"""`python -m app.ledger.audit`: an operations command that needs only DATABASE_URL."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.ledger import audit
from tests.concurrency.support import World


@pytest.fixture
def audit_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    # The audit must not depend on unrelated secrets such as the JWT signing key.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)


@pytest.mark.usefixtures("audit_env")
def test_consistent_ledger_exits_zero(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    world = World(session_factory, "ada", "bob")
    world.expense("ada", 200, "ada", "bob")
    assert audit.main() == 0
    assert "audited 1 groups, 0 inconsistent" in capsys.readouterr().out


@pytest.mark.usefixtures("audit_env")
def test_balances_that_disagree_with_the_journal_exit_one(
    session_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    world = World(session_factory, "ada", "bob")
    world.expense("ada", 200, "ada", "bob")
    # Still sums to zero, so the trigger allows it, but it no longer matches history.
    with session_factory.begin() as session:
        session.execute(text("UPDATE memberships SET balance_cents = 0"))
    assert audit.main() == 1
    assert "1 inconsistent" in capsys.readouterr().out


def test_missing_database_url_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert audit.main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err
