"""Quick health-check for the local Supabase instance.

Run:  python verify_supabase.py
"""

import os, json, urllib.request

SUPABASE_URL = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SERVICE_KEY  = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU",
)

def main() -> None:
    # --- 1. REST API health ---
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/",
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(f"[OK] REST API  — HTTP {resp.status}")

    # --- 2. Storage API health ---
    req2 = urllib.request.Request(
        f"{SUPABASE_URL}/storage/v1/bucket",
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
        },
    )
    with urllib.request.urlopen(req2, timeout=5) as resp2:
        buckets = json.loads(resp2.read())
        names = [b["name"] for b in buckets]
        ok = "property-assets" in names
        print(f"[{'OK' if ok else 'FAIL'}] Storage    — buckets: {names}")

    # --- 3. Auth health ---
    req3 = urllib.request.Request(f"{SUPABASE_URL}/auth/v1/health")
    with urllib.request.urlopen(req3, timeout=5) as resp3:
        print(f"[OK] Auth      — HTTP {resp3.status}")

    print("\nAll local Supabase services are reachable.")


if __name__ == "__main__":
    main()
