"""
export_auth.py

Extract authenticated Facebook cookies from host Chrome browser and
serialize to Playwright storage state format.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

try:
    import browser_cookie3
except ImportError:
    browser_cookie3 = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CHROME_USER_DATA = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
STATE_FILE = Path("local_storage/profiles/test_agent_01/fb_state.json")
TARGET_DOMAINS = (".facebook.com", "facebook.com")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_chrome_profiles() -> list[Path]:
    """Return list of Chrome profile directories that have a Cookies file."""
    profiles = []
    if CHROME_USER_DATA.exists():
        for item in CHROME_USER_DATA.iterdir():
            if item.is_dir() and (item.name == "Default" or item.name.startswith("Profile")):
                cookies_file = item / "Network" / "Cookies"
                if cookies_file.exists():
                    profiles.append(item)
    return profiles


def extract_cookies_browser_cookie3() -> list[dict]:
    """Extract Facebook cookies using browser-cookie3 library."""
    if browser_cookie3 is None:
        return []

    cookies = []
    try:
        cj = browser_cookie3.chrome(domain_name="facebook.com")
        for cookie in cj:
            if any(d in cookie.domain for d in TARGET_DOMAINS):
                cookies.append({
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": int(cookie.expires) if cookie.expires else -1,
                    "httpOnly": cookie.httponly,
                    "secure": cookie.secure,
                    "sameSite": "Lax" if cookie.domain.startswith(".") else "None"
                })
    except Exception as e:
        print(f"[!] browser-cookie3 extraction failed: {e}")
    return cookies


def extract_cookies_sqlite3(profile_dir: Path) -> list[dict]:
    """Extract Facebook cookies by reading Chrome's SQLite cookie database directly."""
    cookies_db = profile_dir / "Network" / "Cookies"
    if not cookies_db.exists():
        return []

    cookies = []
    tmp_path = None
    try:
        import tempfile
        import shutil
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        # Try regular copy first (works if Chrome is closed)
        try:
            shutil.copy2(cookies_db, tmp_path)
        except PermissionError:
            # If locked, try shadowcopy (requires admin)
            try:
                import shadowcopy
                shadowcopy.shadow_copy(str(cookies_db), str(tmp_path))
            except Exception as e:
                raise RuntimeError(f"Cannot copy locked database. Close Chrome or run as admin: {e}")

        conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Chrome cookies table schema
        cursor.execute("""
            SELECT name, value, host_key, path, expires_utc, is_httponly, is_secure, same_site
            FROM cookies
            WHERE host_key LIKE '%facebook.com%'
        """)

        for row in cursor.fetchall():
            # Chrome stores expires as microseconds since Jan 1, 1601
            expires_utc = row["expires_utc"]
            if expires_utc > 0:
                # Convert to Unix timestamp (seconds since Jan 1, 1970)
                expires = int((expires_utc / 1_000_000) - 11644473600)
            else:
                expires = -1

            same_site_map = {0: "None", 1: "Lax", 2: "Strict"}
            same_site = same_site_map.get(row["same_site"], "Lax")

            cookies.append({
                "name": row["name"],
                "value": row["value"],
                "domain": row["host_key"],
                "path": row["path"],
                "expires": expires,
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": same_site
            })

        conn.close()
        tmp_path.unlink(missing_ok=True)

    except Exception as e:
        print(f"[!] SQLite extraction failed for {profile_dir.name}: {e}")

    return cookies


def deduplicate_cookies(cookies: list[dict]) -> list[dict]:
    """Remove duplicate cookies, keeping the one with furthest expiry."""
    seen = {}
    for cookie in cookies:
        key = (cookie["name"], cookie["domain"], cookie["path"])
        if key not in seen or cookie["expires"] > seen[key]["expires"]:
            seen[key] = cookie
    return list(seen.values())


def save_playwright_state(cookies: list[dict]) -> None:
    """Save cookies in Playwright storage state format."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "cookies": cookies,
        "origins": []
    }

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"[+] Saved {len(cookies)} cookies to {STATE_FILE.resolve()}")
    print(f"    Cookies: {len(cookies)}")
    print(f"    Origins: 0")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print(" Facebook Cookie Extractor (Host Chrome Profile)")
    print("=" * 60)
    print(f"[*] Chrome User Data: {CHROME_USER_DATA}")
    print(f"[*] Output file     : {STATE_FILE.resolve()}")
    print()

    # Try browser-cookie3 first (easiest)
    print("[*] Attempting extraction via browser-cookie3...")
    cookies = extract_cookies_browser_cookie3()

    if not cookies:
        print("[!] browser-cookie3 returned no cookies, trying direct SQLite...")
        profiles = get_chrome_profiles()
        print(f"[*] Found {len(profiles)} Chrome profile(s): {[p.name for p in profiles]}")

        for profile in profiles:
            print(f"[*] Reading cookies from profile: {profile.name}")
            cookies.extend(extract_cookies_sqlite3(profile))

    if not cookies:
        print("[!] No Facebook cookies found in any Chrome profile.")
        print("[!] Make sure you are logged into Facebook in Chrome.")
        sys.exit(1)

    # Deduplicate
    cookies = deduplicate_cookies(cookies)
    print(f"[+] Extracted {len(cookies)} unique Facebook cookies")

    # Print cookie names for verification
    for c in cookies:
        print(f"    - {c['name']} (domain: {c['domain']}, expires: {datetime.fromtimestamp(c['expires']) if c['expires'] > 0 else 'Session'})")

    # Save
    save_playwright_state(cookies)
    print("[+] Done. You can now run the worker with this auth state.")


if __name__ == "__main__":
    main()