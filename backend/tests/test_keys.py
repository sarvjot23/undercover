import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend import auth, keys
from backend.api import app
from backend.tests.signing import AGENT_KEY, as_agent, as_handler

START = "/api/claims/CLM-1001/start"
THREAD = {"thread_id": "CLM-1001-test"}
WRONG_KEY = {"X-API-Key": "not-the-key-0123456789abcdefghijklmn"}


@pytest.mark.usefixtures("client")
def test_an_agent_route_needs_the_right_key():
    bare = TestClient(app)
    assert bare.post(START, json=THREAD).status_code == 401
    assert bare.post(START, json=THREAD, headers=WRONG_KEY).status_code == 401
    assert bare.post(START, json=THREAD, headers=as_agent()).status_code == 200


@pytest.mark.usefixtures("client")
def test_a_handler_cant_use_an_agent_route():
    bare = TestClient(app)
    assert bare.post(START, json=THREAD, headers=as_handler()).status_code == 401


@pytest.mark.usefixtures("client")
def test_a_shared_read_takes_the_key_or_a_handler():
    bare = TestClient(app)
    claim = "/api/claims/CLM-1001"
    assert bare.get(claim, headers=as_agent()).status_code == 200
    assert bare.get(claim, headers=as_handler()).status_code == 200
    assert bare.get(claim).status_code == 401
    assert (
        bare.get(claim, headers={"Authorization": "Bearer nonsense"}).status_code == 401
    )


@pytest.mark.usefixtures("client")
def test_the_key_never_stands_in_for_a_handler():
    bare = TestClient(app, headers=as_agent())
    assert bare.post("/api/claims/CLM-1001/sign-off").status_code == 401
    assert bare.post("/api/dispatches", json={"n": 3}).status_code == 401
    assert bare.get("/api/handlers").status_code == 401


@pytest.mark.usefixtures("client")
def test_without_a_key_set_handlers_carry_on_and_the_agent_is_refused(monkeypatch):
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    bare = TestClient(app)
    assert bare.get("/api/claims", headers=as_handler()).status_code == 200
    assert bare.get("/api/handlers", headers=as_handler()).status_code == 200
    assert bare.post(START, json=THREAD, headers=as_agent()).status_code == 401
    assert bare.post(START, json=THREAD, headers={"X-API-Key": ""}).status_code == 401
    assert bare.get("/api/claims", headers=as_agent()).status_code == 401


def test_health_is_open():
    assert TestClient(app).get("/api/health").status_code == 200


@pytest.mark.usefixtures("client")
def test_the_key_is_compared_in_constant_time(monkeypatch):
    compared = []

    def compare(sent, expected):
        compared.append((sent, expected))
        return sent == expected

    monkeypatch.setattr(keys.secrets, "compare_digest", compare)
    TestClient(app).post(START, json=THREAD, headers=as_agent())
    assert compared == [(AGENT_KEY.encode(), AGENT_KEY.encode())]


def rules_of(route: APIRoute) -> set[str]:
    """Which of the access rules a route's dependencies apply."""
    named = {keys.agent_key: "agent", keys.reader: "read", auth.signed_in: "handler"}
    found = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if dependency.call in named:
            found.add(named[dependency.call])
        stack.extend(dependency.dependencies)
    return found


def test_every_route_has_exactly_one_rule():
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    open_routes = [route.path for route in routes if not rules_of(route)]
    assert open_routes == ["/api/health"]
    assert all(len(rules_of(route)) <= 1 for route in routes)
