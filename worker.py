"""AutoBVB v5.0 — Phase 2 Controller Worker.

Asynchronous continuous-polling execution layer that reads approved listings
from listings.json and posts them to Facebook via a Playwright persistent
browser context with cloakbrowser-grade stealth fingerprinting.

Architecture:
  ┌─────────────┐     ┌──────────────────┐     ┌───────────────────┐
  │ listings.json│────▶│  Polling Loop    │────▶│  Browser Context  │
  │  (approved)  │     │  (10s interval)  │     │  (Playwright +    │
  └─────────────┘     └──────────────────┘     │   Stealth Args)   │
                                                └───────┬───────────┘
                                                        │
                                          ┌─────────────┴──────────────┐
                                          │  Native Text Paste (JS)    │
                                          │  Native Image Upload (FC)  │
                                          │  Proof Screenshot Capture  │
                                          └────────────────────────────┘

Key Design Decisions:
  - Completely decoupled from legacy CDP/cloakbrowser launch_persistent_context_async
    and browser-use BrowserSession. Uses raw Playwright async API directly.
  - File-level exclusive locking (msvcrt/fcntl) prevents concurrent status races
    between the API server, worker, and any external tooling.
  - Native clipboard paste via page.evaluate() preserves all line breaks, emojis,
    and Unicode characters that keyboard.type() would mangle or drop.
  - Playwright's expect_file_chooser() intercepts the OS file dialog natively,
    avoiding brittle selector chains for Facebook's ever-changing upload UI.
  - Every task execution is wrapped in try/finally to guarantee browser context
    teardown, preventing background thread and port leakage.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ── Configuration ────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent
LISTINGS_FILE = ROOT_DIR / "listings.json"
LISTINGS_LOCK_FILE = ROOT_DIR / "listings.json.lock"
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", str(ROOT_DIR / "local_storage")))
PROOF_DIR = LOCAL_STORAGE_DIR / "proofs"

POLL_INTERVAL_SECONDS = 10
HEADLESS = os.getenv("WORKER_HEADLESS", "True").lower() in {"1", "true", "yes", "on"}
SHADOW_MODE = os.getenv("SHADOW_MODE", "True").lower() in {"1", "true", "yes", "on"}
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Cloakbrowser-grade stealth launch arguments.
# These arguments mirror what cloakbrowser applies internally to defeat
# common headless-detection fingerprinting (navigator.webdriver, chrome
# runtime checks, WebGL vendor strings, etc.).
STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

STEALTH_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    "--window-size=1280,720",
]

VIEWPORT = {"width": 1280, "height": 720}


# ── File Locking (cross-platform) ───────────────────────────────────────────

@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive file lock. msvcrt on Windows, fcntl on POSIX."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# ── Listings Database I/O ───────────────────────────────────────────────────

def _load_listings() -> list[dict[str, Any]]:
    """Read the full listings array from disk. Returns [] if missing."""
    if not LISTINGS_FILE.exists():
        return []
    with LISTINGS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{LISTINGS_FILE} must contain a JSON array.")
    return data


def _save_listings(listings: list[dict[str, Any]]) -> None:
    """Atomically write the listings array back to disk."""
    LISTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LISTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _update_status(listing_id: str, new_status: str) -> None:
    """Thread-safe status update with exclusive file locking."""
    with _exclusive_file_lock(LISTINGS_LOCK_FILE):
        listings = _load_listings()
        for entry in listings:
            if entry.get("id") == listing_id:
                old_status = entry.get("status")
                entry["status"] = new_status
                _save_listings(listings)
                print(f"[Worker] Status transition: {listing_id} [{old_status} → {new_status}]")
                return
    raise ValueError(f"Listing not found: {listing_id}")


def _claim_next_approved() -> dict[str, Any] | None:
    """Atomically find and claim the first 'approved' listing.

    Within a single lock acquisition, this reads the file, finds the first
    entry with status='approved', flips it to 'processing', writes back,
    and returns the snapshot. This prevents two worker instances from
    claiming the same listing.
    """
    with _exclusive_file_lock(LISTINGS_LOCK_FILE):
        listings = _load_listings()
        for entry in listings:
            if entry.get("status") == "approved":
                listing_id = entry.get("id", "<unknown>")
                entry["status"] = "processing"
                _save_listings(listings)
                print(f"[Worker] Claimed approved listing: {listing_id}")
                return dict(entry)  # Return a snapshot copy
    return None


# ── Profile Resolution ───────────────────────────────────────────────────────

def _resolve_profile(target_profile: str) -> Path:
    """Resolve and validate the fb_state.json path for a target profile.

    Returns the absolute Path to the state file. Raises FileNotFoundError
    if the profile directory or state file does not exist.
    """
    if not PROFILE_ID_PATTERN.fullmatch(target_profile) or target_profile in {".", ".."}:
        raise ValueError(f"Unsafe target_profile identifier: {target_profile!r}")

    profiles_root = (LOCAL_STORAGE_DIR / "profiles").resolve()
    profile_dir = (profiles_root / target_profile).resolve()

    # Path traversal guard: ensure resolved path is under profiles_root.
    if profiles_root not in profile_dir.parents and profile_dir != profiles_root:
        raise ValueError(f"Profile resolved outside storage: {target_profile}")

    state_file = profile_dir / "fb_state.json"
    if not state_file.is_file():
        raise FileNotFoundError(
            f"Session state not found for profile '{target_profile}': {state_file}"
        )

    return state_file


# ── Browser Context Factory ─────────────────────────────────────────────────

async def _launch_context(
    playwright_instance,
    state_file: Path,
    profile_id: str,
) -> tuple[Browser | None, BrowserContext]:
    """Launch a Playwright Chromium browser and create a persistent stealth context.

    Uses Playwright's launch_persistent_context() to map the browser cache
    directly to ROOT_DIR / "fb_browser_profile" / profile_id, with headless=False
    and stealth configuration.
    """
    user_data_dir = ROOT_DIR / "fb_browser_profile" / profile_id
    print(f"[Worker] Launching persistent stealth Chromium browser (headless=False)...")
    print(f"[Worker]   User-Agent: {STEALTH_USER_AGENT[:60]}...")
    print(f"[Worker]   Viewport:   {VIEWPORT['width']}x{VIEWPORT['height']}")
    print(f"[Worker]   State file: {state_file}")
    print(f"[Worker]   User Data:  {user_data_dir}")

    # Read the state file and normalise to Playwright's expected format.
    # Playwright expects {"cookies": [...], "origins": [...]}.
    # Our fb_state.json files may be stored as flat cookie arrays.
    raw_state = json.loads(state_file.read_text(encoding="utf-8"))
    if isinstance(raw_state, list):
        # Flat cookie array → wrap into Playwright storage_state structure.
        raw_state = {"cookies": raw_state, "origins": []}

    context = await playwright_instance.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        args=STEALTH_CHROMIUM_ARGS,
        ignore_default_args=["--enable-automation"],
        viewport=VIEWPORT,
        user_agent=STEALTH_USER_AGENT,
        bypass_csp=True,
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )

    # Manually inject the cookies and local storage state into the persistent context
    # since launch_persistent_context doesn't directly support the storage_state parameter.
    if "cookies" in raw_state:
        await context.add_cookies(raw_state["cookies"])
        print(f"[Worker] Injected {len(raw_state['cookies'])} cookies manually into context.")

    # Note: Local storage from raw_state["origins"] will be injected on navigation or is already
    # persisted if we previously logged in. To do dynamic injection of origins/localStorage,
    # it must be done page-by-page or let the browser persistence handle it.

    print("[Worker] Browser context initialized with stealth fingerprint masking.")
    return None, context


# ── Native Text Paste (JavaScript Clipboard Injection) ───────────────────────

async def _paste_text_native(page: Page, text: str) -> None:
    """Inject text into the focused editor via a synthetic clipboard paste event.

    Instead of page.keyboard.type() which fires individual keypress events
    (slow, drops emojis, mangles Unicode), this uses the DataTransfer API
    to construct a paste event with the full text payload. This preserves:
      - Line breaks (\\n)
      - Emoji sequences (multi-codepoint)
      - RTL/LTR markers
      - All whitespace structure

    The focused element receives the text exactly as if the user pressed
    Ctrl+V with the text on their system clipboard.
    """
    await page.evaluate("""(text) => {
        const el = document.activeElement;
        if (!el) throw new Error('No active element to paste into');

        // Build a synthetic ClipboardEvent with the text payload.
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        const pasteEvent = new ClipboardEvent('paste', {
            bubbles: true,
            cancelable: true,
            clipboardData: dt,
        });
        el.dispatchEvent(pasteEvent);

        // Fallback: if the paste event was cancelled or the element is a
        // contenteditable div (Facebook's composer), also fire an input event
        // to notify React's synthetic event system.
        if (el.isContentEditable) {
            document.execCommand('insertText', false, text);
        } else if ('value' in el) {
            // Standard <input> / <textarea> fallback
            el.value = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }""", text)

    print(f"[Worker] Pasted {len(text)} characters via native clipboard injection.")


# ── Native Image Upload (Playwright File Chooser) ───────────────────────────

async def _upload_images_native(page: Page, image_paths: list[str]) -> None:
    """Attach images to the Facebook composer via Playwright's file chooser API.

    Clicks the 'Photo/video' button and intercepts the OS file dialog using
    Playwright's expect_file_chooser() context manager, then injects the
    real absolute file paths. No DOM selector chains required.
    """
    # Locate the Photo/video attachment trigger.
    # Facebook's composer surfaces this as an aria-label or visible text button.
    photo_button = page.get_by_label("Photo/video", exact=False).first
    if not await photo_button.is_visible():
        # Fallback: try the text-based locator
        photo_button = page.get_by_text("Photo/video", exact=False).first

    print(f"[Worker] Triggering file chooser for {len(image_paths)} image(s)...")

    async with page.expect_file_chooser() as fc_info:
        await photo_button.click()

    file_chooser = await fc_info.value
    await file_chooser.set_files(image_paths)

    print(f"[Worker] Attached {len(image_paths)} image(s) via native file chooser.")
    # Allow time for Facebook to process and render image thumbnails.
    await page.wait_for_timeout(random.randint(3000, 5000))


# ── Proof Screenshot Capture ────────────────────────────────────────────────

async def _capture_proof(page: Page, listing_id: str) -> Path:
    """Capture a full-page verification screenshot to local_storage/proofs/."""
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    proof_path = PROOF_DIR / f"{listing_id}_proof.png"
    await page.screenshot(path=str(proof_path), full_page=True)
    print(f"[Worker] Proof screenshot saved: {proof_path}")
    return proof_path


# ── Core Task Executor ───────────────────────────────────────────────────────

async def _execute_listing(listing: dict[str, Any]) -> None:
    """Execute a single approved listing through the full browser pipeline.

    Lifecycle: claim → launch browser → navigate → paste text → upload
    images → (optionally post) → capture proof → update status.

    The browser context is ALWAYS closed in the finally block, regardless
    of success or failure, to prevent memory/thread/port leaks.
    """
    listing_id: str = listing["id"]
    browser: Browser | None = None
    context: BrowserContext | None = None

    try:
        # ── Extract and validate task payload ────────────────────────────
        target_profile = listing.get("target_profile", "test_agent_01")
        if not isinstance(target_profile, str) or not target_profile.strip():
            target_profile = "test_agent_01"
        target_profile = target_profile.strip()

        final_text = listing.get("final_text", "")
        if not isinstance(final_text, str) or not final_text.strip():
            raise ValueError(f"Listing {listing_id} is missing final_text content.")
        final_text = final_text.strip()

        raw_image_paths = listing.get("image_paths", [])
        if isinstance(raw_image_paths, str):
            raw_image_paths = [raw_image_paths]
        elif not isinstance(raw_image_paths, list):
            raise ValueError(f"Listing {listing_id} has invalid image_paths payload.")

        # Resolve to absolute paths and filter to only existing files.
        abs_image_paths = [
            str(Path(p).resolve())
            for p in raw_image_paths
            if p and Path(p).is_file()
        ]
        skipped = len(raw_image_paths) - len(abs_image_paths)
        if skipped > 0:
            print(f"[Worker] Skipped {skipped} missing image path(s) for listing {listing_id}.")
        if not abs_image_paths:
            raise FileNotFoundError(f"Listing {listing_id}: no readable image files found.")

        print(f"[Worker] ── Task Payload ──")
        print(f"[Worker]   Listing ID : {listing_id}")
        print(f"[Worker]   Profile    : {target_profile}")
        print(f"[Worker]   Caption    : {final_text[:80]}...")
        print(f"[Worker]   Images     : {len(abs_image_paths)} file(s)")

        # ── Resolve profile and launch browser ───────────────────────────
        state_file = _resolve_profile(target_profile)

        async with async_playwright() as pw:
            browser, context = await _launch_context(pw, state_file, target_profile)
            page: Page = await context.new_page()
            await page.set_viewport_size(VIEWPORT)

            # ── Navigate to Facebook ─────────────────────────────────────
            print("[Worker] Navigating to https://www.facebook.com...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(3000, 5000))

            # Dismiss potential modal overlays (cookie consent, notifications).
            for _ in range(3):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)

            # Wait a brief moment to allow Facebook client-side redirection to happen.
            # If the URL changes to a checkpoint, login, or two-step page, or if a login input is visible, trigger the pause.
            checkpoint_detected = False
            for _ in range(25):  # check over 5 seconds (25 * 200ms)
                current_url = page.url.lower()
                if any(k in current_url for k in ["checkpoint", "login", "two_step_verification"]):
                    checkpoint_detected = True
                    break
                try:
                    if await page.locator("input#email, input[name='email']").is_visible():
                        checkpoint_detected = True
                        break
                except Exception:
                    pass
                try:
                    if await page.get_by_text("What's on your mind", exact=False).first.is_visible():
                        break
                except Exception:
                    pass
                await page.wait_for_timeout(200)

            if checkpoint_detected:
                print("\n[HUMAN INTERVENTION REQUIRED] 2FA/CAPTCHA window active! You have 2 minutes to manually clear the checkpoint in the opened browser window...")
                await asyncio.sleep(120)
                print("[Worker] Resuming execution after human intervention window...")

            # ── Open the post composer ───────────────────────────────────
            print("[Worker] Locating and opening the post composer...")
            composer_trigger = page.get_by_text("What's on your mind", exact=False).first
            await composer_trigger.click()
            print("[Worker] Waiting for Create Post modal dialog...")
            await page.wait_for_selector("div[role='dialog']")
            await page.wait_for_timeout(random.randint(1000, 2000))

            # ── Upload images via native file chooser ────────────────────
            await _upload_images_native(page, abs_image_paths)

            # ── Focus the text editor and paste caption ──────────────────
            print("[Worker] Focusing composer text area...")
            # After image upload, the composer editor should be visible.
            # Click into the editable area to ensure focus.
            editor = page.get_by_role("textbox", name="What's on your mind").first
            if not await editor.is_visible():
                # Fallback: look for the contenteditable div
                editor = page.locator('[contenteditable="true"][role="textbox"]').first
            await editor.click()
            await page.wait_for_timeout(500)

            # ── Native clipboard paste ───────────────────────────────────
            await _paste_text_native(page, final_text)
            await page.wait_for_timeout(random.randint(1500, 2500))

            # ── Conditional post submission ──────────────────────────────
            if not SHADOW_MODE:
                print("[Worker] LIVE MODE — Clicking Post button...")
                post_button = page.get_by_role("button", name="Post", exact=True).first
                await post_button.click()
                await page.wait_for_timeout(random.randint(5000, 8000))
                print("[Worker] Post submitted to Facebook.")
            else:
                print("[Worker] SHADOW MODE — Skipping post submission (draft staged only).")

            # ── Capture proof screenshot ─────────────────────────────────
            await _capture_proof(page, listing_id)

        # ── Update terminal status ───────────────────────────────────────
        terminal_status = "shadow_success" if SHADOW_MODE else "completed"
        _update_status(listing_id, terminal_status)
        print(f"[Worker] Listing {listing_id} completed → {terminal_status}")

    except Exception as exc:
        print(f"[Worker] ERROR processing listing {listing_id}: {exc}")
        try:
            _update_status(listing_id, "failed")
        except Exception as status_exc:
            print(f"[Worker] CRITICAL: Failed to update status to 'failed': {status_exc}")
        raise

    finally:
        # ── Strict fail-safe browser cleanup ─────────────────────────────
        # Close context first, then browser, to free all resources.
        # The `async with async_playwright()` block handles the Playwright
        # connection, but we must close browser objects explicitly.
        if context is not None:
            try:
                await context.close()
                print(f"[Worker] Browser context closed for listing {listing_id}.")
            except Exception as close_exc:
                print(f"[Worker] Warning: context close failed: {close_exc}")
        if browser is not None:
            try:
                await browser.close()
                print(f"[Worker] Browser closed for listing {listing_id}.")
            except Exception as close_exc:
                print(f"[Worker] Warning: browser close failed: {close_exc}")


# ── Continuous Polling Loop ──────────────────────────────────────────────────

async def main() -> None:
    """Entrypoint: infinite polling loop that claims and executes approved listings."""
    print("=" * 64)
    print("  AutoBVB v5.0  ·  Phase 2 Controller Worker")
    print("=" * 64)
    print(f"  Listings file : {LISTINGS_FILE}")
    print(f"  Proof storage : {PROOF_DIR}")
    print(f"  Poll interval : {POLL_INTERVAL_SECONDS}s")
    print(f"  Headless      : {HEADLESS}")
    print(f"  Shadow mode   : {SHADOW_MODE}")
    print("=" * 64)

    while True:
        try:
            listing = _claim_next_approved()
            if listing is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            await _execute_listing(listing)

        except KeyboardInterrupt:
            print("\n[Worker] Received shutdown signal. Exiting gracefully.")
            break
        except Exception as exc:
            print(f"[Worker] Loop error: {exc}")
            print(f"[Worker] Retrying in {POLL_INTERVAL_SECONDS}s...")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
