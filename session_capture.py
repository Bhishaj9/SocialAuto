"""
session_capture.py

Captures a fully authenticated Facebook session using standard Playwright with
the system's native Google Chrome, falling back to Microsoft Edge if needed.

Workflow:
  1. Wipe any corrupted profile directory for a 100% clean slate.
  2. Launch a visible, persistent native browser profile.
  3. Open a blank page so you can navigate to Facebook manually.
  4. Wait until you close the browser window or press Ctrl+C.
  5. Save cookies + localStorage to fb_state.json.
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
STATE_FILE = "fb_state.json"

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

    for channel in ("chrome", "msedge"):
        try:
            print(f"[*] Launching persistent browser with channel='{channel}' ...")
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(Path(PROFILE_DIR).resolve()),
                channel=channel,
                headless=False,
                ignore_default_args=["--no-sandbox"],
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
                context.new_page()
                print("[*] Blank page opened. Type https://www.facebook.com in the address bar.")
                print("[*] This avoids SPA navigation hangs from automated goto().")
            except Exception as e:
                print(f"[!] Could not open page: {e}")

            print()
            print("[!] Browser is now open and visible.")
            print("[!] Log in to Facebook, clear any 2FA, dismiss 'Save Device' pop-ups.")
            print("[!] Close the browser window when finished, or press Ctrl+C here.")
            print()
            print("[*] Waiting for you to finish...")

            # Wait until the user closes the browser or interrupts the script.
            disconnected = False
            while not _shutting_down and not disconnected:
                try:
                    browser = context.browser
                    if browser is None or not browser.is_connected():
                        disconnected = True
                        break
                except Exception:
                    disconnected = True
                    break
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
