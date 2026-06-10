#!/usr/bin/env python3
"""AutoBVB Phase 1 Verification Harness — Automated Two-Brain Refactoring Validation.

Launches the FastAPI server, runs both e2e and live-local test suites via
patched wrappers, and programmatically verifies the presence of three critical
operational signatures that prove the Two-Brain pipeline (Vision → Copywriter)
is wired correctly.

Key design decisions:
  - Uses wrapper scripts (_verify_e2e_wrapper.py / _verify_live_wrapper.py) that
    monkey-patch niyanth.validate_assets to bypass the Asset Manager gate —
    ensuring the Brain 1 Vision analysis always fires during verification.
  - Copies a real property image to dummy_flat.jpg so Brain 1 has real pixels.
  - Inserts a 40-second cooldown between test suites for Gemini quota recovery.
  - Searches BOTH test-runner output AND the API server's stdout for signatures
    (Brain 1 signatures are emitted server-side via print()).
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────
PYTHON = r"C:\Users\Dell\AppData\Local\Programs\Python\Python313\python.exe"
PROJECT_DIR = Path(__file__).resolve().parent
API_HOST = "0.0.0.0"
API_PORT = 8000
SERVER_STARTUP_WAIT = 5          # seconds to allow uvicorn to bind
INTER_TEST_COOLDOWN = 40         # seconds between test suites (quota recovery)
SUBPROCESS_TIMEOUT = 300         # max seconds per test subprocess
SHUTDOWN_GRACE_PERIOD = 5        # seconds before escalating to kill

REAL_IMAGE_SOURCE = PROJECT_DIR / "local_storage" / "flats01" / "flat1.jpg"
DUMMY_IMAGE_TARGET = PROJECT_DIR / "dummy_flat.jpg"

# Verification signatures — checked via substring containment.
REQUIRED_SIGNATURES = [
    "[Brain 1 - Vision] Extracting property metrics",
    "[Brain 1 - Vision] Extracted specs:",
    "Step 2: Generating AI Draft... PASS",
]


# ── Utilities ────────────────────────────────────────────────────────────────
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _drain_pipe(pipe, sink: list[str], stop_event: threading.Event) -> None:
    try:
        while not stop_event.is_set():
            line = pipe.readline()
            if not line:
                break
            sink.append(line)
    except (ValueError, OSError):
        pass


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


# ── Core Verification Logic ─────────────────────────────────────────────────
def run_verification() -> bool:
    api_proc: subprocess.Popen | None = None
    api_lines: list[str] = []
    stop_event = threading.Event()

    try:
        # ── Pre-flight ───────────────────────────────────────────────────
        if _port_in_use(API_PORT):
            print(f"[VERIFY] ABORT: Port {API_PORT} is already in use.")
            return False

        print("[VERIFY] Pre-flight — Seeding real property image...")
        if REAL_IMAGE_SOURCE.is_file():
            shutil.copy2(REAL_IMAGE_SOURCE, DUMMY_IMAGE_TARGET)
            print(f"  Seeded {DUMMY_IMAGE_TARGET.name} ({DUMMY_IMAGE_TARGET.stat().st_size:,} bytes)")
        else:
            print(f"  WARNING: {REAL_IMAGE_SOURCE} not found — using existing dummy")

        # ── Step 1: Launch API server ────────────────────────────────────
        print(f"\n[VERIFY] Step 1 — Launching uvicorn _verify_api:app on port {API_PORT}...")
        print("  (Asset Manager bypassed via _verify_api.py patch)")
        api_proc = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "_verify_api:app",
             "--host", API_HOST, "--port", str(API_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_DIR),
        )
        reader = threading.Thread(
            target=_drain_pipe,
            args=(api_proc.stdout, api_lines, stop_event),
            daemon=True,
        )
        reader.start()

        # ── Step 2: Wait for readiness ───────────────────────────────────
        print(f"[VERIFY] Step 2 — Waiting {SERVER_STARTUP_WAIT}s for server startup...")
        time.sleep(SERVER_STARTUP_WAIT)

        if api_proc.poll() is not None:
            stop_event.set()
            print(f"[VERIFY] ABORT: Server exited early (code {api_proc.returncode}).")
            print("".join(api_lines))
            return False

        if not _port_in_use(API_PORT):
            print("[VERIFY] WARNING: Port still not listening — continuing anyway...")

        # ── Step 3: Run e2e_tester via wrapper ───────────────────────────
        print("\n[VERIFY] Step 3 — Running _verify_e2e_wrapper.py...")
        e2e = subprocess.run(
            [PYTHON, "_verify_e2e_wrapper.py"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_DIR),
        )
        e2e_out = e2e.stdout + e2e.stderr
        print(f"  exit code: {e2e.returncode}")
        # Show first 2000 chars of output for live visibility
        print(f"  --- e2e output (first 2000 chars) ---")
        print(e2e_out[:2000])
        print(f"  --- end e2e output ---")

        # ── Quota cooldown ───────────────────────────────────────────────
        print(f"\n[VERIFY] Cooling down {INTER_TEST_COOLDOWN}s for Gemini quota recovery...")
        time.sleep(INTER_TEST_COOLDOWN)

        # ── Step 4: Run live_local_test via wrapper ──────────────────────
        print("\n[VERIFY] Step 4 — Running _verify_live_wrapper.py...")
        live = subprocess.run(
            [PYTHON, "_verify_live_wrapper.py"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_DIR),
        )
        live_out = live.stdout + live.stderr
        print(f"  exit code: {live.returncode}")
        print(f"  --- live output (first 2000 chars) ---")
        print(live_out[:2000])
        print(f"  --- end live output ---")

        # ── Capture API server logs ──────────────────────────────────────
        stop_event.set()
        time.sleep(0.5)
        api_log = "".join(api_lines)

        # ── Build combined log corpus ────────────────────────────────────
        combined_log = "\n".join([
            "=== E2E TESTER OUTPUT ===",
            e2e_out,
            "=== LIVE LOCAL TEST OUTPUT ===",
            live_out,
            "=== API SERVER OUTPUT ===",
            api_log,
        ])

        # ── Step 5: Signature verification ───────────────────────────────
        print("\n" + "=" * 64)
        print("[VERIFY] Step 5 — Operational Signature Verification")
        print("=" * 64)
        missing: list[str] = []
        for sig in REQUIRED_SIGNATURES:
            if sig in combined_log:
                print(f"  ✅  FOUND   : {sig}")
            else:
                print(f"  ❌  MISSING : {sig}")
                missing.append(sig)

        if missing:
            print(f"\n[VERIFY] FAILURE — {len(missing)}/{len(REQUIRED_SIGNATURES)} signature(s) missing.")
            # Dump full API server log for diagnosis (this is where Brain 1 prints)
            print("\n[VERIFY] ── Full API Server Log ──")
            print(api_log)
            return False

        print(f"\n[VERIFY] SUCCESS — All {len(REQUIRED_SIGNATURES)} verification signatures confirmed.")
        return True

    except subprocess.TimeoutExpired as exc:
        print(f"[VERIFY] ERROR: Subprocess timed out — {exc}")
        return False
    except Exception as exc:
        print(f"[VERIFY] ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # ── Step 6: Strict fail-safe teardown ────────────────────────────
        if api_proc is not None:
            print("\n[VERIFY] Tearing down background API server...")
            stop_event.set()
            try:
                api_proc.terminate()
                api_proc.wait(timeout=SHUTDOWN_GRACE_PERIOD)
                print("[VERIFY]   Terminated cleanly.")
            except subprocess.TimeoutExpired:
                print("[VERIFY]   Force killing process tree...")
                _kill_tree(api_proc.pid)
                api_proc.wait()
                print("[VERIFY]   Force kill complete.")
            except Exception as exc:
                print(f"[VERIFY]   Cleanup error: {exc}")
                _kill_tree(api_proc.pid)


# ── Entry Point ──────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 64)
    print("  AutoBVB  ·  Phase 1 Two-Brain Verification Harness")
    print("=" * 64)
    print(f"  Python       : {PYTHON}")
    print(f"  Project      : {PROJECT_DIR}")
    print(f"  Port         : {API_PORT}")
    print(f"  Real Image   : {REAL_IMAGE_SOURCE}")
    print(f"  Cooldown     : {INTER_TEST_COOLDOWN}s")
    print(f"  Signatures   : {len(REQUIRED_SIGNATURES)}")
    print("=" * 64)

    passed = run_verification()

    print("\n" + "=" * 64)
    if passed:
        print("  ✅  VERIFICATION PASSED — Phase 1 Two-Brain refactoring validated")
    else:
        print("  ❌  VERIFICATION FAILED — Review logs above for details")
    print("=" * 64)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
