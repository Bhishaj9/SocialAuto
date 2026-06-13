"""Integration test suite to verify the Supabase database migration.

Simulates the end-to-end listing lifecycle: creation, caption generation,
approval, atomic claiming by worker, and final completion/failure transitions.
"""

from __future__ import annotations

import logging
import sys
from database import DatabaseEngine

# Configure basic log output for visibility during testing
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("TestDbMigration")


def run_integration_test():
    logger.info("=== Starting Supabase Relational DB Migration Verification ===")

    # 1. Initialize the Database Engine
    try:
        engine = DatabaseEngine()
    except Exception as exc:
        logger.error(f"Failed to initialize DatabaseEngine: {exc}")
        logger.error("Make sure your local Supabase instance is running and credentials are set in .env.local")
        sys.exit(1)
    # 1.5. Clean listings table for a reliable test run
    try:
        engine.client.table("listings").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        logger.info("[OK] Truncated listings table for clean test environment")
    except Exception as exc:
        logger.warning(f"Failed to truncate listings table: {exc}")

    # 2. Test create_listing
    logger.info("\n--- Step 1: Creating a new draft listing ---")
    mock_assets = [
        "d:/Projects/AutoBVB/local_storage/drafts/test_image_1.jpg",
        "d:/Projects/AutoBVB/local_storage/drafts/test_image_2.jpg"
    ]
    profile_id = "test_agent_01"
    
    listing = engine.create_listing(profile_id=profile_id, original_assets=mock_assets)
    listing_id = listing.get("id")
    assert listing_id is not None, "Created listing must return a valid UUID id."
    assert listing.get("profile_id") == profile_id
    assert listing.get("status") == "pending"
    assert listing.get("original_assets") == mock_assets
    logger.info(f"[OK] Listing created with ID: {listing_id}")

    # 3. Test update_draft_captions
    logger.info("\n--- Step 2: Injecting alternative caption variations ---")
    mock_captions_str = "Luxurious 3BHK flat in Noida Extension.\n=== VARIATION OVER ===\nPremium flat available for immediate rent in Noida Extension."
    updated = engine.update_draft_captions(listing_id=listing_id, generated_captions=mock_captions_str)
    assert updated.get("generated_captions") is not None, "Draft captions must not be None."
    assert updated.get("generated_captions", {}).get("raw_text") == mock_captions_str, "Draft captions mismatch."
    logger.info("[OK] Draft captions successfully updated.")

    # 4. Test approve_listing
    logger.info("\n--- Step 3: Approving the listing ---")
    final_text = "Final Approved Text: Call +91-9999999999 * Luxurious 3BHK Sector 1 Noida Extension."
    approved = engine.approve_listing(listing_id=listing_id, final_approved_text=final_text)
    assert approved.get("status") == "approved", "Status should transition to 'approved'."
    assert approved.get("final_approved_text") == final_text, "Approved final text mismatch."
    logger.info("[OK] Listing transitioned to status='approved'.")

    # 5. Test claim_job_atomically (RPC claim)
    logger.info("\n--- Step 4: Worker claiming approved job atomically ---")
    worker_name = "worker_bot_beta"
    claimed = engine.claim_job_atomically(worker_name=worker_name)
    
    assert claimed is not None, "Worker failed to claim the approved job."
    assert claimed.get("id") == listing_id, "Claimed job ID mismatch."
    assert claimed.get("status") == "processing", "Status should transition to 'processing'."
    assert claimed.get("claimed_by") == worker_name, "Claimed worker mismatch."
    logger.info(f"[OK] Job atomically claimed by worker '{worker_name}'.")

    # Verify that a second claim attempt returns None (since there are no more approved jobs)
    second_claim = engine.claim_job_atomically(worker_name="another_worker")
    assert second_claim is None, "Expected second claim to be None as queue is empty."
    logger.info("[OK] Verified queue locking: claim returned None when no approved jobs were available.")

    # 6. Test mark_completed
    logger.info("\n--- Step 5: Completing the job ---")
    completed = engine.mark_completed(listing_id=listing_id)
    assert completed.get("status") == "completed", "Status should be 'completed'."
    logger.info("[OK] Job marked completed successfully.")

    # 7. Test mark_failed (We'll create another temporary listing to test failure state transition)
    logger.info("\n--- Step 6: Testing failure transition with temporary draft ---")
    temp_listing = engine.create_listing(profile_id=profile_id, original_assets=[])
    temp_id = temp_listing.get("id")
    
    failed = engine.mark_failed(listing_id=temp_id, error_message="Simulated API connection failure.")
    assert failed.get("status") == "failed", "Status should transition to 'failed'."
    assert failed.get("error_message") == "Simulated API connection failure.", "Error message mismatch."
    logger.info("[OK] Job marked failed successfully.")

    logger.info("\n=== All migration verification checks passed successfully (100% Green) ===")


if __name__ == "__main__":
    run_integration_test()
