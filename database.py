"""Local JSON-backed database mock for AutoBVB.

This module intentionally avoids Firestore so the worker can be tested end to
end while Firebase billing is unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LISTINGS_FILE = Path(__file__).resolve().parent / "listings.json"


def _load_listings() -> list[dict[str, Any]]:
    if not LISTINGS_FILE.exists():
        print(f"[database] {LISTINGS_FILE} not found. Creating an empty listing store.")
        _save_listings([])
        return []

    with LISTINGS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"{LISTINGS_FILE} must contain a JSON array.")

    return data


def _save_listings(listings: list[dict[str, Any]]) -> None:
    with LISTINGS_FILE.open("w", encoding="utf-8") as file:
        json.dump(listings, file, indent=2, ensure_ascii=False)
        file.write("\n")


def get_pending_listing() -> dict[str, Any] | None:
    """Return the first listing whose status is pending."""
    print("[database] Checking listings.json for pending listings...")
    listings = _load_listings()

    for listing in listings:
        if listing.get("status") == "pending":
            listing_id = listing.get("id", "<missing id>")
            print(f"[database] Found pending listing: {listing_id}")
            return dict(listing)

    print("[database] No pending listing found.")
    return None


def update_listing_status(listing_id: str, new_status: str) -> None:
    """Update a listing status in listings.json."""
    if not listing_id:
        raise ValueError("listing_id is required.")

    if not new_status:
        raise ValueError("new_status is required.")

    print(f"[database] Updating listing {listing_id} status to '{new_status}'...")
    listings = _load_listings()

    for listing in listings:
        if listing.get("id") == listing_id:
            listing["status"] = new_status
            _save_listings(listings)
            print(f"[database] Listing {listing_id} status updated to '{new_status}'.")
            return

    raise ValueError(f"Listing not found in {LISTINGS_FILE}: {listing_id}")


class FirestoreManager:
    """Compatibility wrapper exposing the same calls as the live Firestore manager."""

    def get_pending_listing(self) -> dict[str, Any] | None:
        return get_pending_listing()

    def update_listing_status(self, document_id: str, new_status: str) -> None:
        update_listing_status(document_id, new_status)
