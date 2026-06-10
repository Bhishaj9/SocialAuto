"""
session_capture.py

Stealth Facebook Session Capture with Hardware-Spoofing Overrides
Captures a fully authenticated Facebook session using async Playwright with
anti-detection browser fingerprint spoofing to bypass Meta's automation detection.
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROFILE_DIR = "./fb_browser_profile/test_agent_01"
STATE_FILE = "local_storage/profiles/test_agent_01/fb_state.json"

ANTI_DETECTION_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-sandbox",
    "--disable-setuid-sandbox"
]

VIEWPORT = {"width": 1280, "height": 720}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
LOCALE = "en-US"
TIMEZONE_ID = "Asia/Kolkata"

INIT_SCRIPT = """
    // 1. Remove the webdriver property
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    
    // 2. Mock Chrome runtime properties
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
    
    // 3. Spoof Plugins array (so it is not empty)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' }
        ]
    });
    
    // 4. Force regular consumer hardware arrays
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clean_profile(profile_dir: str) -> None:
    """Nuke the profile directory so every run starts from a 100% clean slate."""
    path = Path(profile_dir)
    if path.exists():
        print(f"[*] Removing stale profile: {path.resolve()}")
        shutil.rmtree(path)
        print("[*] Profile directory wiped clean.")


def print_state_summary(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        cookie_count = len(state.get("cookies", []))
        origin_count = len(state.get("origins", []))
        ls_count = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
        print(f"    Cookies captured : {cookie_count}")
        print(f"    Origins captured : {origin_count}")
        print(f"    localStorage keys: {ls_count}")
    except Exception:
        print("    (Could not parse state file; profile data is still saved on disk)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    # Step 0: Wipe any stale/corrupted profile from interrupted logins.
    clean_profile(PROFILE_DIR)

    print("=" * 60)
    print(" Facebook Stealth Session Capture (Hardware-Spoofed)")
    print("=" * 60)
    print(f"[*] Profile directory : {Path(PROFILE_DIR).resolve()}")
    print(f"[*] State output      : {Path(STATE_FILE).resolve()}")
    print()

    try:
        async with async_playwright() as playwright:
            print("[*] Launching stealth persistent browser context...")
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(Path(PROFILE_DIR).resolve()),
                headless=False,
                args=ANTI_DETECTION_ARGS,
                viewport=VIEWPORT,
                user_agent=USER_AGENT,
                locale=LOCALE,
                timezone_id=TIMEZONE_ID,
            )
            print("[+] Browser context launched with anti-detection overrides.")

            page = await context.new_page()
            print("[+] New page created, injecting stealth init script...")
            await page.add_init_script(INIT_SCRIPT)
            print("[+] Stealth init script injected (webdriver, chrome, plugins, languages).")

            print("[*] Navigating to https://www.facebook.com ...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            print("[+] Facebook loaded. Browser is ready for manual authentication.")

            print()
            print("[!] Browser is now open and visible.")
            print("[!] Log in to Facebook, complete 2FA, dismiss 'Save Device' pop-ups.")
            print("[!] Close the browser window when finished, or press Ctrl+C here.")
            print()
            print("[*] Waiting for you to finish (process will stay alive)...")

            # Keep the process alive indefinitely until user closes browser or Ctrl+C
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                print("\n[*] Keyboard interrupt received.")

            print("\n[*] Browser closed by user. Saving session state ...")
            try:
                await context.storage_state(path=STATE_FILE)
                print(f"[+] Session state saved to {Path(STATE_FILE).resolve()}")
                print_state_summary(STATE_FILE)
            except Exception as e:
                print(f"[!] Could not export state via context: {e}")
                print("[*] Persistent profile data is still saved on disk in:")
                print(f"    {Path(PROFILE_DIR).resolve()}")

            print("[*] Closing browser context ...")
            await context.close()

    except Exception as e:
        print(f"[!] Failed to capture session: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("[+] Done.")


if __name__ == "__main__":
    asyncio.run(main())