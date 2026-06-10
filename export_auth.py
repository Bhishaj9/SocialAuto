import os
import json
from pathlib import Path
import browser_cookie3

def extract_cookies():
    root_dir = Path(__file__).resolve().parent
    target_state_path = root_dir / "local_storage" / "profiles" / "test_agent_01" / "fb_state.json"
    
    print("[Extractor] Extracting .facebook.com cookies from local Chrome profile using browser-cookie3...")
    try:
        cj = browser_cookie3.chrome(domain_name='.facebook.com')
    except Exception as e:
        print(f"[Extractor] ERROR extracting cookies: {e}")
        return

    cookies_list = []
    for c in cj:
        cookies_list.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "expires": -1 if c.expires is None else int(c.expires),
            "httpOnly": 'HttpOnly' in c._rest.keys() if hasattr(c, '_rest') else False,
            "secure": c.secure,
            "sameSite": "None"
        })

    output_payload = {
        "cookies": cookies_list,
        "origins": []
    }
    
    target_state_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(target_state_path, "w", encoding="utf-8") as out_file:
        json.dump(output_payload, out_file, indent=2)
        
    print(f"[Extractor] SUCCESS: Extracted {len(cookies_list)} cookies and wrote state to {target_state_path}")

if __name__ == '__main__':
    extract_cookies()