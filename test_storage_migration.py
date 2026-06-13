"""Integration test for Supabase binary asset storage migration."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

from storage import StorageEngine


def main() -> None:
    print("=" * 60)
    print("  Supabase Storage Migration Integration Test")
    print("=" * 60)

    # 1. Initialize StorageEngine
    try:
        engine = StorageEngine()
    except Exception as exc:
        print(f"[FAIL] StorageEngine initialization failed: {exc}")
        exit(1)

    # 2. Check or create dummy file
    project_dir = Path(__file__).resolve().parent
    dummy_file_path = project_dir / "dummy_flat.jpg"

    if not dummy_file_path.is_file():
        print(f"[INFO] dummy_flat.jpg not found. Creating a temporary test file.")
        dummy_file_path.write_bytes(b"Fake JPG contents for testing.")
        created_temp = True
    else:
        print(f"[INFO] Found dummy_flat.jpg ({dummy_file_path.stat().st_size:,} bytes).")
        created_temp = False

    # 3. Perform upload
    remote_path = "test_uploads/dummy_flat.jpg"
    print(f"[INFO] Uploading dummy_flat.jpg to '{remote_path}'...")
    
    try:
        public_url = engine.upload_file(str(dummy_file_path), remote_path)
    except Exception as exc:
        print(f"[FAIL] Upload failed with unhandled exception: {exc}")
        if created_temp and dummy_file_path.is_file():
            dummy_file_path.unlink()
        exit(1)

    # Clean up temporary file if we created one
    if created_temp and dummy_file_path.is_file():
        dummy_file_path.unlink()

    # 4. Assert and verify
    if not public_url:
        print("[FAIL] upload_file returned None.")
        exit(1)

    print(f"[SUCCESS] Upload completed successfully.")
    print(f"[SUCCESS] Public Supabase URL: {public_url}")

    # Assert that the public URL begins with configured local/cloud Supabase URL prefix
    expected_prefix = engine.url
    print(f"[INFO] Expected URL prefix: {expected_prefix}")

    # Basic normalization for comparison (e.g. trailing slashes, scheme)
    normalized_public_url = public_url.lower().strip()
    normalized_prefix = expected_prefix.lower().strip().rstrip("/")

    # Check prefix
    assert normalized_public_url.startswith(normalized_prefix), (
        f"Public URL '{public_url}' does not start with expected prefix '{expected_prefix}'."
    )

    print("[PASS] Assertion passed: Public URL matches the configured Supabase URL prefix.")
    print("=" * 60)


if __name__ == "__main__":
    main()
