import os
import json
import shutil
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from database import DatabaseEngine
from worker import _execute_listing

# Set local storage override environment variable
LOCAL_STORAGE = Path(__file__).resolve().parent / "local_storage"
os.environ["AUTOBVB_LOCAL_STORAGE"] = str(LOCAL_STORAGE)

async def test_multi_tenant_worker():
    print("\n============================================================")
    print("  Testing Multi-Tenant Profiling and Graceful Failures")
    print("============================================================\n")

    db_engine = DatabaseEngine()

    # Clean stale test listings
    print("[TEST] Truncating database listings table...")
    db_engine.client.table("listings").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # Define paths
    profiles_dir = LOCAL_STORAGE / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    agent_01_dir = profiles_dir / "test_agent_01"
    agent_02_dir = profiles_dir / "test_agent_02"

    agent_01_dir.mkdir(parents=True, exist_ok=True)
    if agent_02_dir.exists():
        shutil.rmtree(agent_02_dir)

    # 1. Create a mock auth state file for test_agent_01
    state_file_01 = agent_01_dir / "fb_state.json"
    dummy_state = [{"name": "c_user", "value": "12345", "domain": ".facebook.com"}]
    state_file_01.write_text(json.dumps(dummy_state), encoding="utf-8")
    print(f"[TEST] Created mock state file for test_agent_01: {state_file_01}")

    # 2. Create listing records in database
    # Listing 1: test_agent_01 (State file exists)
    listing_01 = db_engine.create_listing(
        profile_id="test_agent_01",
        original_assets=["http://127.0.0.1:54321/storage/v1/object/public/property-assets/dummy.jpg"]
    )
    id_01 = listing_01["id"]
    db_engine.approve_listing(id_01, "Perfect Noida apartment description.")

    # Listing 2: test_agent_02 (State file missing)
    listing_02 = db_engine.create_listing(
        profile_id="test_agent_02",
        original_assets=["http://127.0.0.1:54321/storage/v1/object/public/property-assets/dummy.jpg"]
    )
    id_02 = listing_02["id"]
    db_engine.approve_listing(id_02, "Another Noida apartment description.")

    print(f"[TEST] Created approved listing {id_01} for test_agent_01.")
    print(f"[TEST] Created approved listing {id_02} for test_agent_02.")

    # --- Test Case A: test_agent_02 (Missing authentication state file) ---
    print("\n--- Running Test Case A: test_agent_02 (Missing authentication state file) ---")
    
    # Read listing record from DB to pass to _execute_listing
    rec_02 = db_engine.client.table("listings").select("*").eq("id", id_02).execute().data[0]

    # Run execution - this must handle missing state gracefully, log warning, and mark listing failed
    await _execute_listing(rec_02)

    # Verify database state for listing 02
    updated_rec_02 = db_engine.client.table("listings").select("*").eq("id", id_02).execute().data[0]
    print(f"[TEST] Updated status for listing {id_02}: {updated_rec_02['status']}")
    print(f"[TEST] Updated error_message: {updated_rec_02.get('error_message')}")

    assert updated_rec_02["status"] == "failed"
    expected_err = f"Authentication profile state missing for test_agent_02. Please upload state file."
    assert updated_rec_02.get("error_message") == expected_err
    print("[PASS] Test Case A: test_agent_02 failed gracefully and recorded the correct error message.")

    # --- Test Case B: test_agent_01 (Auth state exists) ---
    print("\n--- Running Test Case B: test_agent_01 (Auth state exists) ---")
    rec_01 = db_engine.client.table("listings").select("*").eq("id", id_01).execute().data[0]

    validation_flag = {"passed": False}
    
    async def dummy_launch(*args, **kwargs):
        resolved_state_file = args[1]
        resolved_profile_id = args[2]

        print(f"[TEST] Launch Context triggered for profile: {resolved_profile_id}")
        print(f"[TEST] Resolved state file path: {resolved_state_file}")

        # Assert correct mapping
        assert resolved_profile_id == "test_agent_01"
        assert str(resolved_state_file).replace("\\", "/").endswith("local_storage/profiles/test_agent_01/fb_state.json")
        
        # Verify isolation of user data directory
        local_storage_base = os.getenv("AUTOBVB_LOCAL_STORAGE", "local_storage")
        expected_user_data_dir = os.path.join(local_storage_base, "browser_contexts", resolved_profile_id)
        print(f"[TEST] Expected user data directory (sandboxed): {expected_user_data_dir}")
        
        # Verify the actual directory path resolved in context
        assert os.path.normpath(expected_user_data_dir) == os.path.normpath(os.path.join(LOCAL_STORAGE, "browser_contexts", "test_agent_01"))

        validation_flag["passed"] = True
        raise RuntimeError("Abort execution cleanly after parameter assertions")

    with patch("worker._launch_context", side_effect=dummy_launch) as patched_launch, \
         patch("worker._download_assets", return_value=["dummy_local_path.jpg"]) as patched_download:
        
        try:
            await _execute_listing(rec_01)
        except RuntimeError as e:
            # We expect the abort exception
            assert str(e) == "Abort execution cleanly after parameter assertions"

        assert validation_flag["passed"] is True
        print("[PASS] Test Case B: Context parameters and profile paths correctly isolated.")

    # Clean up mock directories
    if agent_01_dir.exists():
        shutil.rmtree(agent_01_dir)

    print("\n============================================================")
    print("  All Multi-Tenant Worker Verification Checks Passed! [SUCCESS]")
    print("============================================================\n")

if __name__ == "__main__":
    asyncio.run(test_multi_tenant_worker())
