"""
extract_state.py
Connects briefly to the populated native profile and extracts the authenticated
cookies and localStorage state into fb_state.json without requiring any UI interaction.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = "./fb_browser_profile"
STATE_FILE = "fb_state.json"

def print_state_summary(path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        cookie_count = len(state.get("cookies", []))
        origin_count = len(state.get("origins", []))
        ls_count = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
        print(f"[+] Extraction Success Summary:")
        print(f"    Cookies captured : {cookie_count}")
        print(f"    Origins captured : {origin_count}")
        print(f"    localStorage keys: {ls_count}")
    except Exception as e:
        print(f"[!] Could not read state file summary: {e}")

def main() -> None:
    print("[*] Initializing Playwright Extraction Pipeline...")

    with sync_playwright() as playwright:
        try:
            # Launch the context pointing to the profile we just authenticated manually
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                channel="chrome",
                headless=True, # Can be headless since the login is already completed
            )

            print(f"[*] Extracting storage state from: {Path(PROFILE_DIR).resolve()}")
            context.storage_state(path=STATE_FILE)
            print(f"[+] State successfully serialized to: {Path(STATE_FILE).resolve()}")

            context.close()
            print_state_summary(STATE_FILE)

        except Exception as e:
            print(f"[!] Extraction failed: {e}")

if __name__ == "__main__":
    main()
