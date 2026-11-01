from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.helpers import Api, Member, equal


@pytest.fixture
def trio(api: Api) -> tuple[Member, Member, Member, int]:
    ada, bob, cy = api.register("Ada"), api.register("Bob"), api.register("Cy")
    return ada, bob, cy, api.create_group(ada, bob, cy)


def put_expense(
    client: TestClient, actor: Member, group_id: int, expense_id: int, **body: Any
) -> Any:
    return client.put(
        f"/api/groups/{group_id}/expenses/{expense_id}", json=body, headers=actor.headers
    )


class TestCreateExpense:
    def test_equal_split_assigns_the_odd_cent_deterministically(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, cy, group_id = trio
        response = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=1000, split=equal(ada.id, bob.id, cy.id)
        )
        assert response.status_code == 201
        expense = response.json()
        assert expense["version"] == 1
        assert expense["split_method"] == "equal"
        assert [(s["user_id"], s["share_cents"]) for s in expense["splits"]] == [
            (ada.id, 334),
            (bob.id, 333),
            (cy.id, 333),
        ]
        assert api.balances(ada, group_id) == {ada.id: 666, bob.id: -333, cy.id: -333}

    def test_exact_split(self, api: Api, trio: tuple[Member, Member, Member, int]) -> None:
        ada, bob, cy, group_id = trio
        split = {
            "method": "exact",
            "shares": [
                {"user_id": bob.id, "amount_cents": 700},
                {"user_id": cy.id, "amount_cents": 300},
            ],
        }
        response = api.add_expense(ada, group_id, paid_by=ada.id, amount_cents=1000, split=split)
        assert response.status_code == 201
        assert api.balances(ada, group_id) == {ada.id: 1000, bob.id: -700, cy.id: -300}

    def test_shares_split_records_weights(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        split = {
            "method": "shares",
            "shares": [{"user_id": ada.id, "weight": 1}, {"user_id": bob.id, "weight": 2}],
        }
        response = api.add_expense(bob, group_id, paid_by=bob.id, amount_cents=900, split=split)
        assert response.status_code == 201
        assert [(s["share_cents"], s["weight"]) for s in response.json()["splits"]] == [
            (300, 1),
            (600, 2),
        ]

    def test_exact_amounts_must_sum_to_total(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        split = {"method": "exact", "shares": [{"user_id": bob.id, "amount_cents": 999}]}
        response = api.add_expense(ada, group_id, paid_by=ada.id, amount_cents=1000, split=split)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_split"

    @pytest.mark.parametrize("who", ["participant", "payer"])
    def test_everyone_named_must_be_a_member(
        self, api: Api, trio: tuple[Member, Member, Member, int], who: str
    ) -> None:
        ada, bob, _, group_id = trio
        outsider = api.register()
        payer, participant = (ada, outsider) if who == "participant" else (outsider, bob)
        response = api.add_expense(
            ada, group_id, paid_by=payer.id, amount_cents=500, split=equal(participant.id, ada.id)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "not_group_member"
        assert response.json()["error"]["details"] == {"user_ids": [outsider.id]}
        assert set(api.balances(ada, group_id).values()) == {0}

    def test_zero_cent_share_still_requires_membership(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, _, _, group_id = trio
        outsider = api.register()
        # 1 cent over 2 people: the outsider's share rounds to 0 but they are still named.
        response = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=1, split=equal(ada.id, outsider.id)
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("amount", "split"),
        [
            (0, None),
            (-100, None),
            (100_000_000_001, None),
            (100, {"method": "equal", "participants": []}),
            (100, {"method": "bogus", "participants": [1]}),
            (100, {"method": "shares", "shares": [{"user_id": 1, "weight": 0}]}),
        ],
    )
    def test_invalid_payloads_are_422(
        self,
        api: Api,
        trio: tuple[Member, Member, Member, int],
        amount: int,
        split: dict[str, Any] | None,
    ) -> None:
        ada, bob, _, group_id = trio
        response = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=amount, split=split or equal(bob.id)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_duplicate_participants_are_422(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        response = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=100, split=equal(bob.id, bob.id)
        )
        assert response.status_code == 422

    def test_non_member_cannot_add(
        self, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, _, _, group_id = trio
        outsider = api.register()
        response = api.add_expense(
            outsider, group_id, paid_by=ada.id, amount_cents=100, split=equal(ada.id)
        )
        assert response.status_code == 404

    def test_list_returns_newest_first_with_splits(
        self, client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        for description in ("first", "second"):
            api.add_expense(
                ada,
                group_id,
                paid_by=ada.id,
                amount_cents=200,
                split=equal(ada.id, bob.id),
                description=description,
            )
        listed = client.get(f"/api/groups/{group_id}/expenses", headers=bob.headers).json()
        assert [e["description"] for e in listed] == ["second", "first"]
        assert all(len(e["splits"]) == 2 for e in listed)


class TestEditExpense:
    def test_edit_reverses_old_split_and_applies_new_one(
        self, client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, cy, group_id = trio
        created = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=600, split=equal(ada.id, bob.id)
        ).json()
        assert api.balances(ada, group_id) == {ada.id: 300, bob.id: -300, cy.id: 0}

        response = put_expense(
            client,
            bob,
            group_id,
            created["id"],
            description="Dinner (fixed)",
            amount_cents=900,
            paid_by=cy.id,
            split=equal(ada.id, bob.id, cy.id),
            version=1,
        )
        assert response.status_code == 200
        assert response.json()["version"] == 2
        assert response.json()["paid_by"] == cy.id
        assert api.balances(ada, group_id) == {ada.id: -300, bob.id: -300, cy.id: 600}

    def test_stale_version_is_rejected_and_changes_nothing(
        self, client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        created = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=600, split=equal(ada.id, bob.id)
        ).json()
        body = {"description": "x", "paid_by": ada.id, "split": equal(ada.id, bob.id)}
        assert (
            put_expense(
                client, ada, group_id, created["id"], amount_cents=800, version=1, **body
            ).status_code
            == 200
        )
        before = api.balances(ada, group_id)

        stale = put_expense(
            client, bob, group_id, created["id"], amount_cents=100, version=1, **body
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "stale_version"
        assert stale.json()["error"]["details"] == {"current_version": 2}
        assert api.balances(ada, group_id) == before

    def test_expense_from_another_group_is_404(
        self, client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        other_group = api.create_group(ada, bob)
        created = api.add_expense(
            ada, other_group, paid_by=ada.id, amount_cents=600, split=equal(ada.id, bob.id)
        ).json()
        response = put_expense(
            client,
            ada,
            group_id,
            created["id"],
            description="x",
            amount_cents=600,
            paid_by=ada.id,
            split=equal(ada.id),
            version=1,
        )
        assert response.status_code == 404

    def test_invalid_edit_leaves_expense_untouched(
        self, client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
    ) -> None:
        ada, bob, _, group_id = trio
        outsider = api.register()
        created = api.add_expense(
            ada, group_id, paid_by=ada.id, amount_cents=600, split=equal(ada.id, bob.id)
        ).json()
        response = put_expense(
            client,
            ada,
            group_id,
            created["id"],
            description="x",
            amount_cents=600,
            paid_by=ada.id,
            split=equal(ada.id, outsider.id),
            version=1,
        )
        assert response.status_code == 422
        listed = client.get(f"/api/groups/{group_id}/expenses", headers=ada.headers).json()
        assert listed[0]["version"] == 1
        assert api.balances(ada, group_id)[ada.id] == 300


def test_group_with_outstanding_balances_cannot_be_deleted(
    client: TestClient, api: Api, trio: tuple[Member, Member, Member, int]
) -> None:
    ada, bob, _, group_id = trio
    api.add_expense(ada, group_id, paid_by=ada.id, amount_cents=600, split=equal(ada.id, bob.id))
    response = client.delete(f"/api/groups/{group_id}", headers=ada.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "group_not_settled"
    assert response.json()["error"]["details"]["outstanding"] == {
        str(ada.id): 300,
        str(bob.id): -300,
    }
