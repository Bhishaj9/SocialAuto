"""Export a Facebook Playwright auth state for cross-OS worker reuse."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto("https://www.facebook.com")
            print("[export_auth] Log in manually. Saving auth state in 60 seconds...")
            await page.wait_for_timeout(60_000)
            await context.storage_state(path="fb_state.json")
            print("[export_auth] Saved Facebook auth state to fb_state.json.")
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
