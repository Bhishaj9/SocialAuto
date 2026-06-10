"""AutoBVB V4.0 local E2E workflow tester."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

API_BASE_URL = "http://localhost:8000"
ROOT_DIR = Path(__file__).resolve().parent
LISTINGS_FILE = ROOT_DIR / "listings.json"
DUMMY_IMAGE_FILE = ROOT_DIR / "dummy_flat.jpg"
DUMMY_STATE_FILE = ROOT_DIR / "dummy_fb_state.json"
TARGET_PROFILE = "test_agent_01"
POLL_SECONDS = 180
POLL_INTERVAL_SECONDS = 2


def _print_pass(message: str) -> None:
    print(f"[TEST] {message}... PASS")


def _print_step(message: str) -> None:
    print(f"[TEST] {message}...")


def _assert_response_ok(response: requests.Response, step_name: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(f"{step_name} returned non-JSON response: {response.text}") from exc

    if response.status_code >= 400:
        raise AssertionError(f"{step_name} failed with HTTP {response.status_code}: {payload}")

    return payload


def create_dummy_files() -> None:
    # Minimal valid JPEG bytes: SOI marker, tiny JFIF payload, EOI marker.
    DUMMY_IMAGE_FILE.write_bytes(
        b"\xff\xd8"
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
        b"\xff\xdb\x00C\x00" + bytes([8] * 64) +
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\x00"
        b"\xff\xd9"
    )

    real_state_file = ROOT_DIR / "local_storage" / "profiles" / TARGET_PROFILE / "fb_state.json"
    if real_state_file.is_file():
        print(f"[TEST] Found real session state at {real_state_file}. Syncing for E2E upload...")
        DUMMY_STATE_FILE.write_text(real_state_file.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dummy_cookies = [
            {
                "name": "c_user",
                "value": "dummy-user",
                "domain": ".facebook.com",
                "path": "/",
                "expires": int(time.time()) + 86400,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "xs",
                "value": "dummy-session",
                "domain": ".facebook.com",
                "path": "/",
                "expires": int(time.time()) + 86400,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            },
        ]
        DUMMY_STATE_FILE.write_text(json.dumps(dummy_cookies, indent=2), encoding="utf-8")


def upload_profile_state() -> None:
    _print_step("Step 1: Uploading Profile")
    with DUMMY_STATE_FILE.open("rb") as state_file:
        response = requests.post(
            f"{API_BASE_URL}/api/accounts/upload-state",
            data={"profile_id": TARGET_PROFILE},
            files={"file": ("fb_state.json", state_file, "application/json")},
            timeout=30,
        )

    payload = _assert_response_ok(response, "profile upload")
    assert payload.get("status") == "success", payload
    assert payload.get("profile_id") == TARGET_PROFILE, payload
    _print_pass("Step 1: Uploading Profile")


def generate_draft() -> dict[str, Any]:
    _print_step("Step 2: Generating AI Draft")
    with DUMMY_IMAGE_FILE.open("rb") as image_file:
        response = requests.post(
            f"{API_BASE_URL}/api/generate-draft",
            data={
                "flat_details": "3BHK Semi-Furnished, Sector 1 Noida Extension",
                "contact_number": "+91-9999999999",
                "custom_instruction": "Keep the caption concise and family-friendly.",
                "target_profile": TARGET_PROFILE,
            },
            files={"images": ("dummy_flat.jpg", image_file, "image/jpeg")},
            timeout=180,
        )

    payload = _assert_response_ok(response, "draft generation")
    assert payload.get("draft_id"), payload
    assert payload.get("image_paths"), payload
    assert payload.get("generated_captions"), payload
    print(f"[TEST] Draft ID: {payload['draft_id']}")
    _print_pass("Step 2: Generating AI Draft")
    return payload


def _choose_caption(generated_captions: Any) -> str:
    if isinstance(generated_captions, list):
        for caption in generated_captions:
            if isinstance(caption, str) and caption.strip():
                return caption.strip()

    if isinstance(generated_captions, str):
        options = [
            option.strip()
            for option in generated_captions.split("=== VARIATION OVER ===")
            if option.strip()
        ]
        if options:
            return options[0]

    raise AssertionError(f"No usable generated caption found: {generated_captions!r}")


def approve_draft(draft_payload: dict[str, Any]) -> None:
    _print_step("Step 3: Approving Draft")
    final_text = _choose_caption(draft_payload["generated_captions"])
    response = requests.post(
        f"{API_BASE_URL}/api/approve-draft",
        json={
            "draft_id": draft_payload["draft_id"],
            "final_approved_text": final_text,
            "image_paths": draft_payload["image_paths"],
            "target_profile": TARGET_PROFILE,
        },
        timeout=30,
    )

    payload = _assert_response_ok(response, "draft approval")
    assert payload.get("status") == "success", payload
    _print_pass("Step 3: Approving Draft")


def _read_listing_status(draft_id: str) -> str | None:
    if not LISTINGS_FILE.exists():
        return None

    with LISTINGS_FILE.open("r", encoding="utf-8") as listings_file:
        listings = json.load(listings_file)

    if not isinstance(listings, list):
        raise AssertionError("listings.json must contain a JSON array.")

    for listing in listings:
        if isinstance(listing, dict) and listing.get("id") == draft_id:
            status = listing.get("status")
            return str(status) if status is not None else None

    return None


def poll_worker_completion(draft_id: str) -> None:
    _print_step("Step 4: Polling Worker Status")
    deadline = time.monotonic() + POLL_SECONDS
    status_history: list[str] = []

    while time.monotonic() < deadline:
        status = _read_listing_status(draft_id)
        if status and (not status_history or status_history[-1] != status):
            status_history.append(status)
            print(f"[TEST] Listing {draft_id} status -> {status}")

        if status in {"completed", "shadow_success"}:
            _print_pass("Step 4: Polling Worker Status")
            print(f"[TEST] Status history: {' -> '.join(status_history)}")
            return

        if status in {"shadow_failed", "failed"}:
            raise AssertionError(f"Worker failed listing {draft_id}. Status history: {status_history}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise AssertionError(
        f"Timed out waiting for completed/shadow_success. Status history: {status_history}"
    )


def main() -> None:
    print("[TEST] AutoBVB V4.0 E2E tester starting.")
    create_dummy_files()
    _print_pass("Step 0: Creating Dummy Files")
    upload_profile_state()
    draft_payload = generate_draft()
    approve_draft(draft_payload)
    poll_worker_completion(draft_payload["draft_id"])
    print("[TEST] AutoBVB V4.0 E2E flow completed successfully.")


if __name__ == "__main__":
    main()
