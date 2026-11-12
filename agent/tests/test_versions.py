import inspect

from fastapi.testclient import TestClient

from agent import claim, client, dispatcher, graph, tools
from agent.tests.stubs import call, script
from backend import db
from backend.api import app
from backend.tests.signing import as_agent

# What only the scoreboard, the rounds and the improver may read.
NEVER = ("/api/evaluations", "/api/rounds", "scores", "handler_decisions", "/view")


def add_version():
    with db.engine().begin() as conn:
        conn.execute(
            db.config_versions.insert().values(
                version=2,
                instructions="Version 2's instructions.",
                model="google/gemini-3.5-flash-lite",
                reasoning="minimal",
                reason="A test.",
                proposed_by="improver",
                approved_by="HND-01",
                approved_at=db.now(),
                current=False,
            )
        )


def test_the_claim_agent_is_built_from_its_runs_version(requests, monkeypatch):
    add_version()
    built = []
    original = graph.build

    def spy(make_llm, instructions, saver, claim):
        built.append(instructions)
        return original(make_llm, instructions, saver, claim)

    monkeypatch.setattr(graph, "build", spy)
    models = []

    def model(name, reasoning):
        models.append((name, reasoning))
        return script(
            call(
                "record_decision",
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        )

    monkeypatch.setattr(claim, "model", model)
    monkeypatch.setattr(dispatcher, "FIRST_WAIT", 0.0)
    created = (
        TestClient(app, headers=as_agent())
        .post(
            "/api/runs",
            json={
                "kind": "evaluation",
                "n": 1,
                "set_name": "evaluation",
                "tiny": True,
                "version": 2,
                "round_id": None,
            },
        )
        .json()
    )
    claim_id = created["claims"][0]["claim_id"]
    claim.work(
        claim_id,
        {
            "run_id": created["run_id"],
            "kind": "evaluation",
            "version": 2,
            "round_id": None,
        },
    )
    assert built == ["Version 2's instructions."]
    assert models == [("google/gemini-3.5-flash-lite", "minimal")]
    assert "/api/configuration/versions/2" in requests


def test_outside_a_run_the_claim_agent_uses_the_current_version(requests):
    claim.run(
        "CLM-1001",
        "CLM-1001-t",
        script(
            call(
                "record_decision",
                decision="refer",
                payout=0,
                reasons="Needs a handler. The manual says so.",
                policy_section="Claims manual 2.",
            )
        ),
    )
    assert "/api/configuration/current" in requests


def test_the_claim_agents_client_and_tools_never_reach_the_scores():
    for module in (client, tools, graph, claim):
        source = inspect.getsource(module)
        for word in NEVER:
            assert word not in source, f"{module.__name__} names {word}"
