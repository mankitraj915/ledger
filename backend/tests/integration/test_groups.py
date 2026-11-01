from fastapi.testclient import TestClient

from tests.helpers import Api


class TestCreateAndRead:
    def test_creator_becomes_a_member_with_zero_balance(self, client: TestClient, api: Api) -> None:
        owner = api.register("Ada")
        response = client.post(
            "/api/groups", json={"name": "  Lisbon  ", "currency": "eur"}, headers=owner.headers
        )
        assert response.status_code == 201
        group = response.json()
        assert (group["name"], group["currency"], group["created_by"]) == (
            "Lisbon",
            "EUR",
            owner.id,
        )

        detail = client.get(f"/api/groups/{group['id']}", headers=owner.headers).json()
        assert detail["members"] == [
            {"user_id": owner.id, "name": "Ada", "email": owner.email, "balance_cents": 0}
        ]
        assert detail["suggested_settlements"] == []

    def test_currency_defaults_to_usd(self, client: TestClient, api: Api) -> None:
        owner = api.register()
        response = client.post("/api/groups", json={"name": "Flat"}, headers=owner.headers)
        assert response.json()["currency"] == "USD"

    def test_invalid_payloads_are_rejected(self, client: TestClient, api: Api) -> None:
        owner = api.register()
        for payload in ({"name": ""}, {"name": "   "}, {"name": "x", "currency": "EURO"}, {}):
            response = client.post("/api/groups", json=payload, headers=owner.headers)
            assert response.status_code == 422, payload

    def test_requires_authentication(self, client: TestClient) -> None:
        assert client.post("/api/groups", json={"name": "x"}).status_code == 401
        assert client.get("/api/groups").status_code == 401

    def test_list_shows_only_my_groups_with_my_balance(self, client: TestClient, api: Api) -> None:
        ada, bob, eve = api.register(), api.register(), api.register()
        shared = api.create_group(ada, bob, name="Shared")
        api.create_group(eve, name="Eve only")

        listed = client.get("/api/groups", headers=bob.headers).json()
        assert [(g["id"], g["member_count"], g["my_balance_cents"]) for g in listed] == [
            (shared, 2, 0)
        ]


class TestAccessControl:
    def test_non_member_gets_404_not_403(self, client: TestClient, api: Api) -> None:
        owner, outsider = api.register(), api.register()
        group_id = api.create_group(owner)
        for method, path in (
            ("GET", f"/api/groups/{group_id}"),
            ("PATCH", f"/api/groups/{group_id}"),
            ("DELETE", f"/api/groups/{group_id}"),
            ("GET", f"/api/groups/{group_id}/expenses"),
            ("GET", f"/api/groups/{group_id}/settlements"),
        ):
            response = client.request(
                method, path, json={"name": "hijack"}, headers=outsider.headers
            )
            assert response.status_code == 404, (method, path)
            assert response.json()["error"]["code"] == "not_found"

    def test_missing_group_and_foreign_group_look_identical(
        self, client: TestClient, api: Api
    ) -> None:
        owner, outsider = api.register(), api.register()
        group_id = api.create_group(owner)
        foreign = client.get(f"/api/groups/{group_id}", headers=outsider.headers)
        missing = client.get("/api/groups/999999", headers=outsider.headers)
        assert foreign.json() == missing.json()


class TestMembers:
    def test_add_member_by_email(self, client: TestClient, api: Api) -> None:
        owner, friend = api.register(), api.register("Bob")
        group_id = api.create_group(owner)
        response = api.add_member(owner, group_id, friend.email.upper())
        assert response.status_code == 201
        assert response.json() == {
            "user_id": friend.id,
            "name": "Bob",
            "email": friend.email,
            "balance_cents": 0,
        }
        assert client.get(f"/api/groups/{group_id}", headers=friend.headers).status_code == 200

    def test_adding_twice_is_a_conflict(self, api: Api) -> None:
        owner, friend = api.register(), api.register()
        group_id = api.create_group(owner, friend)
        response = api.add_member(owner, group_id, friend.email)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_member"

    def test_unknown_email_is_404(self, api: Api) -> None:
        owner = api.register()
        group_id = api.create_group(owner)
        response = api.add_member(owner, group_id, "ghost@example.com")
        assert response.status_code == 404

    def test_non_member_cannot_add_members(self, api: Api) -> None:
        owner, outsider = api.register(), api.register()
        group_id = api.create_group(owner)
        assert api.add_member(outsider, group_id, outsider.email).status_code == 404


class TestRenameAndDelete:
    def test_member_can_rename(self, client: TestClient, api: Api) -> None:
        owner, friend = api.register(), api.register()
        group_id = api.create_group(owner, friend)
        response = client.patch(
            f"/api/groups/{group_id}", json={"name": "Renamed"}, headers=friend.headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"

    def test_creator_can_delete_settled_group(self, client: TestClient, api: Api) -> None:
        owner = api.register()
        group_id = api.create_group(owner)
        response = client.delete(f"/api/groups/{group_id}", headers=owner.headers)
        assert response.status_code == 204
        assert response.content == b""
        assert client.get(f"/api/groups/{group_id}", headers=owner.headers).status_code == 404

    def test_only_creator_can_delete(self, client: TestClient, api: Api) -> None:
        owner, friend = api.register(), api.register()
        group_id = api.create_group(owner, friend)
        response = client.delete(f"/api/groups/{group_id}", headers=friend.headers)
        assert response.status_code == 403
