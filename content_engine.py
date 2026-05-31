from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client()


def generate_captions(image_path: str, flat_details: str, contact_number: str) -> list:
    image_file = Path(image_path)
    if not image_file.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    image_bytes = image_file.read_bytes()
    prompt = f"""You are the Hermes Content Agent for AutoBVB, operating in the Noida Extension rental market. Your task is to analyze the uploaded image(s), verify them against the user-supplied input: {flat_details}, and output the final description exactly as a clean, production-ready text block for a Facebook post.

CRITICAL INSTRUCTION: Do NOT use any Markdown symbols (no **, no #, no _, no `). Facebook cannot render them. Use line breaks, capital letters, and emojis for visual structure and emphasis instead.

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
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are working as part of an AI system, so no chit-chat and no explaining what you're doing and why. "
                "DO NOT start with 'Okay', or 'Alright' or any preambles. Just the output, please."
            )
        ),
    )

    return [
        variation.strip()
        for variation in response.text.split("=== VARIATION OVER===")
        if variation.strip()
    ]
