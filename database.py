"""Local Supabase-backed database engine for AutoBVB.

This module replaces the legacy JSON-backed database with real-time operations
pointing to a local Supabase PostgreSQL instance.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client, Client


class DatabaseEngine:
    """Database Engine using Supabase client to perform CRUD operations on 'listings'."""

    def __init__(self, url: str | None = None, key: str | None = None) -> None:
        # Load environment variables from .env first
        load_dotenv()
        # Explicitly load .env.local if present to ensure local developer keys take precedence
        project_dir = Path(__file__).resolve().parent
        env_local_path = project_dir / ".env.local"
        if env_local_path.is_file():
            load_dotenv(dotenv_path=env_local_path, override=True)

        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not self.url or not self.key:
            raise ValueError(
                "Supabase URL and Key (Service Role or Anon) must be set via environment or arguments."
            )

        self.client: Client = create_client(self.url, self.key)

    def create_listing(
        self, profile_id: str, original_assets: list[str], listing_id: str | None = None
    ) -> dict[str, Any]:
        """Insert a fresh listing row into the database with a status of 'pending'."""
        payload: dict[str, Any] = {
            "profile_id": profile_id,
            "original_assets": original_assets,
            "status": "pending",
        }
        if listing_id:
            payload["id"] = listing_id

        response = self.client.table("listings").insert(payload).execute()
        if not response.data:
            raise RuntimeError("Failed to insert listing into PostgreSQL database.")
        return response.data[0]

    def update_draft_captions(self, listing_id: str, generated_captions: str) -> dict[str, Any]:
        """Update a listing row with generated captions."""
        # Cleanly parse generated_captions to list of variations for storage if it is a string
        variations = [v.strip() for v in generated_captions.split("=== VARIATION OVER ===") if v.strip()]

        response = self.client.table("listings").update({
            "generated_captions": {
                "raw_text": generated_captions,
                "variations": variations,
            }
        }).eq("id", listing_id).execute()

        if not response.data:
            raise RuntimeError(f"Listing {listing_id} not found to update captions.")
        return response.data[0]

    def approve_listing(self, listing_id: str, final_approved_text: str) -> dict[str, Any]:
        """Lock the copy text and transition the row state to approved."""
        response = self.client.table("listings").update({
            "final_approved_text": final_approved_text,
            "status": "approved",
        }).eq("id", listing_id).execute()

        if not response.data:
            raise RuntimeError(f"Listing {listing_id} not found to approve.")
        return response.data[0]

    def list_listings(self) -> list[dict[str, Any]]:
        """Fetch all listings and map them to legacy dictionary structure for UI compatibility."""
        response = self.client.table("listings").select("*").order("created_at", desc=True).execute()
        mapped = []
        for row in response.data:
            mapped.append({
                "id": str(row["id"]),
                "status": row["status"],
                "final_text": row.get("final_approved_text"),
                "image_paths": row.get("original_assets", []),
                "target_profile": row.get("profile_id"),
                "generated_captions": row.get("generated_captions"),
            })
        return mapped

    def claim_job_atomically(self, worker_name: str) -> dict[str, Any] | None:
        """Atomically find and claim the first 'approved' listing using RPC."""
        try:
            response = self.client.rpc(
                "claim_next_approved_listing",
                {"worker_id": worker_name}
            ).execute()
            if response.data:
                return response.data[0]
        except Exception as exc:
            print(f"[database] claim_job_atomically failed: {exc}")
        return None

    def mark_completed(self, listing_id: str) -> dict[str, Any]:
        """Transition the listing row state to completed."""
        response = self.client.table("listings").update({
            "status": "completed",
        }).eq("id", listing_id).execute()
        if not response.data:
            raise RuntimeError(f"Listing {listing_id} not found to mark completed.")
        return response.data[0]

    def mark_failed(self, listing_id: str, error_message: str) -> dict[str, Any]:
        """Transition the listing row state to failed and set the error message."""
        response = self.client.table("listings").update({
            "status": "failed",
            "error_message": error_message,
        }).eq("id", listing_id).execute()
        if not response.data:
            raise RuntimeError(f"Listing {listing_id} not found to mark failed.")
        return response.data[0]


# ── Legacy Compatibility Layer ────────────────────────────────────────────────

def get_approved_listing() -> dict[str, Any] | None:
    """Return the first listing whose status is approved."""
    try:
        engine = DatabaseEngine()
        response = engine.client.table("listings").select("*").eq("status", "approved").order("created_at", desc=True).limit(1).execute()
        if response.data:
            row = response.data[0]
            return {
                "id": str(row["id"]),
                "status": row["status"],
                "final_text": row.get("final_approved_text"),
                "image_paths": row.get("original_assets", []),
                "target_profile": row.get("profile_id"),
                "generated_captions": row.get("generated_captions"),
            }
    except Exception as exc:
        print(f"[database] get_approved_listing failed: {exc}")
    return None


def update_listing_status(listing_id: str, new_status: str) -> None:
    """Update a listing status in the database."""
    if not listing_id:
        raise ValueError("listing_id is required.")
    if not new_status:
        raise ValueError("new_status is required.")

    engine = DatabaseEngine()
    response = engine.client.table("listings").update({"status": new_status}).eq("id", listing_id).execute()
    if not response.data:
        raise ValueError(f"Listing not found in Supabase: {listing_id}")


class FirestoreManager:
    """Compatibility wrapper exposing the same calls as the live Firestore manager."""

    def get_approved_listing(self) -> dict[str, Any] | None:
        return get_approved_listing()

    def update_listing_status(self, document_id: str, new_status: str) -> None:
        update_listing_status(document_id, new_status)
