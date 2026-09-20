"""Test fixtures.

Tests run against a real Postgres (the `db` service), not a stand-in: the exclusion
constraint, SELECT ... FOR UPDATE and the unique idempotency key are the things under
test, and none of them exist in SQLite. Each test gets a clean set of tables.
"""
from __future__ import annotations

import os

import pytest

# Database imports are deliberately lazy: the rule-engine tests are pure and must run
# without Postgres, alembic or the web stack being importable.

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://formulary:formulary@db:5432/formulary_test"
)
# The app reads DATABASE_URL at import time, so point it at the test database first.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

TABLES = ["dispense", "dispense_attempt", "patient_medicine_lock", "formulary_rule", "medicine"]


def _ensure_database() -> None:
    from sqlalchemy import create_engine, text

    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_database() -> None:
    from alembic import command
    from alembic.config import Config

    _ensure_database()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine(migrated_database: None):
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DATABASE_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_tables(engine) -> None:
    """Requested by every database fixture below, so each test starts from empty tables."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session_factory(engine, clean_tables):
    """Concurrency tests need their own sessions, each on its own connection."""
    from sqlalchemy.orm import Session, sessionmaker

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def client(engine, clean_tables):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
