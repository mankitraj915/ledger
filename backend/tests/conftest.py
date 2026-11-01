"""Shared fixtures. Integration and concurrency tests need a real, disposable Postgres.

Set TEST_DATABASE_URL to a database the suite may wipe, e.g.
    postgresql://ledger:ledger@localhost:5432/ledger_test
The schema is built by running the real Alembic migrations (including the zero-sum
trigger), never by metadata.create_all, so tests exercise exactly what production runs.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, normalize_database_url
from app.db import build_engine, build_session_factory
from app.main import create_app
from tests.helpers import Api

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TABLES = ("settlements", "splits", "expenses", "memberships", "groups", "users")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to a disposable Postgres database to run this test")
    return normalize_database_url(url)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = build_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    # Wipe before (not after) each test, so a failing test leaves its data to inspect.
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    return build_session_factory(engine)


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        jwt_secret="test-signing-key-that-is-at-least-32-bytes",
        log_level="WARNING",
        # Argon2 at its minimum cost: hashing strength is not what these tests measure.
        password_hash_time_cost=1,
        password_hash_memory_kib=8,
    )


@pytest.fixture
def app(settings: Settings, session_factory: sessionmaker[Session]) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)
