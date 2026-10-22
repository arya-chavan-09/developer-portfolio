"""PostgreSQL access (Neon in production).

Two connection pools, two roles:
  * DATABASE_URL           - the app's owner role. Reads and writes everything.
  * READONLY_DATABASE_URL  - `portfolio_reader`, which can SELECT from the three public
                             tables and nothing else. The visitor-facing `sql` command
                             runs on this role, so even a clever query cannot reach
                             contact_messages or change data. If it is not set, the
                             `sql` command is disabled.
"""
import logging
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import content

log = logging.getLogger("portfolio.db")

PUBLIC_TABLES = ("projects", "skills", "experience")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    slug       TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    stack      TEXT NOT NULL,
    year       INTEGER NOT NULL,
    status     TEXT NOT NULL,
    repo       TEXT,
    highlights JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    name     TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    level    INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5)
);
CREATE TABLE IF NOT EXISTS experience (
    id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company TEXT NOT NULL,
    role    TEXT NOT NULL,
    start   TEXT NOT NULL,
    "end"   TEXT,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contact_messages (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    message    TEXT NOT NULL,
    ip         TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_pool: ConnectionPool | None = None
_ro_pool: ConnectionPool | None = None


def _new_pool(url: str, **kwargs) -> ConnectionPool:
    return ConnectionPool(
        url, min_size=0, max_size=4, open=False, timeout=30, max_idle=120,
        check=ConnectionPool.check_connection,
        kwargs={"prepare_threshold": None, "connect_timeout": 20, **kwargs},
    )


def init_db() -> None:
    """Open pools, create tables, seed on first run, and grant the reader role access."""
    global _pool, _ro_pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. See README.md > Run it locally.")
    _pool = _new_pool(url, row_factory=dict_row)
    _pool.open()

    with _pool.connection() as conn:
        conn.execute(SCHEMA)
        if conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"] == 0:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO projects VALUES (%(slug)s,%(title)s,%(summary)s,%(stack)s,%(year)s,%(status)s,%(repo)s,%(highlights)s)",
                    [{**p, "highlights": Jsonb(p["highlights"])} for p in content.PROJECTS],
                )
                cur.executemany("INSERT INTO skills VALUES (%(name)s,%(category)s,%(level)s)", content.SKILLS)
                cur.executemany(
                    'INSERT INTO experience (company,role,start,"end",summary) VALUES (%(company)s,%(role)s,%(start)s,%(end)s,%(summary)s)',
                    content.EXPERIENCE,
                )

    ro_url = os.environ.get("READONLY_DATABASE_URL")
    if not ro_url:
        log.warning("READONLY_DATABASE_URL is not set: the public `sql` command is disabled.")
        return
    try:  # the reader role must already exist (see README); grants are idempotent
        with _pool.connection() as conn:
            conn.execute("GRANT USAGE ON SCHEMA public TO portfolio_reader")
            conn.execute(f"GRANT SELECT ON {', '.join(PUBLIC_TABLES)} TO portfolio_reader")
    except psycopg.Error as e:
        log.warning("Could not grant access to portfolio_reader (%s). `sql` command disabled.", str(e).splitlines()[0])
        return
    _ro_pool = _new_pool(ro_url)
    _ro_pool.open()


def close_db() -> None:
    for p in (_pool, _ro_pool):
        if p:
            p.close()


@contextmanager
def connect():
    """Read/write connection. Commits on success, rolls back on error."""
    assert _pool is not None, "init_db() has not run"
    with _pool.connection() as conn:
        yield conn


@contextmanager
def readonly():
    """Connection for visitor queries, or None when the reader role is not configured."""
    if _ro_pool is None:
        yield None
        return
    with _ro_pool.connection() as conn:
        yield conn


def project_row(row: dict) -> dict:
    d = dict(row)
    d["stack"] = [s.strip() for s in d["stack"].split(",")]
    return d