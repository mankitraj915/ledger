"""lock_balances must return the balance as of the lock, never a value cached earlier.

SQLAlchemy's identity map hands back an already-loaded object for a row instead of
the freshly SELECTed values. If the request holds a Membership from before the lock
(for example from an authorisation check) and another transaction commits a change
to it meanwhile, a plain `SELECT ... FOR UPDATE` would lock the new row version but
return the old balance. This test holds such a reference on purpose.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.groups.service import require_membership
from app.ledger.store import lock_balances
from tests.concurrency.support import World

pytestmark = pytest.mark.concurrency


def test_locked_read_overwrites_a_stale_object_held_by_the_session(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    world = World(session_factory, "ada", "bob")
    world.expense("ada", 200, "ada", "bob")
    ada, bob = world.ids["ada"], world.ids["bob"]

    with session_factory() as session:
        held = require_membership(session, world.group_id, bob)  # strong reference
        assert held.balance_cents == -100

        # Another transaction settles Bob's debt and commits.
        with engine.begin() as other:
            other.execute(
                text(
                    "UPDATE memberships SET balance_cents = 0 "
                    "WHERE group_id = :g AND user_id IN (:a, :b)"
                ),
                {"g": world.group_id, "a": ada, "b": bob},
            )

        locked = lock_balances(session, world.group_id, {ada, bob})
        assert locked[bob] is held  # the same identity-mapped object...
        assert locked[bob].balance_cents == 0  # ...refreshed with the post-lock value
