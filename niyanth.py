"""Niyanth Governor Agent for AutoBVB draft orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

import content_engine

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else genai.Client()


def _read_image_parts(image_paths: list[str], max_images: int = 2) -> list[types.Part]:
    image_parts: list[types.Part] = []

    for image_path in image_paths[:max_images]:
        try:
            image_bytes = Path(image_path).read_bytes()
        except FileNotFoundError:
            print(f"[Asset Manager] Missing image skipped during validation: {image_path}")
            continue
        except OSError as exc:
            print(f"[Asset Manager] Could not read image during validation: {image_path} | {exc}")
            continue

        image_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

    return image_parts


def validate_assets(image_paths: list[str]) -> bool:
    """Validate that uploaded assets appear to be real property photos."""
    print(f"[Asset Manager] Validating {len(image_paths)} image(s).")

    if not image_paths:
        print("[Asset Manager] Rejected: no image paths provided.")
        return False

    image_parts = _read_image_parts(image_paths)
    if not image_parts:
        print("[Asset Manager] Rejected: no readable images found.")
        return False

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                *image_parts,
                "Are these images valid real estate/property photos? Reply with only 'YES' or 'NO'.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are the AutoBVB Asset Manager. Return only YES or NO. "
                    "Do not add explanations, punctuation, or extra words."
                )
            ),
        )
    except Exception as exc:
        print(f"[Asset Manager] Gemini validation failed gracefully: {exc}")
        return False

    decision = (response.text or "").strip().upper()
    is_valid = decision.startswith("YES")
    print(f"[Asset Manager] Validation decision: {'YES' if is_valid else 'NO'}")
    return is_valid


def _format_generated_draft(generated_output: Any) -> str:
    if isinstance(generated_output, str):
        return generated_output

    if isinstance(generated_output, list):
        return "\n\n=== VARIATION OVER ===\n\n".join(str(item).strip() for item in generated_output if str(item).strip())

    return str(generated_output)


def run_governed_pipeline(
    image_paths: list[str],
    flat_details: str,
    contact_number: str,
    custom_instruction: str | None = None,
) -> str:
    """Run the governed AutoBVB caption pipeline and return a reviewable draft."""
    print("[Niyanth - Governor] Starting governed draft pipeline.")

    try:
        print("[Niyanth - Governor] Handing images to Asset Manager.")
        if not validate_assets(image_paths):
            print("[Niyanth - Governor] Asset Manager rejected the upload.")
            return "ERROR: Images rejected by Asset Manager. Please ensure valid property photos are uploaded."

        combined_instruction_parts = [
            f"Flat details: {flat_details}",
            f"Contact number: {contact_number}",
        ]
        if custom_instruction and custom_instruction.strip():
            combined_instruction_parts.append(f"Custom instruction: {custom_instruction.strip()}")

        combined_instruction = "\n".join(combined_instruction_parts)
        print("[Niyanth - Governor] Dispatching validated assets to Content Manager.")

        generated_output = content_engine.generate_captions(
            image_paths=image_paths,
            flat_details=flat_details,
            contact_number=contact_number,
            custom_instruction=combined_instruction,
        )
        generated_draft = _format_generated_draft(generated_output)

        print("[Niyanth - Governor] Governed draft pipeline completed successfully.")
        return generated_draft
    except Exception as exc:
        print(f"[Niyanth - Governor] Pipeline failed gracefully: {exc}")
        return "ERROR: Draft generation failed. Please try again after checking the uploaded assets and AI configuration."
