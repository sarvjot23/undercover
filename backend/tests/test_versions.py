from sqlalchemy import select

from backend import allowed, db, diffs, versions
from backend.tests.signing import as_handler

RUN = {"n": 3, "tiny": False, "round_id": None}


def add_version(instructions="Decide carefully.", model="google/gemini-3.5-flash-lite"):
    with db.engine().begin() as conn:
        conn.execute(
            db.config_versions.insert().values(
                version=2,
                instructions=instructions,
                model=model,
                reasoning="minimal",
                reason="A test.",
                proposed_by="improver",
                approved_by="HND-01",
                approved_at=db.now(),
                current=False,
            )
        )


def evaluate(client, set_name="evaluation", **record):
    body = {**RUN, "kind": "evaluation", "set_name": set_name, "version": None}
    run = client.post("/api/runs", json={**body, **record}).json()
    client.post(f"/api/runs/{run['run_id']}/finish")
    return run


def test_a_dispatch_and_an_evaluation_record_the_version_they_use(client):
    add_version()
    dispatch = {**RUN, "kind": "dispatch", "set_name": None, "version": None}
    created = client.post("/api/runs", json=dispatch).json()
    assert (created["version"], created["model"]) == (1, "openai/gpt-6-luna")
    assert created["reasoning"] == "low"
    client.post(f"/api/runs/{created['run_id']}/finish")

    tried = evaluate(client, version=2, round_id=1)
    assert tried["version"] == 2
    assert (tried["model"], tried["reasoning"]) == (
        "google/gemini-3.5-flash-lite",
        "minimal",
    )
    assert tried["round_id"] == 1


def test_a_run_on_a_version_that_doesnt_exist_is_refused(client):
    refused = client.post(
        "/api/runs",
        json={**RUN, "kind": "dispatch", "set_name": None, "version": 9},
    )
    assert refused.status_code == 404


def test_the_claim_agents_version_holds_no_score(client):
    found = client.get("/api/configuration/versions/1").json()
    assert set(found) == {"version", "instructions", "model", "reasoning"}
    assert client.get("/api/configuration/versions/9").status_code == 404


def test_a_versions_scores_count_only_the_whole_set_evaluations_of_rounds(client):
    counted = evaluate(client, round_id=1)
    evaluate(client, round_id=1, tiny=True)
    evaluate(client)
    evaluate(client, "held_out", round_id=1)
    evaluate(client, "held_out", round_id=1)
    listed = client.get("/api/configuration/versions", headers=as_handler()).json()
    scores = listed[0]["scores"]
    assert scores["evaluation"]["runs"] == 1
    assert scores["held_out"]["runs"] == 2
    own = client.get(
        f"/api/evaluations/{counted['run_id']}", headers=as_handler()
    ).json()["scores"]
    assert scores["evaluation"]["accuracy"] == own["accuracy"]
    assert listed[0]["changed"] == []


def test_a_stopped_or_unfinished_evaluation_doesnt_count(client):
    body = {**RUN, "kind": "evaluation", "set_name": "evaluation", "version": None}
    run = client.post("/api/runs", json={**body, "round_id": 1}).json()
    client.post(f"/api/runs/{run['run_id']}/stop")
    with db.engine().connect() as conn:
        assert versions.scores(conn, 1) == {"evaluation": None, "held_out": None}


def test_versions_are_listed_newest_first_with_what_they_changed(client):
    add_version()
    listed = client.get("/api/configuration/versions", headers=as_handler()).json()
    assert [entry["version"] for entry in listed] == [2, 1]
    assert listed[0]["changed"] == ["instructions", "model", "reasoning effort"]
    assert listed[1]["proposed_by"] == "seed"
    assert listed[1]["current"] is True


def test_the_diff_of_two_versions():
    old = "Line one.\nLine two.\nLine three.\n"
    new = "Line one.\nLine 2.\nLine three.\nLine four.\n"
    assert diffs.lines(old, new) == [
        {"kind": "same", "text": "Line one."},
        {"kind": "remove", "text": "Line two."},
        {"kind": "add", "text": "Line 2."},
        {"kind": "same", "text": "Line three."},
        {"kind": "add", "text": "Line four."},
    ]


def test_distant_changes_are_split_by_a_gap():
    old = "\n".join(f"Line {n}." for n in range(20))
    new = old.replace("Line 1.", "First.").replace("Line 18.", "Last.")
    kinds = [line["kind"] for line in diffs.lines(old, new)]
    assert kinds.count("gap") == 1
    assert kinds.count("add") == kinds.count("remove") == 2


def test_a_version_is_shown_against_the_one_before(client):
    add_version(instructions="Decide carefully.\nRefer when unsure.")
    diff = client.get("/api/configuration/versions/2/diff", headers=as_handler()).json()
    assert diff["before"] == 1
    assert {"kind": "add", "text": "Refer when unsure."} in diff["instructions"]
    assert diff["model"] == ["openai/gpt-6-luna", "google/gemini-3.5-flash-lite"]
    assert diff["reasoning"] == ["low", "minimal"]
    first = client.get(
        "/api/configuration/versions/1/diff", headers=as_handler()
    ).json()
    assert first["before"] is None
    assert {line["kind"] for line in first["instructions"]} == {"add"}


def test_the_recipe_starts_as_the_labs(client):
    recipes = client.get("/api/recipes", headers=as_handler()).json()
    assert [recipe["version"] for recipe in recipes] == [1]
    assert recipes[0]["recipe"].startswith("1. Call read_results")
    assert "propose_recipe" in recipes[0]["recipe"]
    diff = client.get("/api/recipes/1/diff", headers=as_handler()).json()
    assert diff["before"] is None
    assert client.get("/api/recipes/2/diff", headers=as_handler()).status_code == 404


def test_the_models_allowed_are_the_labs_three(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    names = [model["model"] for model in allowed.models()]
    assert names == [
        "openai/gpt-6-luna",
        "google/gemini-3.5-flash-lite",
        "deepseek/deepseek-v4.1-flash",
    ]
    assert allowed.refusal("openai/gpt-6-luna", "medium") is None
    assert "isn't one of the models allowed" in str(
        allowed.refusal("anthropic/claude", "low")
    )
    assert "not high" in str(allowed.refusal("openai/gpt-6-luna", "high"))


def test_with_model_name_set_that_model_is_the_only_one_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "free.db"))
    assert allowed.models() == [
        {
            "model": "openrouter/free",
            "reasoning_efforts": ["default"],
            "input_price": 0.0,
            "output_price": 0.0,
        }
    ]
    assert allowed.refusal("openai/gpt-6-luna", "low") is not None
    db.init()
    with db.engine().connect() as conn:
        first = conn.execute(select(db.config_versions)).mappings().one()
    assert (first["model"], first["reasoning"]) == ("openrouter/free", "default")


def test_each_removed_line_sits_above_the_line_that_replaced_it():
    old = "Intro.\n1. Read.\n2. Think.\n3. Act.\nEnd."
    new = "Intro.\n1. Read it all.\n2. Think hard.\n3. Act.\nEnd."
    assert [(line["kind"], line["text"]) for line in diffs.lines(old, new)] == [
        ("same", "Intro."),
        ("remove", "1. Read."),
        ("add", "1. Read it all."),
        ("remove", "2. Think."),
        ("add", "2. Think hard."),
        ("same", "3. Act."),
        ("same", "End."),
    ]
