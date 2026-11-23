import re

import pytest

from app import create_app
from app.blueprints import hooks
from app.config import TestConfig

OK = {"name": "Ada", "email": "ada@example.com", "nationality": "Irish"}


@pytest.fixture()
def client():
    hooks._counters.clear()
    app = create_app(type("Cfg", (TestConfig,), {"WTF_CSRF_ENABLED": True}))  # CSRF on: hook must still work
    return app.test_client()


def test_valid_request_returns_reference(client):
    r = client.post("/hooks/signup", json=OK)
    assert r.status_code == 200
    assert re.fullmatch(r"CB-\d{8}-0001", r.get_json()["reference"])


def test_references_increment(client):
    client.post("/hooks/signup", json=OK)
    assert client.post("/hooks/signup", json=OK).get_json()["reference"].endswith("-0002")


@pytest.mark.parametrize("body", [
    {}, {**OK, "name": ""}, {**OK, "nationality": "  "}, {"name": "A", "email": "a@b.co"},
    {**OK, "email": "nope"}, {**OK, "email": "a@b"}, {**OK, "email": "a b@c.de"}, {**OK, "name": 5}, [1, 2],
])
def test_invalid_bodies_return_400_json(client, body):
    r = client.post("/hooks/signup", json=body)
    assert r.status_code == 400 and "error" in r.get_json()


def test_non_json_and_malformed_json_return_400(client):
    assert client.post("/hooks/signup", data="x", content_type="text/plain").status_code == 400
    assert client.post("/hooks/signup", data="{bad", content_type="application/json").status_code == 400


def test_get_not_allowed(client):
    assert client.get("/hooks/signup").status_code == 405


def test_counter_exhaustion_returns_503(client):
    from datetime import datetime, timezone
    hooks._counters[datetime.now(timezone.utc).strftime("%Y%m%d")] = 9999
    assert client.post("/hooks/signup", json=OK).status_code == 503
