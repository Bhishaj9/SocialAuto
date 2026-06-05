"""AutoBVB local orchestration test — real asset paths, fully decoupled API."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

API_BASE = "http://localhost:8000"
PROFILE_ID = "test_agent_01"
STATE_FILE = Path("D:/Projects/AutoBVB/local_storage/profiles/test_agent_01/fb_state.json")
FLAT_IMAGES = [
    Path("D:/Projects/AutoBVB/local_storage/flats01/flat1.jpg"),
    Path("D:/Projects/AutoBVB/local_storage/flats01/flat2.jpg"),
]
LISTINGS_FILE = Path("D:/Projects/AutoBVB/listings.json")

POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2

CUSTOM_PROMPT = (
    "Write a premium rental post for a gorgeous, highly spacious 3BHK flat "
    "located in Sector 62 Noida Extension, featuring modular kitchens, "
    "wide ambient balconies, close proximity to the metro station, "
    "and available for immediate occupancy."
)


def _assert_ok(resp: requests.Response, label: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        raise AssertionError(f"{label}: non-JSON response ({resp.status_code})")

    if resp.status_code >= 400:
        raise AssertionError(f"{label}: HTTP {resp.status_code} — {body}")

    return body


# ── Phase 1 ──────────────────────────────────────────────────────────────────
def upload_profile_state() -> None:
    print("\n[Phase 1] Uploading employee session state …")

    if not STATE_FILE.is_file():
        raise FileNotFoundError(f"Session state not found: {STATE_FILE}")

    state_data: dict[str, Any] = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    print(f"  Loaded state file ({len(json.dumps(state_data))} bytes).")

    with STATE_FILE.open("rb") as fh:
        resp = requests.post(
            f"{API_BASE}/api/accounts/upload-state",
            data={"profile_id": PROFILE_ID},
            files={"file": (STATE_FILE.name, fh, "application/json")},
            timeout=30,
        )

    body = _assert_ok(resp, "upload-state")
    assert body.get("status") == "success", body
    print(f"  PASS — profile '{body.get('profile_id')}' initialised.")


# ── Phase 2 ──────────────────────────────────────────────────────────────────
def generate_draft() -> dict[str, Any]:
    print("\n[Phase 2] Generating copywriting draft …")

    for img_path in FLAT_IMAGES:
        if not img_path.is_file():
            raise FileNotFoundError(f"Image asset missing: {img_path}")

    files: list[tuple[str, tuple[str, Any, str]]] = []
    handles: list[Any] = []
    for img_path in FLAT_IMAGES:
        fh = img_path.open("rb")
        handles.append(fh)
        files.append(("images", (img_path.name, fh, "image/jpeg")))

    try:
        resp = requests.post(
            f"{API_BASE}/api/generate-draft",
            data={
                "flat_details": CUSTOM_PROMPT,
                "contact_number": "+91-9999999999",
                "custom_instruction": CUSTOM_PROMPT,
                "target_profile": PROFILE_ID,
            },
            files=files,
            timeout=300,
        )
    finally:
        for fh in handles:
            fh.close()

    body = _assert_ok(resp, "generate-draft")
    draft_id: str = body.get("draft_id", "")
    if not draft_id:
        raise AssertionError("generate-draft returned empty draft_id")

    print(f"  PASS — draft_id = {draft_id}")
    return body


# ── Phase 3 ──────────────────────────────────────────────────────────────────
def approve_draft(draft_payload: dict[str, Any]) -> str:
    print("\n[Phase 3] Approving draft for worker execution …")

    draft_id: str = draft_payload["draft_id"]
    generated = draft_payload.get("generated_captions", [])

    final_text: str = ""
    if isinstance(generated, list):
        for item in generated:
            if isinstance(item, str) and item.strip():
                final_text = item.strip()
                break
    if not final_text and isinstance(generated, str):
        parts = [p.strip() for p in generated.split("=== VARIATION OVER ===") if p.strip()]
        if parts:
            final_text = parts[0]
    if not final_text:
        final_text = CUSTOM_PROMPT

    resp = requests.post(
        f"{API_BASE}/api/approve-draft",
        json={
            "draft_id": draft_id,
            "final_approved_text": final_text,
            "image_paths": draft_payload["image_paths"],
            "target_profile": PROFILE_ID,
        },
        timeout=30,
    )

    body = _assert_ok(resp, "approve-draft")
    assert body.get("status") == "success", body
    print(f"  PASS — draft {draft_id} queued for posting.")
    return draft_id


# ── Phase 4 ──────────────────────────────────────────────────────────────────
def poll_status(draft_id: str) -> str:
    print(f"\n[Phase 4] Polling worker status for {draft_id} …")
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    history: list[str] = []

    while time.monotonic() < deadline:
        status: str | None = None

        # Try the live listings endpoint first; fall back to local file.
        try:
            resp = requests.get(f"{API_BASE}/api/listings", timeout=10)
            if resp.status_code < 400:
                data = resp.json()
                for entry in data.get("listings", []):
                    if entry.get("id") == draft_id:
                        status = str(entry.get("status"))
                        break
        except requests.RequestException:
            pass

        if status is None and LISTINGS_FILE.is_file():
            try:
                with LISTINGS_FILE.open("r", encoding="utf-8") as fh:
                    listings: list[dict[str, Any]] = json.load(fh)
                for entry in listings:
                    if entry.get("id") == draft_id:
                        status = str(entry.get("status"))
                        break
            except (json.JSONDecodeError, OSError):
                pass

        if status and (not history or history[-1] != status):
            history.append(status)
            print(f"  status -> {status}")

        if status in {"completed", "shadow_success"}:
            print(f"  PASS — terminal status reached. History: {' -> '.join(history)}")
            return status

        if status in {"failed", "shadow_failed"}:
            print(f"  FAIL — worker reported failure. History: {' -> '.join(history)}")
            return status

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Polling timed out after {POLL_TIMEOUT_SECONDS}s. History: {' -> '.join(history)}"
    )


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  AutoBVB  ·  Local Orchestration Test")
    print("=" * 60)

    try:
        upload_profile_state()
        draft_payload = generate_draft()
        draft_id = approve_draft(draft_payload)
        terminal = poll_status(draft_id)

        print("\n" + "=" * 60)
        print(f"  FINAL RESULT  →  {terminal.upper()}")
        print("=" * 60)

    except FileNotFoundError as exc:
        print(f"\n[FATAL] Asset not found: {exc}", file=sys.stderr)
        sys.exit(1)
    except AssertionError as exc:
        print(f"\n[FATAL] Assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"\n[FATAL] HTTP error: {exc}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as exc:
        print(f"\n[FATAL] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FATAL] Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
