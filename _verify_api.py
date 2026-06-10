#!/usr/bin/env python3
"""Test-mode API server launcher for Phase 1 verification.

Patches niyanth.validate_assets to always return True BEFORE uvicorn
loads the app, ensuring the Two-Brain pipeline (Brain 1 Vision → Brain 2
Copywriter) fires unconditionally during verification runs.
"""

from __future__ import annotations

import niyanth


def _always_valid(image_paths: list[str]) -> bool:
    print("[VERIFY-PATCH] Asset Manager bypassed — pipeline routed to Brain 1.")
    return True


niyanth.validate_assets = _always_valid

# Now import the app so uvicorn can serve it.
from api import app  # noqa: F401, E402
