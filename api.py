"""FastAPI bridge for AutoBVB human-in-the-loop listing drafts."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from database import DatabaseEngine
from storage import StorageEngine
from niyanth import run_governed_pipeline

ROOT_DIR = Path(__file__).resolve().parent
LOCAL_STORAGE_DIR = Path(os.getenv("AUTOBVB_LOCAL_STORAGE", "/app/local_storage"))

app = FastAPI(title="AutoBVB Listings Bridge", version="1.0.0")

# Initialize Engine Singletons
db_engine = DatabaseEngine()
storage_engine = StorageEngine()


class ApproveDraftRequest(BaseModel):
    draft_id: str = Field(..., min_length=1)
    final_approved_text: str = Field(..., min_length=1)
    image_paths: list[str] = Field(..., min_length=1)
    target_profile: str = Field(..., min_length=1)


def _safe_upload_name(upload: UploadFile, index: int) -> str:
    original_name = Path(upload.filename or f"image_{index}.jpg").name
    suffix = Path(original_name).suffix or ".jpg"
    stem = Path(original_name).stem or f"image_{index}"
    safe_stem = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in stem)
    return f"{index:02d}_{safe_stem}_{uuid.uuid4().hex}{suffix.lower()}"


def _validate_profile_id(profile_id: str) -> str:
    normalized = profile_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="profile_id is required.")

    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(char not in allowed_chars for char in normalized) or normalized in {".", ".."}:
        raise HTTPException(status_code=400, detail="profile_id contains unsafe characters.")

    return normalized


def _profile_dir(profile_id: str) -> Path:
    safe_profile_id = _validate_profile_id(profile_id)
    profiles_root = (LOCAL_STORAGE_DIR / "profiles").resolve()
    profile_path = (profiles_root / safe_profile_id).resolve()
    if profiles_root not in profile_path.parents:
        raise HTTPException(status_code=400, detail="profile_id resolved outside profile storage.")

    return profile_path


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
    target_profile: str = Form("default_profile"),
    images: list[UploadFile] = File(...),
) -> dict[str, Any]:
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    safe_target_profile = _validate_profile_id(target_profile)
    draft_id = str(uuid.uuid4())
    print(
        f"[api] Received draft request {draft_id} for profile {safe_target_profile} "
        f"with {len(images)} image(s)."
    )

    # 1. Save local image files first to read their binaries and pass to Governor Agent
    saved_image_paths = await _save_uploaded_images(draft_id, images)

    # 2. Stream local file binaries directly to the Supabase property-assets bucket
    public_urls: list[str] = []
    for local_path in saved_image_paths:
        filename = Path(local_path).name
        remote_path = f"drafts/{draft_id}/{filename}"
        public_url = storage_engine.upload_file(local_path, remote_path)
        if not public_url:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload property asset {filename} to Supabase storage."
            )
        public_urls.append(public_url)

    # 3. Insert listing record into local database cluster in 'pending' state
    try:
        db_engine.create_listing(
            profile_id=safe_target_profile,
            original_assets=public_urls,
            listing_id=draft_id
        )
    except Exception as exc:
        print(f"[api] Failed to create database record: {exc}")
        raise HTTPException(status_code=500, detail="Failed to initialize listing in database.") from exc

    # 4. Generate the 3 preview variations out-of-band using the Governor Agent
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

    # 5. Call database update draft captions before returning
    try:
        db_engine.update_draft_captions(draft_id, generated_captions)
    except Exception as exc:
        print(f"[api] Failed to update draft captions: {exc}")
        raise HTTPException(status_code=500, detail="Failed to save generated captions.") from exc

    print(f"[api] Draft {draft_id} generated successfully for human review.")
    return {
        "draft_id": draft_id,
        "target_profile": safe_target_profile,
        "image_paths": saved_image_paths,
        "generated_captions": generated_captions,
    }


@app.post("/api/approve-draft")
def approve_draft(request: ApproveDraftRequest) -> dict[str, str]:
    print(f"[api] Approval received for draft {request.draft_id}.")

    try:
        db_engine.approve_listing(
            listing_id=request.draft_id,
            final_approved_text=request.final_approved_text
        )
    except Exception as exc:
        print(f"[api] Failed to approve listing: {exc}")
        raise HTTPException(status_code=500, detail=f"Database error during approval: {exc}") from exc

    print(f"[api] Draft {request.draft_id} approved and marked visible for worker loops.")
    return {"status": "success", "message": "Draft approved and queued for posting"}


@app.get("/api/accounts/download-capture")
def download_capture_script() -> FileResponse:
    capture_script = ROOT_DIR / "session_capture.py"
    if not capture_script.is_file():
        print(f"[api] session_capture.py download failed: missing at {capture_script}.")
        raise HTTPException(status_code=404, detail="session_capture.py was not found.")

    print(f"[api] Serving account capture script: {capture_script}.")
    return FileResponse(
        path=capture_script,
        media_type="text/x-python",
        filename="session_capture.py",
    )


@app.post("/api/accounts/upload-state")
async def upload_account_state(
    profile_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    safe_profile_id = _validate_profile_id(profile_id)
    profile_path = _profile_dir(safe_profile_id)
    state_path = profile_path / "fb_state.json"

    print(f"[api] Received state upload for profile {safe_profile_id}.")

    try:
        raw_state = await file.read()
        state_text = raw_state.decode("utf-8")
        parsed_state = json.loads(state_text)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Uploaded state file must be UTF-8 JSON.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Uploaded state file is not valid JSON.") from exc
    finally:
        await file.close()

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(parsed_state, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        print(
            f"[api] ERROR writing state file — "
            f"path={state_path!r} errno={exc.errno} strerror={exc.strerror!r}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Unable to write state file: {exc.strerror}",
        ) from exc

    print(f"[api] Account profile {safe_profile_id} initialized at {state_path}.")
    return {
        "status": "success",
        "message": "Account profile initialized",
        "profile_id": safe_profile_id,
    }


@app.get("/api/listings")
def list_listings() -> dict[str, list[dict[str, Any]]]:
    try:
        listings = db_engine.list_listings()
    except Exception as exc:
        print(f"[api] Failed to list listings: {exc}")
        raise HTTPException(status_code=500, detail="Failed to fetch listings.") from exc

    print(f"[api] Returning {len(listings)} listing status record(s).")
    return {"listings": listings}
