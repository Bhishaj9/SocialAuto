"""AutoBVB — UI-Driven Cookie Sync Layer.

Launches a visual Playwright persistent browser context so the operator can
manually authenticate with Facebook (including 2FA), then extracts the live
session cookies and writes them into the strict Playwright state file used
by the worker pipeline.

No file-system cookie scraping. No browser-cookie3. Zero OS lock conflicts.
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright


ROOT_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = str(ROOT_DIR / "fb_browser_profile" / "test_agent_01")
STATE_OUTPUT = ROOT_DIR / "local_storage" / "profiles" / "test_agent_01" / "fb_state.json"

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
]


async def main() -> None:
    print("=" * 72)
    print("  AutoBVB  -  Cookie Sync Layer (UI-Driven)")
    print("=" * 72)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            args=STEALTH_ARGS,
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded")

        print()
        print("[COOKIE SYNC LAYER ACTIVE] Please log into your target Facebook")
        print("account in the opened window, complete 2FA, and ensure you see")
        print("your News Feed. Once loaded, click Enter in this terminal to")
        print("save and close.")
        print()
        print(">>> DO NOT close the browser window manually. Press Enter here. <<<")
        print()

        # Hold the terminal open until the operator presses Enter.
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Extract live cookies from the authenticated context.
        try:
            raw_cookies = await context.cookies()
        except Exception as e:
            print(f"[Extractor] ERROR: Browser was closed before cookies could be extracted: {e}")
            print("[Extractor] Please re-run the script and press Enter WITHOUT closing the browser window.")
            sys.exit(1)

        output_payload = {
            "cookies": raw_cookies,
            "origins": [],
        }

        STATE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        STATE_OUTPUT.write_text(
            json.dumps(output_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"[Extractor] SUCCESS: Exported {len(raw_cookies)} cookies to {STATE_OUTPUT}")

        # Gracefully close context.
        try:
            await context.close()
        except Exception:
            pass

    print("[Extractor] Browser context closed. Cookie sync complete.")


if __name__ == "__main__":
    asyncio.run(main())