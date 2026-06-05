"""Vision-coordinate cache for stable Playwright mouse targets."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

UI_MAP_FILE = Path("/app/local_storage/ui_map.json")
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720

_client = genai.Client()


def _load_cache() -> dict[str, Any]:
    if not UI_MAP_FILE.exists():
        return {}

    try:
        with UI_MAP_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    UI_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with UI_MAP_FILE.open("w", encoding="utf-8") as file:
        json.dump(cache, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _validate_coordinate(candidate: Any) -> tuple[int, int]:
    if not isinstance(candidate, dict):
        raise ValueError("Coordinate cache entry must be an object.")

    x = candidate.get("x")
    y = candidate.get("y")
    viewport = candidate.get("viewport")
    if viewport is not None:
        if not isinstance(viewport, dict):
            raise ValueError("Coordinate viewport metadata must be an object.")
        if viewport.get("width") != VIEWPORT_WIDTH or viewport.get("height") != VIEWPORT_HEIGHT:
            raise ValueError("Coordinate cache entry was captured for a different viewport.")

    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("Coordinate x and y values must be integers.")

    if not 0 <= x < VIEWPORT_WIDTH or not 0 <= y < VIEWPORT_HEIGHT:
        raise ValueError(f"Coordinate ({x}, {y}) is outside {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}.")

    return x, y


def _extract_coordinate(response_text: str) -> tuple[int, int]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\"x\"\s*:\s*\d+[^{}]*\"y\"\s*:\s*\d+[^{}]*\}", response_text)
        if match is None:
            raise ValueError(f"Gemini response did not include coordinate JSON: {response_text!r}")
        payload = json.loads(match.group(0))

    return _validate_coordinate(payload)


def _resolve_with_gemini(snapshot: bytes, element_key: str, description: str) -> tuple[int, int]:
    prompt = f"""
Return only strict JSON in this exact shape: {{"x": int, "y": int}}.

The image is a 1280x720 browser viewport. Identify the center pixel coordinate
for this UI target:

element_key: {element_key}
description: {description}

The coordinate must be within 0 <= x < 1280 and 0 <= y < 720.
"""
    response = _client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part.from_bytes(data=snapshot, mime_type="image/jpeg"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            system_instruction=(
                "You are a visual UI landmark detector. Return only JSON coordinates. "
                "Do not include markdown, prose, labels, or explanations."
            ),
        ),
    )
    return _extract_coordinate(response.text)


async def get_visual_target(page, element_key: str, description: str) -> tuple[int, int]:
    """Resolve a visual UI target coordinate using cache first, Gemini second."""

    cache = _load_cache()

    try:
        return _validate_coordinate(cache[element_key])
    except (KeyError, ValueError, TypeError):
        cache.pop(element_key, None)

    snapshot = await page.screenshot(type="jpeg")
    x, y = await asyncio.to_thread(_resolve_with_gemini, snapshot, element_key, description)

    cache[element_key] = {
        "x": x,
        "y": y,
        "viewport": {
            "width": VIEWPORT_WIDTH,
            "height": VIEWPORT_HEIGHT,
        },
        "description": description,
    }
    _save_cache(cache)
    return x, y
