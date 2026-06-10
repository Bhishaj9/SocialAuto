"""
session_capture.py

Captures a fully authenticated Facebook session using standard Playwright with
the system's native Google Chrome, falling back to Microsoft Edge if needed.
Injects comprehensive anti-detection masking and init scripts to defeat automated detection.

Workflow:
  1. Wipe any corrupted profile directory for a 100% clean slate.
  2. Launch a visible, persistent native browser profile with high-stealth arguments.
  3. Hook JS injection layer on page creation.
  4. Navigate directly to Facebook.
  5. Wait for up to 180 seconds or until the window is closed.
  6. Save cookies + localStorage to fb_state.json.
"""

import json
import shutil
import signal
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROFILE_DIR = "./fb_browser_profile"
STATE_FILE = "local_storage/profiles/test_agent_01/fb_state.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clean_profile(profile_dir: str) -> None:
    """Nuke the profile directory so every run starts from a 100% clean slate."""
    path = Path(profile_dir)
    if path.exists():
        print(f"[*] Removing corrupted profile: {path.resolve()}")
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


def launch_native_persistent_context(playwright):
    """Launch native Chrome first, then native Edge if Chrome is unavailable."""
    last_error = None

    # High-stealth Chromium launch flags
    stealth_args = [
        "--disable-blink-features=AutomationControlled",
        "--use-fake-ui-for-media-stream",
        "--disable-infobars",
        "--no-sandbox",
    ]

    # Real-world User-Agent string
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # Viewport mapping
    viewport = {"width": 1280, "height": 720}

    for channel in ("chrome", "msedge"):
        try:
            print(f"[*] Launching persistent browser with channel='{channel}' ...")
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(Path(PROFILE_DIR).resolve()),
                channel=channel,
                headless=False,  # Hardcoded visible browser
                args=stealth_args,
                ignore_default_args=["--enable-automation"],
                user_agent=user_agent,
                viewport=viewport,
            )
            print(f"[+] Browser launched using channel='{channel}'.")
            return context
        except PlaywrightError as e:
            last_error = e
            print(f"[!] Could not launch channel='{channel}': {e}")

    raise RuntimeError(
        "Could not launch native Chrome or Edge via Playwright. "
        "Install Google Chrome or Microsoft Edge and try again."
    ) from last_error


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
_shutting_down = False


def _signal_handler(signum, frame):
    global _shutting_down
    _shutting_down = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global _shutting_down

    # Step 0: Wipe any stale/corrupted profile from interrupted logins.
    clean_profile(PROFILE_DIR)

    print("=" * 60)
    print(" Facebook Native Browser Session Capture")
    print("=" * 60)
    print(f"[*] Profile directory : {Path(PROFILE_DIR).resolve()}")
    print(f"[*] State output      : {Path(STATE_FILE).resolve()}")
    print()

    try:
        with sync_playwright() as playwright:
            context = launch_native_persistent_context(playwright)

            # Open a blank page; navigate to Facebook manually in the browser.
            try:
                page = context.new_page()
                
                # Javascript Injection Layer right after the context page is opened
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                """)
                
                print("[*] Navigating directly to https://www.facebook.com...")
                page.goto("https://www.facebook.com")
            except Exception as e:
                print(f"[!] Could not open page or navigate: {e}")

            print()
            print("[!] Browser is now open and visible.")
            print("[!] Log in to Facebook, clear any 2FA, dismiss 'Save Device' pop-ups.")
            print("[!] You have 180 seconds to complete the login/checkpoint...")
            print("[!] Close the browser window when finished, or press Ctrl+C here.")
            print()
            print("[*] Waiting for you to finish...")

            # Wait until the user closes the browser or interrupts the script or times out.
            start_time = time.time()
            disconnected = False
            last_print_time = 0
            while not _shutting_down and not disconnected:
                elapsed = time.time() - start_time
                if elapsed > 180:
                    print(f"\n[*] 180-second timeout reached. Saving state...")
                    break
                try:
                    # Check if pages exist to see if browser is closed
                    if not context.pages:
                        disconnected = True
                        break
                except Exception:
                    disconnected = True
                    break
                
                # Print progress update
                if int(elapsed) // 10 > last_print_time:
                    last_print_time = int(elapsed) // 10
                    print(f"    [Time elapsed: {int(elapsed)}s / 180s]")
                    
                time.sleep(1)

            print("\n[*] Saving session state ...")
            try:
                context.storage_state(path=STATE_FILE)
                print(f"[+] Session state saved to {Path(STATE_FILE).resolve()}")
                print_state_summary(STATE_FILE)
            except Exception as e:
                print(f"[!] Could not export state via context: {e}")
                print("[*] Persistent profile data is still saved on disk in:")
                print(f"    {Path(PROFILE_DIR).resolve()}")

            print("[*] Closing browser context ...")
            try:
                context.close()
            except Exception:
                pass

    except Exception as e:
        print(f"[!] Failed to capture session: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("[+] Done.")


if __name__ == "__main__":
    main()
