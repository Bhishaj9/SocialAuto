"""FastAPI bridge for AutoBVB human-in-the-loop listing drafts."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from niyanth import run_governed_pipeline

ROOT_DIR = Path(__file__).resolve().parent
LISTINGS_FILE = ROOT_DIR / "listings.json"
LISTINGS_LOCK_FILE = ROOT_DIR / "listings.json.lock"
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", "/app/local_storage"))

app = FastAPI(title="AutoBVB Listings Bridge", version="1.0.0")
_listings_lock = threading.Lock()


class ApproveDraftRequest(BaseModel):
    draft_id: str = Field(..., min_length=1)
    final_approved_text: str = Field(..., min_length=1)
    image_paths: list[str] = Field(..., min_length=1)


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
    except OSError as exc:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to write listings database.") from exc


def _safe_upload_name(upload: UploadFile, index: int) -> str:
    original_name = Path(upload.filename or f"image_{index}.jpg").name
    suffix = Path(original_name).suffix or ".jpg"
    stem = Path(original_name).stem or f"image_{index}"
    safe_stem = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in stem)
    return f"{index:02d}_{safe_stem}_{uuid.uuid4().hex}{suffix.lower()}"


async def _save_uploaded_images(draft_id: str, images: list[UploadFile]) -> list[str]:
    draft_dir = (LOCAL_STORAGE_DIR / "drafts" / draft_id).resolve()
    saved_paths: list[str] = []

    try:
        draft_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Unable to create draft asset directory.") from exc

    for index, image in enumerate(images, start=1):
        destination = draft_dir / _safe_upload_name(image, index)
        try:
            image_bytes = await image.read()
            if not image_bytes:
                raise HTTPException(status_code=400, detail=f"Uploaded image {index} is empty.")

            destination.write_bytes(image_bytes)
            saved_paths.append(str(destination))
            print(f"[api] Saved image {index} for draft {draft_id}: {destination}")
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded image {index}.") from exc
        finally:
            await image.close()

    return saved_paths


@app.post("/api/generate-draft")
async def generate_draft(
    flat_details: str = Form(...),
    contact_number: str = Form(...),
    custom_instruction: str | None = Form(None),
    images: list[UploadFile] = File(...),
) -> dict[str, Any]:
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    draft_id = uuid.uuid4().hex
    print(f"[api] Received draft request {draft_id} with {len(images)} image(s).")

    saved_image_paths = await _save_uploaded_images(draft_id, images)

    try:
        generated_captions = await asyncio.to_thread(
            run_governed_pipeline,
            saved_image_paths,
            flat_details,
            contact_number,
            custom_instruction,
        )
    except Exception as exc:
        print(f"[api] Draft pipeline failed for {draft_id}: {exc}")
        raise HTTPException(status_code=500, detail="Draft generation failed.") from exc

    print(f"[api] Draft {draft_id} generated successfully for human review.")
    return {
        "draft_id": draft_id,
        "image_paths": saved_image_paths,
        "generated_captions": generated_captions,
    }


@app.post("/api/approve-draft")
def approve_draft(request: ApproveDraftRequest) -> dict[str, str]:
    print(f"[api] Approval received for draft {request.draft_id}.")

    listing: dict[str, Any] = {
        "id": request.draft_id,
        "status": "pending",
        "final_text": request.final_approved_text,
        "image_paths": request.image_paths,
    }

    with _listings_lock:
        with _exclusive_file_lock(LISTINGS_LOCK_FILE):
            listings = _load_listings()
            listings.append(listing)
            _save_listings(listings)

    print(f"[api] Draft {request.draft_id} approved and queued in {LISTINGS_FILE}.")
    return {"status": "success", "message": "Draft approved and queued for posting"}


@app.get("/api/listings")
def list_listings() -> dict[str, list[dict[str, Any]]]:
    with _listings_lock:
        with _exclusive_file_lock(LISTINGS_LOCK_FILE):
            listings = _load_listings()

    print(f"[api] Returning {len(listings)} listing status record(s).")
    return {"listings": listings}
