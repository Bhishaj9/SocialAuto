from __future__ import annotations

import os
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=(
        "You are working as part of an AI system, so no chit-chat and no explaining what you're doing and why. "
        "DO NOT start with 'Okay', or 'Alright' or any preambles. Just the output, please."
    )
)


def generate_captions(
    image_paths: list[str],
    flat_details: str,
    contact_number: str,
    custom_instruction: str | None = None,
) -> list[str]:
    image_parts: list[dict] = []
    missing_images: list[str] = []

    for image_path in image_paths:
        image_file = Path(image_path)
        try:
            image_bytes = image_file.read_bytes()
        except FileNotFoundError:
            missing_images.append(image_path)
            continue

        image_parts.append({"mime_type": "image/jpeg", "data": image_bytes})

    if missing_images:
        print(f"[content_engine] Skipping missing image(s): {', '.join(missing_images)}")

    if not image_parts:
        raise FileNotFoundError(f"No readable image files found: {', '.join(image_paths)}")

    custom_instruction_block = (
        f"\nUSER CUSTOM INSTRUCTION:\n{custom_instruction.strip()}\n"
        if custom_instruction and custom_instruction.strip()
        else ""
    )

    prompt = f"""You are the Hermes Content Agent for AutoBVB, operating in the Noida Extension rental market. Your task is to analyze the uploaded image(s), verify them against the user-supplied input: {flat_details}, and output the final description exactly as a clean, production-ready text block for a Facebook post.

CRITICAL INSTRUCTION: Do NOT use any Markdown symbols (no **, no #, no _, no `). Facebook cannot render them. Use line breaks, capital letters, and emojis for visual structure and emphasis instead.
{custom_instruction_block}
Use this exact string template formatting for your baseline facts:
Call and WhatsApp on {contact_number} ✨Luxurious flat available for rent 
📍Location: Noida Extension 
👉 Type:- {flat_details} 
👉 Immediate shifting 
👉 All the amenities are available 
👉 For Family and Bachelor 
👉 Club House 🏡 
👉 Gym 
👉 Swimming pool 🏊‍♀️ 
👉 Power backup 
👉 Near by school 
👉 Near by metro : sector - 52

Generate exactly 3 distinct structural variations to bypass Meta's automated spam filters. Separate each variation using a clear separator token like "=== VARIATION OVER ===".

Variation 1: The Gold Standard (Professional & Structured)
Variation 2: The Lifestyle Narrative (Conversational)
Variation 3: The Short & Urgent (Scarcity-Driven)
"""
    response = _model.generate_content(
        contents=[*image_parts, prompt],
    )

    return [
        variation.strip()
        for variation in response.text.split("=== VARIATION OVER ===")
        if variation.strip()
    ]
