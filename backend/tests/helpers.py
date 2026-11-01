"""A thin client for driving the HTTP API in tests."""

import itertools
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

_emails = itertools.count(1)
PASSWORD = "correct horse battery"


@dataclass(frozen=True)
class Member:
    id: int
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def equal(*user_ids: int) -> dict[str, Any]:
    return {"method": "equal", "participants": list(user_ids)}


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def register(self, name: str = "Member") -> Member:
        email = f"user{next(_emails)}@example.com"
        response = self.client.post(
            "/api/auth/register", json={"email": email, "name": name, "password": PASSWORD}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return Member(id=body["user"]["id"], email=email, token=body["access_token"])

    def create_group(self, owner: Member, *members: Member, name: str = "Trip") -> int:
        response = self.client.post("/api/groups", json={"name": name}, headers=owner.headers)
        assert response.status_code == 201, response.text
        group_id: int = response.json()["id"]
        for member in members:
            added = self.add_member(owner, group_id, member.email)
            assert added.status_code == 201, added.text
        return group_id

    def add_member(self, actor: Member, group_id: int, email: str) -> Response:
        return self.client.post(
            f"/api/groups/{group_id}/members", json={"email": email}, headers=actor.headers
        )

    def add_expense(
        self,
        actor: Member,
        group_id: int,
        *,
        paid_by: int,
        amount_cents: int,
        split: dict[str, Any],
        description: str = "Dinner",
    ) -> Response:
        return self.client.post(
            f"/api/groups/{group_id}/expenses",
            json={
                "description": description,
                "amount_cents": amount_cents,
                "paid_by": paid_by,
                "split": split,
            },
            headers=actor.headers,
        )

    def settle(
        self,
        actor: Member,
        group_id: int,
        *,
        payer_id: int,
        payee_id: int,
        amount_cents: int,
        key: str | None = None,
    ) -> Response:
        headers = {**actor.headers, "Idempotency-Key": key or str(uuid.uuid4())}
        return self.client.post(
            f"/api/groups/{group_id}/settlements",
            json={"payer_id": payer_id, "payee_id": payee_id, "amount_cents": amount_cents},
            headers=headers,
        )

    def balances(self, actor: Member, group_id: int) -> dict[int, int]:
        response = self.client.get(f"/api/groups/{group_id}", headers=actor.headers)
        assert response.status_code == 200, response.text
        return {m["user_id"]: m["balance_cents"] for m in response.json()["members"]}
