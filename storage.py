"""Local file-backed storage mock for AutoBVB proof screenshots."""

from __future__ import annotations

import shutil
from pathlib import Path

LOCAL_PROOF_DIR = Path(__file__).resolve().parent / "local_storage" / "proofs"


def upload_proof(local_file_path: str | Path, destination_name: str | None = None) -> str:
    """Copy a proof screenshot into local_storage/proofs and return its path."""
    source_path = Path(local_file_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Proof file was not found: {source_path}")

    LOCAL_PROOF_DIR.mkdir(parents=True, exist_ok=True)
    target_name = destination_name or source_path.name
    destination_path = LOCAL_PROOF_DIR / target_name

    print(f"[storage] Copying proof from {source_path.resolve()}...")
    shutil.copy2(source_path, destination_path)
    print(f"[storage] Proof saved locally at {destination_path.resolve()}.")

    return str(destination_path)


class StorageManager:
    """Compatibility wrapper for the live GCS storage manager."""

    def upload_screenshot(
        self, local_file_path: str | Path, destination_blob_name: str
    ) -> str:
        safe_name = Path(destination_blob_name).name
        return upload_proof(local_file_path, safe_name)
