import json
import subprocess
import sys
from typing import Any

from fastapi import FastAPI
from mangum import Mangum
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool, QueuePool

from backend import db, static
from backend.main import handler

LAMBDA_URL = "abc123.lambda-url.us-east-1.on.aws"
SUPABASE = "postgresql://user:secret@pooler.supabase.test:6543/postgres"
# Mangum only passes the context on to the app; the tests need none.
CONTEXT: Any = {}


def event(path: str) -> dict:
    """A request as a Lambda Function URL delivers it (payload version 2.0)."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": LAMBDA_URL},
        "requestContext": {
            "accountId": "anonymous",
            "apiId": "abc123",
            "domainName": LAMBDA_URL,
            "http": {
                "method": "GET",
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.1",
                "userAgent": "test",
            },
            "requestId": "request-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "07/Nov/2026:12:00:00 +0000",
            "timeEpoch": 0,
        },
        "isBase64Encoded": False,
    }


def test_the_lambda_handler_answers_a_function_url_request():
    response = handler(event("/api/health"), CONTEXT)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_the_dashboards_build_is_served_beside_the_api(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>UnderCover</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('dashboard')")
    app = FastAPI()

    @app.get("/api/health", operation_id="health")
    def health() -> dict[str, str]:
        """Check that the backend is running."""
        return {"status": "ok"}

    static.serve_dashboard(app, tmp_path)
    serve = Mangum(app, lifespan="off")
    for page in ("/", "/scoreboard/4"):
        response = serve(event(page), CONTEXT)
        assert response["statusCode"] == 200
        assert "<title>UnderCover</title>" in response["body"]
    script = serve(event("/assets/app.js"), CONTEXT)
    assert "console.log('dashboard')" in script["body"]
    unknown = serve(event("/api/nope"), CONTEXT)
    assert unknown["statusCode"] == 404
    assert json.loads(unknown["body"]) == {"detail": "Not Found"}
    assert serve(event("/api/health"), CONTEXT)["statusCode"] == 200


def test_without_a_build_only_the_api_is_served(tmp_path):
    app = FastAPI()
    static.serve_dashboard(app, tmp_path)
    assert Mangum(app, lifespan="off")(event("/"), CONTEXT)["statusCode"] == 404


def made_with(monkeypatch) -> dict:
    """The arguments the engine is made with, on a stand-in for Supabase."""
    made = {}

    def spy(url, **kwargs):
        made.update(kwargs, url=url)
        return create_engine("sqlite://")

    monkeypatch.setattr(db, "create_engine", spy)
    db.postgres_engine(SUPABASE)
    return made


def test_on_lambda_a_connection_is_opened_for_each_request(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "undercover-app")
    made = made_with(monkeypatch)
    assert made["poolclass"] is NullPool
    assert made["connect_args"]["prepare_threshold"] is None
    assert ":6543/" in made["url"]


def test_off_lambda_the_pool_of_four_stays(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    made = made_with(monkeypatch)
    assert made.get("poolclass", QueuePool) is QueuePool
    assert made["pool_size"] == db.MAX_CONNECTIONS == 4


def test_the_deployed_app_imports_nothing_from_the_agent():
    code = (
        "import sys, backend.main; "
        "print([m for m in sys.modules if m.split('.')[0] == 'agent'])"
    )
    found = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert found.stdout.strip() == "[]"
