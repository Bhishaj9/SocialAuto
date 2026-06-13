"""Niyanth Governor Agent for AutoBVB draft orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import google.generativeai as genai

import content_engine

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=(
        "You are the AutoBVB Asset Manager. Return only YES or NO. "
        "Do not add explanations, punctuation, or extra words."
    )
)


def _read_image_parts(image_paths: list[str], max_images: int = 2) -> list[dict]:
    image_parts: list[dict] = []
    for image_path in image_paths[:max_images]:
        try:
            image_bytes = Path(image_path).read_bytes()
            image_parts.append({"mime_type": "image/jpeg", "data": image_bytes})
        except Exception as exc:
            print(f"[Asset Manager] Skipping image read error on: {image_path} | {exc}")
            continue
    return image_parts


def validate_assets(image_paths: list[str]) -> bool:
    """Verify assets are genuine real estate photos prior to firing the Two-Brain loop."""
    print(f"[Asset Manager] Auditing {len(image_paths)} pipeline images.")
    if not image_paths:
        return False

    image_parts = _read_image_parts(image_paths)
    if not image_parts:
        return False

    try:
        response = _model.generate_content(
            contents=[
                *image_parts,
                "Are these images valid real estate/property photos? Reply with only 'YES' or 'NO'.",
            ],
        )
        decision = (response.text or "").strip().upper()
        return decision.startswith("YES")
    except Exception as exc:
        print(f"[Asset Manager] Graceful degradation on error: {exc}")
        return False


def _format_generated_draft(generated_output: Any) -> str:
    if isinstance(generated_output, str):
        return generated_output
    if isinstance(generated_output, list):
        return "\n\n=== VARIATION OVER ===\n\n".join(
            str(item).strip() for item in generated_output if str(item).strip()
        )
    return str(generated_output)


def run_governed_pipeline(
    image_paths: list[str],
    flat_details: str,
    contact_number: str,
    custom_instruction: str | None = None,
) -> str:
    """Orchestrate asset validation and fire the asymmetric Two-Brain generation pipeline."""
    print("[Niyanth - Governor] Activating pipeline operations.")

    if os.getenv("AUTOBVB_MOCK_PIPELINE", "False").lower() in {"1", "true", "yes", "on"}:
        print("[Niyanth - Governor] MOCK MODE: Bypassing real pipeline. Returning mock captions.")
        return (
            "Luxurious 3BHK flat in Noida Extension.\n"
            "=== VARIATION OVER ===\n"
            "Premium flat available for immediate rent in Noida Extension.\n"
            "=== VARIATION OVER ===\n"
            "Superb 3BHK Sector 1 Noida Extension. Contact: +91-9999999999."
        )

    if not validate_assets(image_paths):
        print("[Niyanth - Governor] Quality Check Denied by Asset Manager.")
        return "ERROR: Images rejected by Asset Manager. Please ensure valid property photos are uploaded."

    try:
        combined_instruction_parts = [f"Client Specification Target: {flat_details}"]
        if custom_instruction and custom_instruction.strip():
            combined_instruction_parts.append(f"Custom Adjustments: {custom_instruction.strip()}")

        print("[Niyanth - Governor] Handing process variables off to Content Engine.")
        generated_output = content_engine.generate_captions(
            image_paths=image_paths,
            flat_details=flat_details,
            contact_number=contact_number,
            custom_instruction="\n".join(combined_instruction_parts),
        )
        
        return _format_generated_draft(generated_output)
    except Exception as exc:
        print(f"[Niyanth - Governor] Critical system bypass triggered: {exc}")
        return "ERROR: Production draft synthesis encountered engine timeout issues."
