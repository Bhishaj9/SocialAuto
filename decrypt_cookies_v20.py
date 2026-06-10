import json
import base64
import sqlite3
import tempfile
import shutil
import os
from pathlib import Path
import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Get the encryption key from Local State
local_state_path = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Local State"
with open(local_state_path, "r", encoding="utf-8") as f:
    local_state = json.load(f)

encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
encrypted_key = base64.b64decode(encrypted_key_b64)
if encrypted_key[:5] == b"DPAPI":
    encrypted_key = encrypted_key[5:]
key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
print(f"Decrypted key length: {len(key)}")

# Now decrypt cookies
cookies_db = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Default" / "Network" / "Cookies"
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
    tmp_path = Path(tmp.name)
shutil.copy2(cookies_db, tmp_path)

conn = sqlite3.connect(f'file:{tmp_path}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT name, encrypted_value, host_key, path, expires_utc, is_httponly, is_secure, samesite FROM cookies WHERE host_key LIKE '%facebook.com%'")
for row in cursor.fetchall():
    encrypted_value = row['encrypted_value']
    print(f"\n{row['name']}: prefix={encrypted_value[:3]!r}, len={len(encrypted_value)}")
    
    # Try v10/v20 format: prefix (3) + nonce (12) + ciphertext + tag (16)
    if encrypted_value[:3] in (b'v10', b'v11', b'v20'):
        try:
            nonce = encrypted_value[3:15]
            ciphertext_and_tag = encrypted_value[15:]
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
            print(f"  DECRYPTED: {decrypted.decode()}")
        except Exception as e:
            print(f"  Failed to decrypt (v10 format): {e}")
            
            # Try alternative: maybe v20 has different structure
            # Some sources say v20 uses 12-byte nonce + ciphertext + 16-byte tag
            # But the data might be structured differently
            try:
                # Try with 12-byte nonce at position 3
                nonce = encrypted_value[3:15]
                ciphertext = encrypted_value[15:-16]
                tag = encrypted_value[-16:]
                aesgcm = AESGCM(key)
                decrypted = aesgcm.decrypt(nonce, ciphertext + tag, None)
                print(f"  DECRYPTED (alt): {decrypted.decode()}")
            except Exception as e2:
                print(f"  Failed to decrypt (alt): {e2}")

conn.close()
tmp_path.unlink(missing_ok=True)