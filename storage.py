"""Supabase-backed binary asset storage for AutoBVB."""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

import sys
from dotenv import load_dotenv

# Evict the local 'supabase' directory shadowing by removing empty string, '.', and current directory from sys.path temporarily
_orig_sys_path = list(sys.path)
try:
    sys.path = [p for p in sys.path if p not in ("", ".", os.getcwd(), os.path.dirname(os.path.abspath(__file__)))]
    from supabase import create_client, Client
finally:
    sys.path = _orig_sys_path


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StorageEngine")


class StorageEngine:
    """Storage Engine using Supabase client to stream uploads to public buckets."""

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
            logger.error("[StorageEngine] Missing SUPABASE_URL or SUPABASE key in environment.")
            raise ValueError(
                "Supabase URL and Key (Service Role or Anon) must be set via environment or arguments."
            )

        logger.info(f"[StorageEngine] Initializing Supabase client pointing to: {self.url}")
        self.client: Client = create_client(self.url, self.key)

    def upload_file(self, local_path: str, remote_destination_path: str) -> Optional[str]:
        """Upload a local file to the 'property-assets' Supabase storage bucket.

        Args:
            local_path: Path to the local file to upload.
            remote_destination_path: Remote path in the bucket.

        Returns:
            The public URL of the uploaded file, or None if the upload failed.
        """
        local_file = Path(local_path)
        if not local_file.is_file():
            logger.error(f"[StorageEngine] Local file does not exist: {local_path}")
            return None

        # MIME-Type Auto-Detection
        mime_type, _ = mimetypes.guess_type(local_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        logger.info(
            f"[StorageEngine] Uploading {local_path} ({mime_type}) to "
            f"bucket 'property-assets' at path '{remote_destination_path}'..."
        )

        try:
            # File Stream Handling: safely open file in binary read mode
            with open(local_file, "rb") as f:
                # Upsert Protocol
                file_options = {
                    "content-type": mime_type,
                    "upsert": "true"
                }

                # Perform streaming upload
                self.client.storage.from_("property-assets").upload(
                    path=remote_destination_path,
                    file=f,
                    file_options=file_options
                )

            logger.info(f"[StorageEngine] Successfully uploaded {local_path} to {remote_destination_path}")

            # Public URL Extraction
            public_url_response = self.client.storage.from_("property-assets").get_public_url(remote_destination_path)

            # Robust extraction handling for various supabase-py version return types
            public_url: str | None = None
            if isinstance(public_url_response, str):
                public_url = public_url_response
            elif isinstance(public_url_response, dict):
                public_url = public_url_response.get("publicUrl") or public_url_response.get("public_url")
            elif hasattr(public_url_response, "public_url"):
                public_url = getattr(public_url_response, "public_url")
            elif hasattr(public_url_response, "publicUrl"):
                public_url = getattr(public_url_response, "publicUrl")
            elif hasattr(public_url_response, "data") and isinstance(public_url_response.data, dict):
                public_url = public_url_response.data.get("publicUrl") or public_url_response.data.get("public_url")

            if not public_url:
                # Fallback to manual string reconstruction if extraction failed
                public_url = f"{self.url}/storage/v1/object/public/property-assets/{remote_destination_path}"
                logger.warning(
                    f"[StorageEngine] Could not parse get_public_url response {public_url_response}. "
                    f"Fell back to constructed URL: {public_url}"
                )

            logger.info(f"[StorageEngine] Extracted public URL: {public_url}")
            return public_url

        except Exception as e:
            logger.exception(f"[StorageEngine] Error uploading file {local_path} to {remote_destination_path}: {e}")
            return None
