"""AutoBVB local shadow-mode execution worker.

The worker polls listings.json, drafts pending Facebook listings in a
cloakbrowser-backed persistent profile, stores proof screenshots locally, and
updates local listing state.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from browser_use import BrowserSession
from cloakbrowser import launch_persistent_context_async

import database
import storage

ROOT_DIR = Path(__file__).resolve().parent
PROFILE_DIR = "./fb_browser_profile"
PROOF_FILE = ROOT_DIR / "proof.png"
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
POLL_INTERVAL_SECONDS = 10
SHADOW_MODE = os.getenv("SHADOW_MODE", "True").lower() in {"1", "true", "yes", "on"}

FACEBOOK_ALLOWED_DOMAINS = [
    "facebook.com",
    "*.facebook.com",
    "fbcdn.net",
    "*.fbcdn.net",
    "fbsbx.com",
    "*.fbsbx.com",
]


async def wait_for_cdp_endpoint(timeout_seconds: float = 15.0) -> str:
    """Wait until the cloakbrowser debug endpoint is accepting CDP connections."""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    version_url = f"{CDP_URL}/json/version"
    last_error: Exception | None = None

    while asyncio.get_running_loop().time() < deadline:
        try:
            body = await asyncio.to_thread(_read_url, version_url)
            payload = json.loads(body)
            websocket_url = payload.get("webSocketDebuggerUrl")
            if websocket_url:
                print(f"[worker] cloakbrowser CDP endpoint is ready: {CDP_URL}")
                return CDP_URL
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc

        await asyncio.sleep(0.25)

    raise RuntimeError(f"cloakbrowser CDP endpoint did not become ready at {CDP_URL}: {last_error}")


def _read_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=2.0) as response:
        return response.read().decode("utf-8")


async def launch_stealth_browser() -> Any:
    # Self-healing: Aggressively remove all Singleton* files in the profile
    import glob
    profile_path = "/app/fb_browser_profile"
    print(f"[worker] Pre-flight: Clearing locks in {profile_path}...")
    for lock_file in glob.glob(f"{profile_path}/Singleton*"):
        try:
            Path(lock_file).unlink()
            print(f"[worker] Deleted stale lock file: {lock_file}")
        except Exception as e:
            print(f"[worker] Failed to remove {lock_file}: {e}")

    print(f"[worker] Launching cloakbrowser persistent context at {PROFILE_DIR}...")
    (ROOT_DIR / "fb_browser_profile").mkdir(parents=True, exist_ok=True)

    context = await launch_persistent_context_async(
        user_data_dir=PROFILE_DIR,
        headless=True,  # Changed to True for Docker compatibility
        viewport={"width": 1440, "height": 1000},
        args=[f"--remote-debugging-port={CDP_PORT}"],
    )

    await wait_for_cdp_endpoint()
    return context


def build_browser_session() -> BrowserSession:
    """Bridge browser-use into the already-launched cloakbrowser session."""

    print("[worker] Handing cloakbrowser's persistent CDP session to browser-use...")
    return BrowserSession(
        cdp_url=CDP_URL,
        is_local=False,
        keep_alive=True,
        allowed_domains=FACEBOOK_ALLOWED_DOMAINS,
        minimum_wait_page_load_time=1.0,
        wait_for_network_idle_page_load_time=3.0,
        wait_between_actions=0.75,
    )


async def draft_listing(listing: dict[str, Any]) -> None:
    listing_id = listing["id"]
    context = None
    browser_session: BrowserSession | None = None

    print(f"[worker] Starting shadow draft workflow for listing {listing_id}.")
    database.update_listing_status(listing_id, "processing")

    try:
        chosen_caption = listing.get("final_text")
        if not isinstance(chosen_caption, str) or not chosen_caption.strip():
            raise ValueError(f"Listing {listing_id} is missing final_text from HITL approval.")
        chosen_caption = chosen_caption.strip()

        image_paths = listing.get("image_paths", [])
        if isinstance(image_paths, str):
            image_paths = [image_paths]
        elif not isinstance(image_paths, list):
            raise ValueError(f"Listing {listing_id} has invalid image_paths payload.")

        # Ensure all paths are absolute strings for Playwright inside Docker
        candidate_image_paths = [str(Path(p).resolve()) for p in image_paths if p and p is not None]
        abs_image_paths = [path for path in candidate_image_paths if Path(path).exists()]
        missing_image_paths = sorted(set(candidate_image_paths) - set(abs_image_paths))
        if missing_image_paths:
            print(f"[worker] Skipping missing image(s): {', '.join(missing_image_paths)}")

        if not abs_image_paths:
            raise FileNotFoundError(f"Listing {listing_id} has no readable approved image paths.")

        print(f"[worker] Loaded pre-approved caption for listing {listing_id}: {chosen_caption[:50]}...")
        print(f"[worker] Using {len(abs_image_paths)} verified approved image(s).")
        print(f"[Debug] Current working directory: {os.getcwd()}")

        storage_dir = "/app/local_storage"
        if os.path.isdir(storage_dir):
            print(f"[Debug] {storage_dir} exists.")
            print("[Debug] Files visible inside /app/local_storage:")
            for filename in os.listdir(storage_dir):
                full_path = os.path.join(storage_dir, filename)
                size = os.path.getsize(full_path) if os.path.isfile(full_path) else "N/A"
                print(f"[Debug] - {filename} | file={os.path.isfile(full_path)} | size={size} bytes")
        else:
            print(f"[Debug] WARNING: {storage_dir} does not exist. Volume mount likely failed.")

        if PROOF_FILE.exists():
            print(f"[worker] Removing stale proof file before new run: {PROOF_FILE}")
            PROOF_FILE.unlink()

        context = await launch_stealth_browser()
        auth_state_file = ROOT_DIR / "fb_state.json"
        if auth_state_file.exists():
            await context.add_cookies(json.loads(auth_state_file.read_text()).get("cookies", []))
            print("[worker] Cross-OS cookies injected from fb_state.json.")

        browser_session = build_browser_session()

        print(f"[worker] Executing Deterministic Playwright Script for {len(abs_image_paths)} images...")
        print("[worker] Connecting natively to CloakBrowser via direct CDP endpoint...")
        import playwright.async_api as pw_api
        
        # We fetch the raw browser instance linked via cloakbrowser's port 9222
        async with pw_api.async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            # Grab the existing context or configure a standard clean context handle
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            
            try:
                # 1. Navigate and wait for feed to load
                await page.goto("https://www.facebook.com")
                await page.wait_for_timeout(random.randint(4000, 7000))
                
                # 1. Dismiss potential blockers (modals, welcome pop-ups)
                for _ in range(3):
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)

                # 2. Robust Locator Strategy
                # We look for ANY button containing "What" and role="button"
                # This ignores the specific "Gaurav" part of the string
                composer_locator = page.locator('div[role="button"]:has-text("What")').first
                
                # 3. Attempt to click with aggressive force and retries
                try:
                    await composer_locator.click(force=True, timeout=10000)
                    print("[worker] Successfully opened the Facebook composer.")
                except Exception as e:
                    # If that fails, try a broader fallback
                    print(f"[worker] First composer click failed, trying fallback: {e}")
                    fallback = page.locator('div[role="button"]').filter(has_text="What").first
                    await fallback.click(force=True)

                await page.wait_for_timeout(3000)
                
                # 3. Bulk Upload Images via the hidden input
                file_input = page.locator('input[type="file"][accept*="image"]').first
                await file_input.set_input_files(abs_image_paths)
                print(f"[worker] Attached {len(abs_image_paths)} images directly to DOM input.")
                await page.wait_for_timeout(random.randint(5000, 7000))
                
                # 4. Inject Text using actual keyboard simulation
                # This triggers all the necessary React/Lexical input events
                editor_locator = page.locator('[contenteditable="true"]').first
                await editor_locator.click()
                await page.wait_for_timeout(500)
                
                # Type the caption with a human-like delay between characters
                # This is slow enough to trigger state updates but fast enough for automation
                await page.keyboard.type(chosen_caption, delay=20) 
                print("[worker] Injected caption via keyboard emulation.")
                await page.wait_for_timeout(2000)
                
                # 5. Capture Proof
                await page.screenshot(path="/app/proof.png")
                print("[worker] Shadow run complete. Proof saved via native DOM snapshot.")
                
            finally:
                await page.close()
                await browser.close()

        if not PROOF_FILE.exists():
            print("[worker] proof.png was not found after agent run. Capturing fallback screenshot...")
            await browser_session.take_screenshot(path=str(PROOF_FILE), full_page=True)
            print(f"[worker] Fallback screenshot saved at {PROOF_FILE}.")
        else:
            print(f"[worker] Agent-created proof found at {PROOF_FILE}.")

        destination_name = f"{listing_id}_proof.png"
        print(f"[worker] Saving proof to local mock storage as {destination_name}...")
        saved_path = storage.upload_proof(PROOF_FILE, destination_name)
        print(f"[worker] Proof upload simulation complete: {saved_path}")

        success_status = "shadow_success" if SHADOW_MODE else "completed"
        database.update_listing_status(listing_id, success_status)
        print(f"[worker] Listing {listing_id} marked as {success_status}.")

    except Exception as exc:
        print(f"[worker] ERROR while processing listing {listing_id}: {exc}")
        database.update_listing_status(listing_id, "shadow_failed")
        raise

    finally:
        if browser_session is not None:
            print("[worker] Stopping browser-use CDP session...")
            try:
                await browser_session.stop()
            except Exception as exc:
                print(f"[worker] Warning: browser-use session stop failed: {exc}")

        if context is not None:
            print("[worker] Closing cloakbrowser context...")
            try:
                await context.close()
            except Exception as exc:
                print(f"[worker] Warning: cloakbrowser context close failed: {exc}")


async def main() -> None:
    print("[worker] AutoBVB local worker started.")
    print(f"[worker] Polling every {POLL_INTERVAL_SECONDS} seconds.")
    print(f"[worker] Local listings file: {database.LISTINGS_FILE}")
    print(f"[worker] Local proof storage: {storage.LOCAL_PROOF_DIR}")

    while True:
        try:
            listing = database.get_pending_listing()
            if listing is None:
                print(f"[worker] Sleeping for {POLL_INTERVAL_SECONDS} seconds...")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            await draft_listing(listing)

        except Exception as exc:
            print(f"[worker] Loop error: {exc}")
            print(f"[worker] Sleeping for {POLL_INTERVAL_SECONDS} seconds before retry...")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
