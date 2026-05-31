"""
shadow_test.py

Runs a browser-use shadow test against Facebook using the authenticated
Playwright storage state captured in fb_state.json.

The agent drafts a test real-estate caption but must not click Post/Publish.
After the agent stops, the script saves a full-page screenshot to
shadow_test_success.png as proof of the drafted authenticated state.
"""

import asyncio
import os
from pathlib import Path

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatGoogle

STATE_FILE = Path("fb_state.json").resolve()
SCREENSHOT_FILE = Path("shadow_test_success.png").resolve()

TEST_CAPTION = (
    "Test listing: Beautiful 3 BHK apartment in Noida Extension. "
    "Fully furnished. #NoidaRealEstate #Test"
)


def build_llm() -> ChatGoogle:
    """
    Configure the LLM using Google's Gemini model via browser_use.

    Reads GEMINI_API_KEY from environment automatically.
    """
    return ChatGoogle(
        model="gemini-2.5-flash",
        temperature=0.0,
    )


def build_task() -> str:
    return f"""
You are running a Facebook authenticated-session shadow test.

Steps:
1. Navigate to https://www.facebook.com.
2. Verify the session is logged in by looking for authenticated UI such as the
   navigation bar, profile/account controls, home feed, or a create-post entry point.
3. Click the "What's on your mind?" post creation box.
4. Type this exact caption into the post composer:
   {TEST_CAPTION}
5. Stop once the caption is visible in the composer.

Critical safety rule:
- Do not click Post, Publish, Share, Send, or any equivalent submission button.
- Do not submit the post with keyboard shortcuts.
- This is only a draft shadow test.

The controlling script will save the final full-page screenshot as:
{SCREENSHOT_FILE.name}
"""


async def main() -> None:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"Missing storage state file: {STATE_FILE}")

    browser_session = BrowserSession(
        storage_state=str(STATE_FILE),
        channel="chrome",
        headless=False,
        ignore_default_args=["--no-sandbox"],
        viewport={"width": 1440, "height": 1000},
        allowed_domains=[
            "facebook.com",
            "*.facebook.com",
            "fbcdn.net",
            "*.fbcdn.net",
            "fbsbx.com",
            "*.fbsbx.com",
        ],
        keep_alive=True,
    )

    agent = Agent(
        task=build_task(),
        llm=build_llm(),
        browser_session=browser_session,
        use_vision=True,
        max_actions_per_step=3,
        max_failures=3,
        extend_system_message=(
            "Never click Post, Publish, Share, Send, or any final submission "
            "control. If the requested caption is visible in the composer, "
            "finish immediately and report success."
        ),
    )

    try:
        await agent.run(max_steps=30)
        await browser_session.take_screenshot(path=str(SCREENSHOT_FILE), full_page=True)
        print(f"[+] Shadow test screenshot saved to: {SCREENSHOT_FILE}")
    finally:
        await browser_session.stop()


if __name__ == "__main__":
    asyncio.run(main())
