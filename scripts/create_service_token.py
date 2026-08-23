"""Create the n8n service account + long-lived token.

Usage: uv run python scripts/create_service_token.py
- creates automation@orbit.local (no human login intended)
- adds it to every existing workspace as 'admin'
- writes ORBIT_SERVICE_TOKEN into backend/.env (gitignored)
"""
import os
import pathlib
import sys
import time

import psycopg

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.core.security import hash_password  # noqa: E402
import jwt  # noqa: E402

ENV = {}
for line in (REPO / "backend" / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k] = v

DB_URL = (
    f"postgresql://{ENV['POSTGRES_USER']}:{ENV['POSTGRES_PASSWORD']}"
    f"@{ENV['POSTGRES_HOST']}:{ENV['POSTGRES_PORT']}/{ENV['POSTGRES_DB']}"
)

conn = psycopg.connect(DB_URL, autocommit=True)
row = conn.execute("SELECT id FROM users WHERE email='automation@orbit.local'").fetchone()
if row:
    user_id = str(row[0])
    print("service user exists:", user_id)
else:
    user_id = str(conn.execute(
        """INSERT INTO users (email, password_hash, display_name)
           VALUES ('automation@orbit.local', %s, 'n8n automation') RETURNING id""",
        (hash_password(os.urandom(24).hex()),),
    ).fetchone()[0])
    print("created service user:", user_id)

for (ws_id,) in conn.execute("SELECT id FROM workspaces").fetchall():
    conn.execute(
        """INSERT INTO workspace_members (workspace_id, user_id, role)
           VALUES (%s,%s,'admin') ON CONFLICT DO NOTHING""",
        (ws_id, user_id),
    )

token = jwt.encode(
    {"sub": user_id, "ws": str(conn.execute(
        "SELECT workspace_id FROM workspace_members WHERE user_id=%s LIMIT 1",
        (user_id,)).fetchone()[0]),
     "iat": int(time.time()), "exp": int(time.time()) + 10 * 365 * 86400},
    ENV["JWT_SECRET"], algorithm="HS256",
)
conn.close()

env_path = REPO / "backend" / ".env"
content = env_path.read_text()
if "ORBIT_SERVICE_TOKEN=" in content:
    lines = [l for l in content.splitlines()
             if not l.startswith("ORBIT_SERVICE_TOKEN=")]
    content = "\n".join(lines) + "\n"
content += f"\nORBIT_SERVICE_TOKEN={token}\n"
env_path.write_text(content)
print("token written to backend/.env (10-year expiry)")
