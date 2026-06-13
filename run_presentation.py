import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    print("[PRESENTATION DRIVER] Starting presentation browser driver...")
    
    # Resolve absolute paths and convert them to file URIs
    root_dir = Path(__file__).resolve().parent
    ingestion_path = (root_dir / "Frontend" / "stitch_autobvb_marketing_portal" / "ingestion_dashboard" / "code.html").resolve()
    cockpit_path = (root_dir / "Frontend" / "stitch_autobvb_marketing_portal" / "governor_cockpit" / "code.html").resolve()
    dummy_image_path = (root_dir / "dummy_flat.jpg").resolve()
    
    print(f"[PRESENTATION DRIVER] Ingestion path: {ingestion_path.as_uri()}")
    print(f"[PRESENTATION DRIVER] Cockpit path: {cockpit_path.as_uri()}")
    print(f"[PRESENTATION DRIVER] Dummy image path: {dummy_image_path}")
    
    if not dummy_image_path.exists():
        print(f"[PRESENTATION DRIVER] WARNING: Dummy image not found at {dummy_image_path}!")
        
    with sync_playwright() as p:
        print("[PRESENTATION DRIVER] Launching visible Chromium browser...")
        browser = p.chromium.launch(headless=False, slow_mo=1500)
        context = browser.new_context()
        page = context.new_page()
        
        # Attach console/error event handlers for debugging/logging
        page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.text}"))
        page.on("pageerror", lambda err: print(f"[BROWSER PAGE ERROR] {err}"))
        
        # Step 1: Dashboard Step
        print("[PRESENTATION DRIVER] Navigating to Ingestion Dashboard...")
        page.goto(ingestion_path.as_uri())
        
        print("[PRESENTATION DRIVER] Filling #broker-id with 'test_agent_01'...")
        page.fill("#broker-id", "test_agent_01")
        
        print("[PRESENTATION DRIVER] Uploading dummy_flat.jpg...")
        page.locator("#file-input").set_input_files(str(dummy_image_path))
        
        print("[PRESENTATION DRIVER] Form filled. 4-second presentational pause...")
        page.wait_for_timeout(4000)
        
        print("[PRESENTATION DRIVER] Clicking Generate AI Variations button...")
        page.click("#generate-btn")
        
        # Step 2: AI Generation Wait
        print("[PRESENTATION DRIVER] Waiting for generation response (up to 120s)...")
        page.wait_for_selector("#status-message:has-text('Draft successfully generated!')", timeout=120000)
        print("[PRESENTATION DRIVER] Draft successfully generated confirmed by UI status message.")
        
        # Step 3: Cockpit Step
        print("[PRESENTATION DRIVER] Navigating to Governor Cockpit...")
        page.goto(cockpit_path.as_uri())
        
        print("[PRESENTATION DRIVER] Waiting for active queue items to load in sidebar...")
        page.wait_for_selector("#queue-container > div:not(.hidden)", timeout=20000)
        
        print("[PRESENTATION DRIVER] Clicking the first active listing item...")
        first_item = page.locator("#queue-container > div:not(.hidden)").first
        first_item.click()
        
        print("[PRESENTATION DRIVER] Queue item clicked. 4-second presentational pause for reading...")
        page.wait_for_timeout(4000)
        
        print("[PRESENTATION DRIVER] Clicking #approve-btn...")
        page.click("#approve-btn")
        
        print("[PRESENTATION DRIVER] Waiting for approval action to be acknowledged...")
        page.wait_for_selector("#approve-btn[disabled]", timeout=10000)
        
        print("[PRESENTATION DRIVER] Approved. Waiting 3 seconds for database sync before exit...")
        page.wait_for_timeout(3000)
        
        print("[PRESENTATION DRIVER] Closing browser pages and context safely...")
        context.close()
        browser.close()
        
    print("[PRESENTATION DRIVER] Presentation driver automation execution completed.")

if __name__ == "__main__":
    main()
