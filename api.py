"""FastAPI bridge for submitting AutoBVB property listings."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile

ROOT_DIR = Path(__file__).resolve().parent
LISTINGS_FILE = ROOT_DIR / "listings.json"
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", "/app/local_storage"))

app = FastAPI(title="AutoBVB Listings Bridge", version="1.0.0")
_listings_lock = threading.Lock()


def _load_listings() -> list[dict[str, Any]]:
    if not LISTINGS_FILE.exists():
        print(f"[api] {LISTINGS_FILE} not found. Initializing empty listing store.")
        return []

    try:
        with LISTINGS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Listings database is invalid JSON.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Unable to read listings database.") from exc

    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Listings database must contain a JSON array.")

    return data


def _save_listings(listings: list[dict[str, Any]]) -> None:
    LISTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

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
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Unable to write listings database.") from exc


def _safe_upload_name(upload: UploadFile, index: int) -> str:
    original_name = Path(upload.filename or f"image_{index}.jpg").name
    suffix = Path(original_name).suffix or ".jpg"
    stem = Path(original_name).stem or f"image_{index}"
    safe_stem = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in stem)
    return f"{index:02d}_{safe_stem}_{uuid.uuid4().hex}{suffix.lower()}"


async def _save_uploaded_images(listing_id: str, images: list[UploadFile]) -> list[str]:
    listing_dir = (LOCAL_STORAGE_DIR / "listings" / listing_id).resolve()
    saved_paths: list[str] = []

    try:
        listing_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Unable to create listing asset directory.") from exc

    for index, image in enumerate(images, start=1):
        destination = listing_dir / _safe_upload_name(image, index)
        try:
            image_bytes = await image.read()
            if not image_bytes:
                raise HTTPException(status_code=400, detail=f"Uploaded image {index} is empty.")

            destination.write_bytes(image_bytes)
            saved_paths.append(str(destination))
            print(f"[api] Saved image {index} for listing {listing_id}: {destination}")
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded image {index}.") from exc
        finally:
            await image.close()

    return saved_paths


@app.post("/api/listings")
async def create_listing(
    background_tasks: BackgroundTasks,
    flat_details: str = Form(...),
    contact_number: str = Form(...),
    custom_instruction: str | None = Form(None),
    images: list[UploadFile] = File(...),
) -> dict[str, Any]:
    del background_tasks

    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    listing_id = uuid.uuid4().hex
    print(f"[api] Received listing submission {listing_id} with {len(images)} image(s).")

    saved_image_paths = await _save_uploaded_images(listing_id, images)
    listing: dict[str, Any] = {
        "id": listing_id,
        "status": "pending",
        "flat_details": flat_details,
        "contact_number": contact_number,
        "metadata": {
            "image_paths": saved_image_paths,
            "custom_instruction": custom_instruction,
        },
    }

    with _listings_lock:
        listings = _load_listings()
        listings.append(listing)
        _save_listings(listings)

    print(f"[api] Listing {listing_id} queued in {LISTINGS_FILE}. Worker can process it now.")
    return {"id": listing_id, "status": "pending", "image_paths": saved_image_paths}


@app.get("/api/listings")
def list_listings() -> dict[str, list[dict[str, Any]]]:
    with _listings_lock:
        listings = _load_listings()

    print(f"[api] Returning {len(listings)} listing status record(s).")
    return {"listings": listings}
