import sqlite3
import tempfile
import shutil
from pathlib import Path

cookies_db = Path(r'C:\Users\Dell\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies')
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
    tmp_path = Path(tmp.name)
shutil.copy2(cookies_db, tmp_path)

conn = sqlite3.connect(f'file:{tmp_path}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT name, value, encrypted_value, host_key FROM cookies WHERE host_key LIKE '%facebook.com%' LIMIT 5")
for row in cursor.fetchall():
    print(f"name={row['name']}, value={row['value']}, encrypted_value_len={len(row['encrypted_value']) if row['encrypted_value'] else 0}, host_key={row['host_key']}")
conn.close()
tmp_path.unlink(missing_ok=True)