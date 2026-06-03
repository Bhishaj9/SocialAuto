"""Local JSON-backed database mock for AutoBVB.

This module intentionally avoids Firestore so the worker can be tested end to
end while Firebase billing is unavailable.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator

LISTINGS_FILE = Path(__file__).resolve().parent / "listings.json"
LISTINGS_LOCK_FILE = Path(__file__).resolve().parent / "listings.json.lock"
_LISTINGS_LOCK = threading.Lock()


@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
    LISTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=LISTINGS_FILE.parent,
            delete=False,
            suffix=".tmp",
        ) as temp_file:
            json.dump(listings, temp_file, indent=2, ensure_ascii=False)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        os.replace(temp_path, LISTINGS_FILE)
    except OSError:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def get_pending_listing() -> dict[str, Any] | None:
    """Return the first listing whose status is pending."""
    print("[database] Checking listings.json for pending listings...")
    with _LISTINGS_LOCK:
        with _exclusive_file_lock(LISTINGS_LOCK_FILE):
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
    with _LISTINGS_LOCK:
        with _exclusive_file_lock(LISTINGS_LOCK_FILE):
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
