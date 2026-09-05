"""Test fixtures: isolated orbit_test database, migrations applied once per session,
per-test transaction rollback for isolation."""

import os
import pathlib

import psycopg
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ENV = {}
for line in (REPO / "backend" / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k] = v

TEST_DB_URL = (
    f"postgresql://{ENV['POSTGRES_USER']}:{ENV['POSTGRES_PASSWORD']}"
    f"@{ENV['POSTGRES_HOST']}:{ENV['POSTGRES_PORT']}/orbit_test"
)


@pytest.fixture(scope="session", autouse=True)
def applied_migrations():
    """Point the app at the isolated test DB and apply migrations."""
    import app.config as _config  # noqa: F401 - ensure cache cleared after env change

    os.environ["POSTGRES_DB"] = "orbit_test"
    _config.get_settings.cache_clear()
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    for f in sorted((REPO / "db" / "migrations").glob("*.sql")):
        done = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename=%s", (f.name,)
        ).fetchone()
        if not done:
            conn.execute(f.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,)
            )
    conn.close()
    os.environ["ORBIT_TEST_DB"] = TEST_DB_URL


@pytest.fixture(autouse=True)
def clean_db(applied_migrations):
    """Truncate all data tables between tests (keep schema)."""
    yield
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    tables = [
        r[0]
        for r in conn.execute(
            """SELECT tablename FROM pg_tables WHERE schemaname='public'
               AND tablename NOT IN ('schema_migrations')"""
        ).fetchall()
    ]
    if tables:
        conn.execute(f"TRUNCATE {', '.join(tables)} CASCADE")
    conn.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.main import RateLimitMiddleware
    RateLimitMiddleware.reset()
    yield
    RateLimitMiddleware.reset()


@pytest.fixture
def db_url() -> str:
    return TEST_DB_URL


@pytest.fixture
def workspace(db_url):
    """A workspace + owner user; returns (workspace_id, user_id)."""
    conn = psycopg.connect(db_url, autocommit=True)
    ws = conn.execute(
        "INSERT INTO workspaces (name) VALUES ('Test WS') RETURNING id"
    ).fetchone()[0]
    user = conn.execute(
        """INSERT INTO users (email, password_hash) VALUES ('op@test.dev','x')
           RETURNING id"""
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO workspace_members VALUES (%s,%s,'owner')", (ws, user)
    )
    conn.close()
    return str(ws), str(user)


def make_lead(db_url: str, workspace_id: str, name: str = "Acme Plumbing",
              city="Greensboro", state="NC", phone="(336) 555-0000") -> str:
    conn = psycopg.connect(db_url, autocommit=True)
    company = conn.execute(
        """INSERT INTO companies (workspace_id, business_name, city, state, phone)
           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (workspace_id, name, city, state, phone),
    ).fetchone()[0]
    lead = conn.execute(
        "INSERT INTO leads (workspace_id, company_id) VALUES (%s,%s) RETURNING id",
        (workspace_id, company),
    ).fetchone()[0]
    conn.close()
    return str(lead)
