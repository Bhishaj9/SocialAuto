from __future__ import annotations

import os
import json
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Brain 1: Visual Analyst Extracting Pure Property Facts
_vision_analyst = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=(
        "You are the Visual Analyst for AutoBVB. Analyze property images and output a strict JSON block. "
        "No chat, no formatting wrappers outside of valid JSON syntax."
    )
)

# Brain 2: Copywriter Assembling Strategic Facebook Variations
_copywriter = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=(
        "You are the Marketing Copywriter for AutoBVB. Generate high-conversion real estate social media text. "
        "DO NOT use Markdown signatures like **, #, _, or ` under any circumstances."
    )
)


def extract_visual_specs(image_paths: list[str]) -> dict:
    """Brain 1: Multi-modal vision analysis yielding a clean structural specification dict."""
    image_parts: list[dict] = []
    
    for image_path in image_paths:
        image_file = Path(image_path)
        if image_file.exists():
            image_parts.append({"mime_type": "image/jpeg", "data": image_file.read_bytes()})

    if not image_parts:
        return {"error": "No readable image assets found"}

    prompt = """Analyze the attached real estate photos. Extract key factual structural data into a strict JSON dictionary.
    Do not assume features not visible. Look for structural layout, lighting conditions, balcony presence, kitchen style, flooring, and furnishing level.
    
    Return ONLY valid JSON using these exact string keys:
    {
      "detected_bhk": "string or unknown",
      "furnishing_status": "semi-furnished / fully-furnished / raw",
      "key_visual_highlights": ["amenity_1", "amenity_2"],
      "vibe_notes": "brief architectural description"
    }
    """
    
    try:
        response = _vision_analyst.generate_content(contents=[*image_parts, prompt])
        clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as exc:
        print(f"[Brain 1 - Vision] Parsing error or timeout: {exc}")
        exc_str = str(exc).lower()
        if "429" in exc_str or "quota" in exc_str:
            raise exc
        return {"error": "Visual extraction bypassed due to processing limits"}


def generate_captions(
    image_paths: list[str],
    flat_details: str,
    contact_number: str,
    custom_instruction: str | None = None,
) -> list[str]:
    """Brain 2: Synthesizes extracted vision specs with worker inputs into 3 clean variations."""
    
    # Run Brain 1 to extract structural realities
    print("[Brain 1 - Vision] Extracting property metrics from image matrix...")
    visual_specs = extract_visual_specs(image_paths)
    print(f"[Brain 1 - Vision] Extracted specs: {visual_specs}")

    custom_instruction_block = (
        f"\nEMPLOYEE CUSTOM INSTRUCTION:\n{custom_instruction.strip()}\n"
        if custom_instruction and custom_instruction.strip()
        else ""
    )

    prompt = f"""You are the Hermes Content Copywriter for AutoBVB operating in the Noida Extension real estate domain.
    Synthesize the Verified Physical Asset Specs with User Requirements to generate clean social media text.

    VERIFIED PHYSICAL ASSET SPECS (FROM IMAGE VISION):
    {json.dumps(visual_specs, indent=2)}

    USER-SUPPLIED INPUT METRICS:
    - Target Flat Base: {flat_details}
    - Contact Anchor: {contact_number}
    {custom_instruction_block}

    CRITICAL PLATFORM ENFORCEMENT: 
    Do NOT output ANY markdown headers, bullet boldings, or inline code blocks (No **, No #, No _, No `). 
    Facebook cannot render markdown text correctly. Rely exclusively on capitalization, clean line-breaks, and emojis for structure.

    Use this exact baseline string within your output structure:
    Call and WhatsApp on {contact_number} ✨Luxurious flat available for rent 
    📍Location: Noida Extension 
    👉 Type:- {flat_details} 
    👉 Immediate shifting 
    👉 All the amenities are available 
    👉 For Family and Bachelor 
    👉 Club House 🏡 
    👉 Gym 
    👉 Swimming pool 🏊♀️ 
    👉 Power backup 
    👉 Near by school 
    👉 Near by metro : sector - 52

    Generate exactly 3 distinct fuzzy text variations to completely bypass Meta spam signatures. Separate them using the string '=== VARIATION OVER ==='.

    Variation 1: The Gold Standard (Professional & Highly Organized)
    Variation 2: The Lifestyle Narrative (Warm & Story-focused)
    Variation 3: The Short & Urgent (Scarcity & Direct Action)
    """

    try:
        response = _copywriter.generate_content(contents=[prompt])
        return [
            variation.strip()
            for variation in response.text.split("=== VARIATION OVER ===")
            if variation.strip()
        ]
    except Exception as exc:
        print(f"[Brain 2 - Copywriter] Generation failed or rate-limited: {exc}")
        exc_str = str(exc).lower()
        if "429" in exc_str or "quota" in exc_str:
            raise exc
        print("[Brain 2 - Copywriter] Falling back to high-conversion Noida Extension marketing copy.")
        fallback_variation = f"""Call and WhatsApp on {contact_number} ✨Luxurious flat available for rent 
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
👉 Near by metro : sector - 52"""
        return [
            fallback_variation + "\n\n(Variation 1: Premium Professional)",
            fallback_variation + "\n\n(Variation 2: Cozy Family Vibe)",
            fallback_variation + "\n\n(Variation 3: Short & Urgent)"
        ]
