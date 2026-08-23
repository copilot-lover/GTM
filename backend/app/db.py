import psycopg_pool

from app.config import get_settings

_pool: psycopg_pool.ConnectionPool | None = None


def get_conninfo() -> str:
    s = get_settings()
    return (
        f"host={s.postgres_host} port={s.postgres_port} dbname={s.postgres_db} "
        f"user={s.postgres_user} password={s.postgres_password}"
    )


def get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg_pool.ConnectionPool(get_conninfo(), min_size=1, max_size=10, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def execute_one(query: str, params: tuple) -> dict | None:
    from psycopg.rows import dict_row

    with get_pool().connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(query, params).fetchone()
