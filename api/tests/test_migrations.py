"""Every migration must downgrade cleanly, and 0002 must move data both ways.

These run against their own database so they can walk the whole chain without
disturbing the schema the other tests rely on.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://formulary:formulary@db:5432/formulary_test")
MIGRATION_DB_URL = BASE_URL.rsplit("/", 1)[0] + "/formulary_migrations"


@pytest.fixture
def migration_engine():
    admin = create_engine(BASE_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS formulary_migrations WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE formulary_migrations"))
    admin.dispose()

    engine = create_engine(MIGRATION_DB_URL, future=True)
    yield engine
    engine.dispose()


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", MIGRATION_DB_URL)
    return config


def test_every_migration_downgrades_and_upgrades_again(migration_engine):
    config = alembic_config()

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    with migration_engine.connect() as conn:
        tables = set(
            conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).all()
        )
    assert {"medicine", "formulary_rule", "dispense", "dispense_attempt"} <= tables


def test_0002_moves_strength_data_in_both_directions(migration_engine):
    config = alembic_config()
    command.upgrade(config, "0001")

    with migration_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO medicine (code, name, form, strength) VALUES"
                " ('M1', 'Testazole', 'tablet', '500 mg'),"
                " ('M2', 'Otherazole', 'suspension', '12.5 mg/ml')"
            )
        )

    command.upgrade(config, "0002")
    with migration_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT code, strength_value || '|' || strength_unit FROM medicine")).all())
    assert rows == {"M1": "500.000|mg", "M2": "12.500|mg/ml"}

    command.downgrade(config, "0001")
    with migration_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT code, strength FROM medicine")).all())
    assert rows == {"M1": "500 mg", "M2": "12.5 mg/ml"}
