#!/usr/bin/env python3
"""Wrapper for live_local_test that ensures the Two-Brain pipeline fires.

Patches niyanth.validate_assets() to always return True so the pipeline
is not short-circuited by Asset Manager failures during verification.
Also reduces polling timeout to avoid long waits (worker isn't running).
"""

from __future__ import annotations

import sys

# Must be imported BEFORE live_local_test so the patch takes effect.
import niyanth


def _always_valid(image_paths: list[str]) -> bool:
    print("[VERIFY-PATCH] Asset Manager bypassed — forcing pipeline through to Brain 1.")
    return True


niyanth.validate_assets = _always_valid

# Now import and patch live_local_test.
import live_local_test

# Reduce polling timeout — worker isn't running so we'll always time out.
# 10 seconds is enough to confirm the listing was queued.
live_local_test.POLL_TIMEOUT_SECONDS = 10

if __name__ == "__main__":
    live_local_test.main()
