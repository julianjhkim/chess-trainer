"""The names I play under, edited from the top bar."""

from __future__ import annotations


def test_the_list_starts_from_the_configured_name(client):
    assert client.get("/api/me").json() == {"usernames": ["test-player"]}


def test_the_list_can_be_replaced(client):
    payload = client.put("/api/me", json={"usernames": ["test-player", " second-account "]}).json()
    assert payload == {"usernames": ["test-player", "second-account"]}
    assert client.get("/api/me").json() == payload


def test_too_many_or_too_long_names_are_refused(client):
    assert client.put("/api/me", json={"usernames": ["x"] * 21}).status_code == 422
    assert client.put("/api/me", json={"usernames": ["x" * 51]}).status_code == 422
