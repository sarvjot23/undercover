import json

import pytest

from agent import steps
from context import server


@pytest.mark.parametrize(
    ("name", "args", "looked_up", "file"),
    [
        ("lookup_term", {"term": "Carrier"}, "The term “Carrier”", "glossary.yaml"),
        (
            "describe_fields",
            {"record": "previous_claim"},
            "What the fields of a previous claim mean",
            "data_dictionary.yaml",
        ),
        ("get_plan", {"plan": "premium"}, "The premium plan", "plans.yaml"),
        ("get_claim_rules", {}, "The claim rules", "claim_rules.yaml"),
        (
            "search_reference_data",
            {"query": "storm"},
            "Outside facts on “storm”",
            "reference_data.yaml",
        ),
        (
            "read_section",
            {"document": "policy_wording", "number": 3},
            "Policy wording · 3. Trip Delay",
            "policy_wording.md",
        ),
    ],
)
def test_each_lookup_says_what_and_where_from(name, args, looked_up, file):
    answer = json.dumps(getattr(server, name)(**args))
    kind, text, detail = steps.describe(name, name, args, answer)
    assert (kind, text) == ("lookup", looked_up)
    assert detail == {
        "looked_up": looked_up,
        "files": [{"file": file, **json.loads(answer)["source"]}],
    }


def test_a_document_search_names_each_file_once():
    answer = json.dumps(server.search_documents("receipts"))
    _, _, detail = steps.describe(
        "search_documents", "x", {"query": "receipts"}, answer
    )
    assert detail
    files = [entry["file"] for entry in detail["files"]]
    assert sorted(files) == ["claims_manual.md", "policy_wording.md"]


def test_a_search_that_finds_nothing_names_no_file():
    answer = json.dumps(server.search_documents("zeppelin"))
    _, _, detail = steps.describe(
        "search_documents", "x", {"query": "zeppelin"}, answer
    )
    assert detail
    assert detail["files"] == []


def test_a_refusal_says_who_refused():
    refused = "Refused by the Gateway: Tool Execution Denied"
    kind, text, detail = steps.describe(
        "get_plan", "undercover-context___get_plan", {}, refused
    )
    assert kind == "refusal"
    assert text == f"undercover-context___get_plan: {refused}"
    assert detail == {"by": "the Gateway"}


def test_any_other_result_is_a_plain_result():
    assert steps.describe("get_claim", "get_claim", {}, "{}") == (
        "tool_result",
        "get_claim: {}",
        None,
    )
