"""Tests run against a real PostgreSQL. Locally:  docker compose up -d db
Override the target with TEST_DATABASE_URL (the user must be allowed to create roles)."""
import os
from urllib.parse import urlsplit, urlunsplit

import psycopg

ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:dev@localhost:5432/portfolio_test")


def reader_url(url: str) -> str:
    p = urlsplit(url)
    port = f":{p.port}" if p.port else ""
    return urlunsplit((p.scheme, f"portfolio_reader:readerpass@{p.hostname}{port}", p.path, "", ""))


os.environ["DATABASE_URL"] = ADMIN_URL
os.environ["READONLY_DATABASE_URL"] = reader_url(ADMIN_URL)
os.environ["ADMIN_PASSWORD"] = "correct-horse-battery"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ALLOWED_HOSTS", None)

with psycopg.connect(ADMIN_URL, autocommit=True) as c:  # clean slate + the reader role
    c.execute("DROP TABLE IF EXISTS contact_messages, experience, skills, projects CASCADE")
    c.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='portfolio_reader') "
        "THEN CREATE ROLE portfolio_reader LOGIN PASSWORD 'readerpass'; END IF; END $$"
    )