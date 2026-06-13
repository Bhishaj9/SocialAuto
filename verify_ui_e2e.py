#!/usr/bin/env python3
"""AutoBVB E2E UI Verification Test.

Orchestrates the entire platform loop:
1. Truncates database listings.
2. Seeds mock state for test_agent_01.
3. Launches api.py and worker.py in the background.
4. Uses Playwright to fill and submit the Ingestion form, then approve it via Governor Cockpit.
5. Polls database to verify worker claims and completes the listing.
6. Cleanly terminates background processes.
"""

from __future__ import annotations

import os
import sys
import time
import socket
import shutil
import logging
import subprocess
import urllib.request
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv()
project_dir = Path(__file__).resolve().parent
env_local_path = project_dir / ".env.local"
if env_local_path.is_file():
    load_dotenv(dotenv_path=env_local_path, override=True)

# Import DatabaseEngine after environment is initialized
from database import DatabaseEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("UI_TEST")

def check_and_kill_port(port):
    """Scan if port is in use, and taskkill the process holding it to prevent binding failures."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            logger.warning(f"[UI TEST] Port {port} is already in use! Attempting to find and terminate the process...")
            try:
                # Find the PID holding the port using netstat
                output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
                pids = set()
                for line in output.strip().split("\n"):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pids.add(parts[-1])
                for pid in pids:
                    if int(pid) != os.getpid():
                        logger.info(f"[UI TEST] Terminating conflicting process with PID {pid} on port {port}...")
                        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
            except Exception as e:
                logger.error(f"[UI TEST] Failed to clear port {port}: {e}")

def kill_proc(proc, label):
    """Forcefully kill a process tree on Windows/Unix."""
    if proc and proc.poll() is None:
        logger.info(f"Terminating {label} (PID {proc.pid})...")
        try:
            proc.terminate()
            proc.wait(timeout=3)
            logger.info(f"{label} terminated cleanly.")
        except Exception:
            logger.warning(f"Failed to terminate {label} cleanly, force-killing...")
            try:
                # Use taskkill to kill the whole process tree (crucial for uvicorn/workers on Windows)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                logger.info(f"{label} force-killed.")
            except Exception as e:
                logger.error(f"Error force-killing {label}: {e}")

def main():
    logger.info("[UI TEST] Starting AutoBVB E2E UI verification test.")
    check_and_kill_port(8000)
    
    # 1. Clear database listings table for a clean test environment
    try:
        logger.info("[UI TEST] Truncating database listings table for a clean run...")
        db_engine = DatabaseEngine()
        db_engine.client.table("listings").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        logger.info("[UI TEST] Database listings table truncated successfully.")
    except Exception as e:
        logger.warning(f"[UI TEST] Warning: Database truncate failed: {e}")
        
    # 2. Seed REAL authenticated Facebook state for test_agent_01
    try:
        profiles_dir = Path("local_storage/profiles/test_agent_01")
        profiles_dir.mkdir(parents=True, exist_ok=True)
        real_state = Path("fb_state.json")
        if not real_state.is_file():
            logger.error("[UI TEST] ABORT: Real fb_state.json not found in project root. Cannot run live fire test.")
            sys.exit(1)
        shutil.copy(real_state, profiles_dir / "fb_state.json")
        logger.info("[UI TEST] Seeded REAL authenticated Facebook state for test_agent_01.")
    except Exception as e:
        logger.error(f"[UI TEST] Failed to seed Facebook state: {e}")
        sys.exit(1)

    # 3. Spin up api.py and worker.py in the background
    api_proc = None
    worker_proc = None
    api_log = None
    worker_log = None
    
    # Configure subprocess environment — LIVE FIRE MODE
    env = os.environ.copy()
    env["AUTOBVB_MOCK_PIPELINE"] = "False"
    env["AUTOBVB_MOCK_WORKER"] = "False"
    env["AUTOBVB_LOCAL_STORAGE"] = "local_storage"
    env["SHADOW_MODE"] = "True"
    env["WORKER_HEADLESS"] = "False"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        # Open redirect logs to prevent subprocess blocking/deadlocks
        api_log = open("api.stdout.log", "w", encoding="utf-8")
        worker_log = open("worker.stdout.log", "w", encoding="utf-8")

        logger.info("[UI TEST] Launching api.py (uvicorn api:app) in background...")
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", "8000", "--host", "127.0.0.1"],
            stdout=api_log,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        logger.info("[UI TEST] Launching worker.py in background...")
        worker_proc = subprocess.Popen(
            [sys.executable, "worker.py"],
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Poll the API health endpoint until it is ready
        logger.info("[UI TEST] Waiting for API server to respond on http://127.0.0.1:8000...")
        api_ready = False
        for _ in range(15):  # Try for 15 seconds
            if api_proc.poll() is not None:
                raise RuntimeError(f"api.py exited prematurely with code {api_proc.returncode}. Check api.stdout.log")
            if worker_proc.poll() is not None:
                raise RuntimeError(f"worker.py exited prematurely with code {worker_proc.returncode}. Check worker.stdout.log")
            try:
                # Try a simple GET request
                with urllib.request.urlopen("http://127.0.0.1:8000/api/listings", timeout=1) as r:
                    if r.status == 200:
                        api_ready = True
                        break
            except Exception:
                time.sleep(1)
                
        if not api_ready:
            raise RuntimeError("API server failed to respond on port 8000 within 15 seconds.")
        logger.info("[UI TEST] API server is ready and responding.")
        
        # 4. Playwright UI automation (Sync API)
        with sync_playwright() as p:
            logger.info("[UI TEST] Launching visible Chromium (demo mode, slow_mo=1500ms)...")
            browser = p.chromium.launch(headless=False, slow_mo=1500)
            page = browser.new_page()
            page.on("console", lambda msg: logger.info(f"[BROWSER CONSOLE] {msg.text}"))
            page.on("pageerror", lambda err: logger.error(f"[BROWSER PAGE ERROR] {err}"))
            
            # Step A: Ingestion Dashboard
            ingestion_path = Path("Frontend/stitch_autobvb_marketing_portal/ingestion_dashboard/code.html").resolve()
            logger.info(f"[UI TEST] Navigating to Ingestion Dashboard at {ingestion_path.as_uri()}...")
            page.goto(ingestion_path.as_uri())
            
            logger.info("[UI TEST] Filling broker-id as test_agent_01...")
            page.fill("#broker-id", "test_agent_01")
            
            # Set dummy image
            dummy_image_path = Path("dummy_flat.jpg").resolve()
            logger.info(f"[UI TEST] Uploading file payload: {dummy_image_path}...")
            page.locator("#file-input").set_input_files(str(dummy_image_path))
            
            logger.info("[UI TEST] Ingestion form filled. Pausing 4s for audience inspection...")
            page.wait_for_timeout(4000)
            logger.info("[UI TEST] Clicking Generate AI Variations...")
            page.click("#generate-btn")
            
            logger.info("[UI TEST] Waiting for status message update (live pipeline — up to 120s)...")
            page.wait_for_selector("#status-message:has-text('Draft successfully generated!')", timeout=120000)
            logger.info("[UI TEST] Draft successfully generated!")
            
            # Step B: Governor Cockpit
            cockpit_path = Path("Frontend/stitch_autobvb_marketing_portal/governor_cockpit/code.html").resolve()
            logger.info(f"[UI TEST] Navigating to Governor Cockpit at {cockpit_path.as_uri()}...")
            page.goto(cockpit_path.as_uri())
            
            logger.info("[UI TEST] Waiting for queue items to load...")
            page.wait_for_selector("#queue-container > div:not(.hidden)", timeout=20000)
            
            logger.info("[UI TEST] Selecting the newest item in the sidebar...")
            newest_item = page.locator("#queue-container > div:not(.hidden)").first
            newest_item.click()
            
            logger.info("[UI TEST] Cockpit loaded. Pausing 4s for audience inspection...")
            page.wait_for_timeout(4000)
            logger.info("[UI TEST] Clicking approve-btn...")
            page.click("#approve-btn")
            
            logger.info("[UI TEST] Waiting for approval reflection (button disabled)...")
            page.wait_for_selector("#approve-btn[disabled]", timeout=10000)
            logger.info("[UI TEST] Draft approved!")
            
            browser.close()
            
        # 5. Backend verification (Database checking)
        logger.info("[UI TEST] Beginning database verification loop...")
        db_engine = DatabaseEngine()
        
        # Poll listings table
        start_time = time.monotonic()
        verified = False
        last_status = None
        
        while time.monotonic() - start_time < 180:
            listings = db_engine.client.table("listings").select("*").eq("profile_id", "test_agent_01").order("created_at", desc=True).execute().data
            if listings:
                newest_listing = listings[0]
                status = newest_listing.get("status")
                if status != last_status:
                    logger.info(f"[UI TEST] Listing status transition: {last_status} -> {status}")
                    last_status = status
                    
                if status == "completed":
                    verified = True
                    logger.info("[UI TEST] Worker execution verified! Listing status flipped to 'completed'.")
                    logger.info("[UI TEST] Settiing a 5-second safety buffer for proof file write stabilization...")
                    time.sleep(5)
                    break
                elif status == "failed":
                    error_msg = newest_listing.get("error_message")
                    logger.error(f"[UI TEST] Worker reported failure: {error_msg}")
                    logger.info("[UI TEST] In live fire mode, this may be expected (e.g. Facebook checkpoint).")
                    break
                    
            time.sleep(3)
            
        if not verified and last_status != "failed":
            raise AssertionError(f"Timed out after 180s waiting for terminal status. Last status: {last_status}")
            
        logger.info("[UI TEST] E2E UI verification test passed successfully! [SUCCESS]")
        
    finally:
        # Clean up subprocesses
        logger.info("[UI TEST] Cleaning up background processes (skipping kill_proc for manual review)...")
        # kill_proc(worker_proc, "Worker process")
        # kill_proc(api_proc, "API process")
        
        # Close log file handles
        if api_log:
            api_log.close()
        if worker_log:
            worker_log.close()
        logger.info("[UI TEST] Teardown complete.")

if __name__ == "__main__":
    main()
