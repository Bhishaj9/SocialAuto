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
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from browser_use import BrowserSession
from cloakbrowser import launch_persistent_context_async

import database
import storage
import vision_map

ROOT_DIR = Path(__file__).resolve().parent
PROOF_FILE = ROOT_DIR / "proof.png"
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", "/app/local_storage"))
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
POLL_INTERVAL_SECONDS = 10
SHADOW_MODE = os.getenv("SHADOW_MODE", "True").lower() in {"1", "true", "yes", "on"}
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

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


def resolve_profile_paths(target_profile: str) -> tuple[str, str]:
    if not PROFILE_ID_PATTERN.fullmatch(target_profile) or target_profile in {".", ".."}:
        raise ValueError(f"Unsafe target_profile value: {target_profile}")

    profile_root = (LOCAL_STORAGE_DIR / "profiles" / target_profile).resolve()
    profiles_root = (LOCAL_STORAGE_DIR / "profiles").resolve()
    if profiles_root not in profile_root.parents:
        raise ValueError(f"target_profile resolved outside profile storage: {target_profile}")

    profile_dir = profile_root / "fb_browser_profile"
    state_json = profile_root / "fb_state.json"
    return str(profile_dir), str(state_json)


async def launch_stealth_browser(profile_dir: str, state_json: str, target_profile: str) -> Any:
    # Self-healing: Aggressively remove all Singleton* files in the profile
    import glob

    if not os.path.exists(state_json):
        print(f"[worker] [ERROR] State context missing for profile: {target_profile}")
        raise FileNotFoundError(f"State context missing for profile: {target_profile}")

    print(f"[worker] Pre-flight: Clearing locks in {profile_dir}...")
    for lock_file in glob.glob(f"{profile_dir}/Singleton*"):
        try:
            Path(lock_file).unlink()
            print(f"[worker] Deleted stale lock file: {lock_file}")
        except Exception as e:
            print(f"[worker] Failed to remove {lock_file}: {e}")

    print(f"[worker] Launching cloakbrowser persistent context for profile {target_profile} at {profile_dir}...")
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    context = await launch_persistent_context_async(
        user_data_dir=profile_dir,
        headless=True,  # Changed to True for Docker compatibility
        viewport={"width": 1280, "height": 720},
        args=[f"--remote-debugging-port={CDP_PORT}"],
    )

    if os.path.exists(state_json):
        with open(state_json, "r", encoding="utf-8") as file:
            state_data = json.load(file)
            cookies = state_data.get("cookies", state_data) if isinstance(state_data, dict) else state_data
            await context.add_cookies(cookies)

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
        target_profile = listing.get("target_profile", "default_profile")
        if not isinstance(target_profile, str) or not target_profile.strip():
            target_profile = "default_profile"
        target_profile = target_profile.strip()
        profile_dir, state_json = resolve_profile_paths(target_profile)

        if not os.path.exists(state_json):
            print(f"[worker] [ERROR] State context missing for profile: {target_profile}")
            database.update_listing_status(listing_id, "shadow_failed")
            return

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

        context = await launch_stealth_browser(profile_dir, state_json, target_profile)

        browser_session = build_browser_session()

        print(f"[worker] Executing Deterministic Playwright Script for {len(abs_image_paths)} images...")
        print("[worker] Connecting natively to CloakBrowser via direct CDP endpoint...")
        import playwright.async_api as pw_api
        
        # We fetch the raw browser instance linked via cloakbrowser's port 9222
        async with pw_api.async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            # Grab the existing context or configure a standard clean context handle
            context = browser.contexts[0] if browser.contexts else await browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            await page.set_viewport_size({"width": 1280, "height": 720})
            
            try:
                # 1. Navigate and wait for feed to load
                await page.goto("https://www.facebook.com")
                await page.wait_for_timeout(random.randint(4000, 7000))
                
                # 1. Dismiss potential blockers (modals, welcome pop-ups)
                for _ in range(3):
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)

                composer_x, composer_y = await vision_map.get_visual_target(
                    page,
                    "facebook_composer_trigger",
                    "the Facebook feed composer trigger that opens the post composer, commonly labeled like What is on your mind",
                )
                await page.mouse.click(composer_x, composer_y)
                print("[worker] Successfully opened the Facebook composer via vision map.")

                await page.wait_for_timeout(3000)
                
                upload_x, upload_y = await vision_map.get_visual_target(
                    page,
                    "facebook_composer_photo_upload",
                    "the Photo/video button inside the open Facebook post composer used to attach listing images",
                )
                async with page.expect_file_chooser() as file_chooser_info:
                    await page.mouse.click(upload_x, upload_y)
                file_chooser = await file_chooser_info.value
                await file_chooser.set_files(abs_image_paths)
                print(f"[worker] Attached {len(abs_image_paths)} images directly to DOM input.")
                await page.wait_for_timeout(random.randint(5000, 7000))
                
                editor_x, editor_y = await vision_map.get_visual_target(
                    page,
                    "facebook_composer_text_area",
                    "the main editable text area inside the open Facebook post composer where the caption should be typed",
                )
                await page.mouse.click(editor_x, editor_y)
                await page.wait_for_timeout(500)
                
                # Type the caption with a human-like delay between characters
                # This is slow enough to trigger state updates but fast enough for automation
                await page.keyboard.type(chosen_caption, delay=20) 
                print("[worker] Injected caption via keyboard emulation.")
                await page.wait_for_timeout(2000)

                if not SHADOW_MODE:
                    post_x, post_y = await vision_map.get_visual_target(
                        page,
                        "facebook_composer_post_button",
                        "the final Post button in the Facebook composer used to confirm publishing the listing",
                    )
                    await page.mouse.click(post_x, post_y)
                    print("[worker] Submitted Facebook post via vision map.")
                    await page.wait_for_timeout(random.randint(5000, 7000))
                
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
