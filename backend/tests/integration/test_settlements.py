import pytest
from fastapi.testclient import TestClient

from tests.helpers import Api, Member, equal


@pytest.fixture
def debt(api: Api) -> tuple[Member, Member, int]:
    """Ada paid 1000 for herself and Bob: Bob owes Ada 500."""
    ada, bob = api.register("Ada"), api.register("Bob")
    group_id = api.create_group(ada, bob)
    response = api.add_expense(
        ada, group_id, paid_by=ada.id, amount_cents=1000, split=equal(ada.id, bob.id)
    )
    assert response.status_code == 201
    return ada, bob, group_id


class TestSettleUp:
    def test_full_settlement_zeroes_balances(
        self, client: TestClient, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        response = api.settle(bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=500)
        assert response.status_code == 201
        assert "Idempotent-Replayed" not in response.headers
        settlement = response.json()
        assert (settlement["payer_id"], settlement["payee_id"], settlement["amount_cents"]) == (
            bob.id,
            ada.id,
            500,
        )
        detail = client.get(f"/api/groups/{group_id}", headers=ada.headers).json()
        assert {m["balance_cents"] for m in detail["members"]} == {0}
        assert detail["suggested_settlements"] == []

    def test_payee_can_record_it_too(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        ada, bob, group_id = debt
        response = api.settle(ada, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=200)
        assert response.status_code == 201
        assert api.balances(ada, group_id) == {ada.id: 300, bob.id: -300}

    def test_overdraw_is_rejected_and_changes_nothing(
        self, client: TestClient, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        response = api.settle(bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=501)
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "settlement_exceeds_balance",
            "message": "Settlement of 501 cents exceeds the 500 cents outstanding",
            "details": {"max_amount_cents": 500},
        }
        assert api.balances(ada, group_id) == {ada.id: 500, bob.id: -500}
        assert client.get(f"/api/groups/{group_id}/settlements", headers=ada.headers).json() == []

    def test_creditor_cannot_pay_debtor(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        ada, bob, group_id = debt
        response = api.settle(ada, group_id, payer_id=ada.id, payee_id=bob.id, amount_cents=100)
        assert response.status_code == 409

    def test_third_party_cannot_record(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        ada, bob, group_id = debt
        cy = api.register()
        assert api.add_member(ada, group_id, cy.email).status_code == 201
        response = api.settle(cy, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=100)
        assert response.status_code == 403

    def test_parties_must_be_members(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        _, bob, group_id = debt
        outsider = api.register()
        response = api.settle(bob, group_id, payer_id=bob.id, payee_id=outsider.id, amount_cents=1)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "not_group_member"

    def test_non_member_gets_404(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        ada, _, group_id = debt
        outsider = api.register()
        response = api.settle(
            outsider, group_id, payer_id=outsider.id, payee_id=ada.id, amount_cents=1
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("amount", [0, -1])
    def test_non_positive_amount_is_422(
        self, api: Api, debt: tuple[Member, Member, int], amount: int
    ) -> None:
        ada, bob, group_id = debt
        response = api.settle(bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=amount)
        assert response.status_code == 422

    def test_self_settlement_is_422(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        _, bob, group_id = debt
        response = api.settle(bob, group_id, payer_id=bob.id, payee_id=bob.id, amount_cents=1)
        assert response.status_code == 422


class TestIdempotency:
    def test_key_is_required(self, client: TestClient, debt: tuple[Member, Member, int]) -> None:
        ada, bob, group_id = debt
        response = client.post(
            f"/api/groups/{group_id}/settlements",
            json={"payer_id": bob.id, "payee_id": ada.id, "amount_cents": 100},
            headers=bob.headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "idempotency_key_required"

    def test_resubmission_replays_without_applying_twice(
        self, client: TestClient, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        first = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=300, key="k-1"
        )
        second = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=300, key="k-1"
        )
        assert (first.status_code, second.status_code) == (201, 200)
        assert second.headers["Idempotent-Replayed"] == "true"
        assert second.json() == first.json()
        assert api.balances(ada, group_id) == {ada.id: 200, bob.id: -200}
        listed = client.get(f"/api/groups/{group_id}/settlements", headers=ada.headers).json()
        assert [s["id"] for s in listed] == [first.json()["id"]]

    def test_replay_succeeds_even_when_a_fresh_request_would_now_overdraw(
        self, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        api.settle(bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=500, key="all")
        retry = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=500, key="all"
        )
        assert retry.status_code == 200  # not 409: the key is checked before the balance

    def test_key_reused_for_a_different_request_is_422(
        self, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        api.settle(bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=100, key="k")
        response = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=200, key="k"
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "idempotency_key_reused"
        assert api.balances(ada, group_id)[bob.id] == -400

    def test_keys_are_scoped_per_user(self, api: Api, debt: tuple[Member, Member, int]) -> None:
        ada, bob, group_id = debt
        by_bob = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=100, key="same"
        )
        by_ada = api.settle(
            ada, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=100, key="same"
        )
        assert (by_bob.status_code, by_ada.status_code) == (201, 201)
        assert api.balances(ada, group_id)[bob.id] == -300

    def test_a_failed_attempt_does_not_burn_the_key(
        self, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        too_much = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=800, key="later"
        )
        assert too_much.status_code == 409
        # More debt arrives; the identical request with the same key now succeeds.
        api.add_expense(ada, group_id, paid_by=ada.id, amount_cents=600, split=equal(bob.id))
        retried = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=800, key="later"
        )
        assert retried.status_code == 201

    def test_key_longer_than_255_chars_is_422(
        self, api: Api, debt: tuple[Member, Member, int]
    ) -> None:
        ada, bob, group_id = debt
        response = api.settle(
            bob, group_id, payer_id=bob.id, payee_id=ada.id, amount_cents=1, key="k" * 256
        )
        assert response.status_code == 422
