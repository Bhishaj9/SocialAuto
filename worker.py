"""AutoBVB v5.0 — Phase 3 Supabase Worker.

Asynchronous continuous-polling execution layer that claims approved listings
from Supabase database and posts them to Facebook via a Playwright persistent
browser context with cloakbrowser-grade stealth fingerprinting.

Architecture:
  ┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
  │  Supabase DB    │────▶│  Polling Loop    │────▶│  Browser Context  │
  │  (approved row) │     │  (10s interval)  │     │  (Playwright +    │
  └─────────────────┘     └──────────────────┘     │   Stealth Args)   │
                                                    └───────┬───────────┘
                                                            │
                                              ┌─────────────┴──────────────┐
                                              │  Native Text Paste (JS)    │
                                              │  Native Image Upload (FC)  │
                                              │  Proof Screenshot Capture  │
                                              └────────────────────────────┘

Key Design Decisions:
  - Completely decoupled from legacy JSON file-based store and locking mechanisms.
  - Relies on PostgreSQL RPC function `claim_next_approved_listing` to atomically
    claim jobs via skip-locked row transactions.
  - Automatically downloads binary image assets from public storage bucket URLs
    into a local temporary directory during execution.
  - Robust exception safety ensuring browser context teardown and marking the job
    as failed in Supabase if any execution step crashes or times out.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from database import DatabaseEngine

# ── Configuration ────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", str(ROOT_DIR / "local_storage")))
PROOF_DIR = LOCAL_STORAGE_DIR / "proofs"

POLL_INTERVAL_SECONDS = 10
HEADLESS = os.getenv("WORKER_HEADLESS", "True").lower() in {"1", "true", "yes", "on"}
SHADOW_MODE = os.getenv("SHADOW_MODE", "True").lower() in {"1", "true", "yes", "on"}
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Cloakbrowser-grade stealth launch arguments.
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



# ── Browser Context Factory ─────────────────────────────────────────────────

async def _launch_context(
    playwright_instance,
    state_file: str | Path,
    profile_id: str,
) -> tuple[Browser | None, BrowserContext]:
    """Launch a Playwright Chromium browser and create a persistent stealth context.

    Uses Playwright's launch_persistent_context() to map the browser cache
    directly to os.path.join(local_storage, "browser_contexts", profile_id), with headless=False
    and stealth configuration.
    """
    local_storage_base = os.getenv("AUTOBVB_LOCAL_STORAGE", "local_storage")
    user_data_dir = os.path.join(local_storage_base, "browser_contexts", profile_id)
    print(f"[Worker] Launching persistent stealth Chromium browser (headless={HEADLESS})...")
    print(f"[Worker]   User-Agent: {STEALTH_USER_AGENT[:60]}...")
    print(f"[Worker]   Viewport:   {VIEWPORT['width']}x{VIEWPORT['height']}")
    print(f"[Worker]   State file: {state_file}")
    print(f"[Worker]   User Data:  {user_data_dir}")

    # Read the state file and normalise to Playwright's expected format.
    state_file_path = Path(state_file) if isinstance(state_file, str) else state_file
    raw_state = json.loads(state_file_path.read_text(encoding="utf-8"))
    if isinstance(raw_state, list):
        # Flat cookie array → wrap into Playwright storage_state structure.
        raw_state = {"cookies": raw_state, "origins": []}


    context = await playwright_instance.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=HEADLESS,
        args=STEALTH_CHROMIUM_ARGS,
        ignore_default_args=["--enable-automation"],
        viewport=VIEWPORT,
        user_agent=STEALTH_USER_AGENT,
        bypass_csp=True,
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )

    # Manually inject the cookies and local storage state into the persistent context
    if "cookies" in raw_state:
        await context.add_cookies(raw_state["cookies"])
        print(f"[Worker] Injected {len(raw_state['cookies'])} cookies manually into context.")

    print("[Worker] Browser context initialized with stealth fingerprint masking.")
    return None, context


# ── Native Text Paste (JavaScript Clipboard Injection) ───────────────────────

async def _paste_text_native(page: Page, text: str) -> None:
    """Inject text into the focused editor via a synthetic clipboard paste event."""
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

        if (el.isContentEditable) {
            document.execCommand('insertText', false, text);
        } else if ('value' in el) {
            el.value = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }""", text)

    print(f"[Worker] Pasted {len(text)} characters via native clipboard injection.")


# ── Native Image Upload (Playwright File Chooser) ───────────────────────────

async def _upload_images_native(page: Page, image_paths: list[str], dialog: Any = None) -> None:
    """Attach images to the Facebook composer via Playwright's file chooser API."""
    if dialog:
        photo_button = dialog.locator('text="Photo/video"').first
        if not await photo_button.is_visible():
            photo_button = dialog.get_by_label("Photo/video", exact=False).first
    else:
        photo_button = page.get_by_label("Photo/video", exact=False).first
        
    if not await photo_button.is_visible():
        photo_button = page.get_by_text("Photo/video", exact=False).first

    print(f"[Worker] Triggering file chooser for {len(image_paths)} image(s)...")

    async with page.expect_file_chooser() as fc_info:
        await photo_button.click()

    file_chooser = await fc_info.value
    await file_chooser.set_files(image_paths)

    print(f"[Worker] Attached {len(image_paths)} image(s) via native file chooser.")
    await page.wait_for_timeout(random.randint(3000, 5000))


# ── Proof Screenshot Capture ────────────────────────────────────────────────

async def _capture_proof(page: Page, listing_id: str) -> Path:
    """Capture a full-page verification screenshot to local_storage/proofs/."""
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    proof_path = PROOF_DIR / f"{listing_id}_proof.png"
    await page.screenshot(path=str(proof_path), full_page=True)
    print(f"[Worker] Proof screenshot saved: {proof_path}")
    return proof_path


# ── Asset Download Helper ───────────────────────────────────────────────────

async def _download_assets(original_assets: list[str], temp_dir_path: Path) -> list[str]:
    """Download public image URLs into a temporary directory asynchronously."""
    def sync_download():
        local_paths = []
        for index, url in enumerate(original_assets):
            if not url:
                continue
            parsed_url = urllib.parse.urlparse(url)
            filename = Path(parsed_url.path).name
            if not filename or filename.strip() == "":
                filename = f"image_{index}.jpg"
            # Path traversal guard:
            filename = Path(filename).name
            if not any(filename.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                filename += ".jpg"
            local_path = temp_dir_path / filename
            print(f"[Worker] Downloading asset from {url} to {local_path}...")
            urllib.request.urlretrieve(url, str(local_path))
            local_paths.append(str(local_path.resolve()))
        return local_paths

    return await asyncio.to_thread(sync_download)


# ── Core Task Executor ───────────────────────────────────────────────────────

async def _execute_listing(listing: dict[str, Any]) -> None:
    """Execute a single approved listing through the full browser pipeline.

    Lifecycle: claim → download images → launch browser → navigate → paste text
    → upload images → (optionally post) → capture proof → update status.

    The browser context is ALWAYS closed in the finally block, regardless
    of success or failure, to prevent memory/thread/port leaks.
    """
    listing_id: str = listing["id"]
    browser: Browser | None = None
    context: BrowserContext | None = None

    db_engine = DatabaseEngine()

    try:
        # ── Extract and validate task payload ────────────────────────────
        profile_id = listing.get("profile_id", "default_profile")
        if not isinstance(profile_id, str) or not profile_id.strip():
            profile_id = "default_profile"
        profile_id = profile_id.strip()

        if not PROFILE_ID_PATTERN.fullmatch(profile_id) or profile_id in {".", ".."}:
            raise ValueError(f"Unsafe profile_id identifier: {profile_id!r}")

        final_text = listing.get("final_approved_text", "")
        if not isinstance(final_text, str) or not final_text.strip():
            raise ValueError(f"Listing {listing_id} is missing final_approved_text content.")
        final_text = final_text.strip()

        original_assets = listing.get("original_assets", [])
        if isinstance(original_assets, str):
            original_assets = [original_assets]
        elif not isinstance(original_assets, list):
            raise ValueError(f"Listing {listing_id} has invalid original_assets payload.")

        if not original_assets:
            raise FileNotFoundError(f"Listing {listing_id}: original_assets is empty.")

        print(f"[Worker] == Task Payload ==")
        print(f"[Worker]   Listing ID : {listing_id}")
        print(f"[Worker]   Profile    : {profile_id}")
        print(f"[Worker]   Caption    : {final_text[:80]}...")
        print(f"[Worker]   Images URL : {len(original_assets)} URL(s)")

        # Dynamic Profile Path Resolution:
        local_storage_base = os.getenv("AUTOBVB_LOCAL_STORAGE", "local_storage")
        state_dir = os.path.join(local_storage_base, "profiles", profile_id)
        state_file = os.path.join(state_dir, "fb_state.json")

        # Graceful Failures for Missing States:
        if not os.path.isfile(state_file):
            print(f"[Worker] Missing authentication state file for Profile: {profile_id} at {state_file}")
            try:
                db_engine.mark_failed(
                    listing_id,
                    error_message=f"Authentication profile state missing for {profile_id}. Please upload state file."
                )
            except Exception as status_exc:
                print(f"[Worker] CRITICAL: Failed to update status to 'failed': {status_exc}")
            return

        # Download images into a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            abs_image_paths = await _download_assets(original_assets, temp_dir_path)

            if not abs_image_paths:
                raise FileNotFoundError(f"Listing {listing_id}: failed to download any valid image files.")

            async with async_playwright() as pw:
                browser, context = await _launch_context(pw, state_file, profile_id)
                page: Page = await context.new_page()
                await page.set_viewport_size(VIEWPORT)

                if os.getenv("AUTOBVB_MOCK_WORKER", "False").lower() in {"1", "true", "yes", "on"}:
                    print("[Worker] MOCK WORKER MODE - Navigating to https://example.com and capturing screenshot...")
                    await page.goto("https://example.com")
                    await _capture_proof(page, listing_id)
                    db_engine.mark_completed(listing_id)
                    print(f"[Worker] Listing {listing_id} completed successfully (MOCK).")
                    return

                # ── Navigate to Facebook ─────────────────────────────────────
                print("[Worker] Navigating to https://www.facebook.com...")
                await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
                await page.wait_for_timeout(random.randint(3000, 5000))

                # Dismiss potential modal overlays (cookie consent, notifications).
                for _ in range(3):
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)

                # Wait a brief moment to allow Facebook client-side redirection to happen.
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
                    if HEADLESS:
                        print("\n[Worker] Checkpoint detected in HEADLESS mode. Skipping human intervention sleep.")
                    else:
                        print("\n[HUMAN INTERVENTION REQUIRED] 2FA/CAPTCHA window active! You have 2 minutes to manually clear the checkpoint in the opened browser window...")
                        await asyncio.sleep(120)
                        print("[Worker] Resuming execution after human intervention window...")

                # ── Open the post composer ───────────────────────────────────
                print("[Worker] Locating and opening the post composer...")
                composer_trigger = page.get_by_text("What's on your mind", exact=False).first
                await composer_trigger.click()
                dialog = page.locator("div[role='dialog']")
                await dialog.wait_for(state="visible", timeout=15000)
                await page.wait_for_timeout(random.randint(1000, 2000))

                # ── Upload images via native file chooser ────────────────────
                await _upload_images_native(page, abs_image_paths, dialog=dialog)

                # ── Focus the text editor and paste caption ──────────────────
                print("[Worker] Focusing composer text area...")
                editor = dialog.get_by_role("textbox", name="What's on your mind").first if dialog else page.get_by_role("textbox", name="What's on your mind").first
                if not await editor.is_visible():
                    editor = dialog.locator('[contenteditable="true"][role="textbox"]').first if dialog else page.locator('[contenteditable="true"][role="textbox"]').first
                
                try:
                    await editor.click(timeout=5000)
                except Exception as e:
                    print(f"[Worker] Basic editor click failed ({e}). Attempting force click and focus override...")
                    try:
                        await editor.click(force=True)
                    except Exception:
                        await editor.focus()
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

        # ── Update status to completed ───────────────────────────────────────
        db_engine.mark_completed(listing_id)
        print(f"[Worker] Listing {listing_id} completed successfully.")

    except Exception as exc:
        print(f"[Worker] ERROR processing listing {listing_id}: {exc}")
        try:
            db_engine.mark_failed(listing_id, error_message=str(exc))
        except Exception as status_exc:
            print(f"[Worker] CRITICAL: Failed to update status to 'failed': {status_exc}")
        raise

    finally:
        # ── Strict fail-safe browser cleanup ─────────────────────────────
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
    """Entrypoint: infinite polling loop that claims and executes approved listings from database."""
    print("=" * 64)
    print("  AutoBVB v5.0  *  Phase 3 Supabase Worker")
    print("=" * 64)
    print(f"  Proof storage : {PROOF_DIR}")
    print(f"  Poll interval : {POLL_INTERVAL_SECONDS}s")
    print(f"  Headless      : {HEADLESS}")
    print(f"  Shadow mode   : {SHADOW_MODE}")
    print("=" * 64)

    db_engine = DatabaseEngine()

    while True:
        try:
            listing = db_engine.claim_job_atomically(worker_name="autobvb_muscle_node_01")
            if listing is None:
                # Log a debug message and loop back cleanly
                print(f"[Worker] No approved jobs available in queue. Sleeping...")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            print(f"[Worker] Claimed approved listing: {listing['id']}")
            try:
                await _execute_listing(listing)
            except Exception as e:
                print(f"[Worker] Failed executing claimed listing {listing['id']}: {e}")

            # Sleep briefly before looking for the next task
            await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\n[Worker] Received shutdown signal. Exiting gracefully.")
            break
        except Exception as exc:
            print(f"[Worker] Loop error: {exc}")
            print(f"[Worker] Retrying in {POLL_INTERVAL_SECONDS}s...")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
