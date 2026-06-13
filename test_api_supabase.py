"""Integration test suite verifying Supabase integration for api.py."""

from __future__ import annotations

import os
from pathlib import Path
from fastapi.testclient import TestClient

# 1. Patch asset manager checks in niyanth BEFORE importing the app
import niyanth


def mock_validate_assets(image_paths: list[str]) -> bool:
    print("[MOCK-PATCH] Asset Manager bypassed - assuming valid real estate photos.")
    return True


niyanth.validate_assets = mock_validate_assets

# 2. Now import api.app and database engines
from api import app
from database import DatabaseEngine


def main() -> None:
    print("=" * 60)
    print("  Supabase Ingestion API Integration Test")
    print("=" * 60)

    client = TestClient(app)
    db_engine = DatabaseEngine()

    # Define dummy image path
    project_dir = Path(__file__).resolve().parent
    dummy_image = project_dir / "dummy_flat.jpg"

    if not dummy_image.is_file():
        print("[INFO] Creating temporary dummy_flat.jpg for test run.")
        dummy_image.write_bytes(b"Fake JPEG binary payload for API tests.")
        created_temp_img = True
    else:
        print(f"[INFO] Found dummy_flat.jpg ({dummy_image.stat().st_size:,} bytes).")
        created_temp_img = False

    try:
        # Step A: Mimic Employee Intake Form submittal (POST /api/generate-draft)
        print("\n[STEP A] Sending draft generation request to /api/generate-draft...")
        with open(dummy_image, "rb") as f:
            response = client.post(
                "/api/generate-draft",
                data={
                    "flat_details": "2BHK Semi-Furnished, Sector-4 Noida Extension",
                    "contact_number": "+91-9876543210",
                    "custom_instruction": "Highlight natural lighting and immediate occupancy.",
                    "target_profile": "test_verification_profile",
                },
                files={"images": ("dummy_flat.jpg", f, "image/jpeg")},
            )

        assert response.status_code == 200, f"Generate draft failed: {response.text}"
        payload = response.json()
        draft_id = payload.get("draft_id")
        image_paths = payload.get("image_paths")
        generated_captions = payload.get("generated_captions")

        print(f"[SUCCESS] Draft generated with ID: {draft_id}")
        assert draft_id, "Missing draft_id in response."
        assert image_paths, "Missing image_paths in response."
        assert generated_captions, "Missing generated_captions in response."

        # Verify initial database state is 'pending'
        listings = db_engine.list_listings()
        created_listing = next((l for l in listings if l["id"] == draft_id), None)
        assert created_listing, f"Listing {draft_id} not found in database."
        assert created_listing["status"] == "pending", (
            f"Expected listing status to be 'pending', got: {created_listing['status']}"
        )
        print("[PASS] Listing successfully initialized in database in 'pending' state.")

        # Step B: Mimic Admin Approval (POST /api/approve-draft)
        final_text = "✨ Luxurious 2BHK flat available for rent at Noida Extension! immediate shifting, contact +91-9876543210!"
        print("\n[STEP B] Sending approval request to /api/approve-draft...")
        approve_response = client.post(
            "/api/approve-draft",
            json={
                "draft_id": draft_id,
                "final_approved_text": final_text,
                "image_paths": image_paths,
                "target_profile": "test_verification_profile",
            },
        )

        assert approve_response.status_code == 200, f"Approve draft failed: {approve_response.text}"
        approve_payload = approve_response.json()
        assert approve_payload.get("status") == "success", approve_payload

        # Step C: Verify the final database state transitions to 'approved'
        print("\n[STEP C] Verifying state transition in local database cluster...")
        listings = db_engine.list_listings()
        approved_listing = next((l for l in listings if l["id"] == draft_id), None)
        
        assert approved_listing, f"Listing {draft_id} not found in database after approval."
        assert approved_listing["status"] == "approved", (
            f"Expected final listing status to be 'approved', got: {approved_listing['status']}"
        )
        assert approved_listing["final_text"] == final_text, (
            f"Expected final_text to match: {final_text}, got: {approved_listing['final_text']}"
        )
        
        print(f"[SUCCESS] Final database state for listing {draft_id} verified as 'approved' with the correct caption.")
        print("=" * 60)
        print("All verification steps passed successfully! [SUCCESS]")
        print("=" * 60)

    finally:
        # Clean up temporary test image if created
        if created_temp_img and dummy_image.is_file():
            dummy_image.unlink()


if __name__ == "__main__":
    main()
