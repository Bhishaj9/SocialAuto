import json
import base64
import sqlite3
import tempfile
import shutil
import os
from pathlib import Path

# Get the encryption key from Local State
local_state_path = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Local State"
with open(local_state_path, "r", encoding="utf-8") as f:
    local_state = json.load(f)

encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
encrypted_key = base64.b64decode(encrypted_key_b64)
# Remove DPAPI prefix
if encrypted_key[:5] == b"DPAPI":
    encrypted_key = encrypted_key[5:]

import win32crypt
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
    print(f"{row['name']}: prefix={encrypted_value[:3]!r}, len={len(encrypted_value)}")
    if encrypted_value[:3] == b'v10':
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext + tag, None)
            print(f"  DECRYPTED: {decrypted.decode()}")
        except Exception as e:
            print(f"  Failed to decrypt: {e}")
    elif encrypted_value[:3] == b'v11':
        print(f"  v11 format (not implemented)")
    else:
        print(f"  Unknown format")

conn.close()
tmp_path.unlink(missing_ok=True)