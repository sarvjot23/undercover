import asyncio
import json
from typing import Any

import pytest

from context import files, server

LAMBDA_URL = "ctx123.lambda-url.us-east-1.on.aws"
# Mangum only passes the context on to the app; the tests need none.
LAMBDA_CONTEXT: Any = {}
SOURCE_KEYS = {"system", "owner", "reviewed"}


def named(found, file):
    assert found["file"] == file
    assert found["source"].keys() == SOURCE_KEYS


def test_a_term_is_found_whatever_its_case():
    found = server.lookup_term("UNATTENDED")
    named(found, "glossary.yaml")
    assert found["term"] == "Unattended"
    assert found["sections"] == [5]
    assert found["definition"].startswith("Out of your sight")


def test_an_unknown_term_gets_the_terms_the_glossary_defines():
    found = server.lookup_term("zeppelin")
    named(found, "glossary.yaml")
    assert found["definition"] is None
    assert "Unattended" in found["defined_terms"]
    assert "Deductible" in found["defined_terms"]


@pytest.mark.parametrize("record", ["claim", "policy", "previous_claim"])
def test_each_records_fields(record):
    found = server.describe_fields(record)
    named(found, "data_dictionary.yaml")
    assert found["record"] == record
    assert {"field", "meaning"} <= found["fields"][0].keys()


def test_the_decision_record_fields_are_described():
    fields = {f["field"] for f in server.describe_fields("claim")["fields"]}
    assert {"decision.calculation", "decision.decided_by"} <= fields


@pytest.mark.parametrize(
    ("plan", "deductible"), [("economy", 100), ("premium", 50), ("first", 0)]
)
def test_each_plan(plan, deductible):
    found = server.get_plan(plan)
    named(found, "plans.yaml")
    assert found["plan"]["deductible"] == deductible
    assert found["deductible_applies_to"] == ["baggage", "emergency_medical"]
    assert [a["add_on"] for a in found["add_ons"]] == [
        "adventure_sports",
        "pre_existing_waiver",
        "electronics_plus",
    ]


def test_the_claim_rules():
    found = server.get_claim_rules()
    named(found, "claim_rules.yaml")
    rules = {rule["rule"]: rule for rule in found["rules"]}
    assert rules["filing_window"]["days"] == 90
    assert rules["repeat_claims"]["claims"] == 3


def test_reference_data_needs_every_word_in_any_case():
    found = server.search_reference_data("LISBON strike")
    named(found, "reference_data.yaml")
    assert len(found["facts"]) == 1
    assert found["facts"][0]["topic"] == "events"
    assert "Portugal" in found["facts"][0]["fact"]
    assert server.search_reference_data("Lisbon zeppelin")["facts"] == []


def test_a_document_search_names_each_sections_file():
    found = server.search_documents("giraffes")["found"]
    assert [(f["document"], f["number"]) for f in found] == [("claims_manual", 7)]
    named(found[0], "claims_manual.md")
    assert found[0]["title"] == "Interpretation notes"
    assert all("giraffe" in line.lower() for line in found[0]["lines"])
    both = server.search_documents("deductible")["found"]
    assert {f["file"] for f in both} == {"policy_wording.md", "claims_manual.md"}


def test_a_section_is_read_with_its_documents_version():
    found = server.read_section("claims_manual", 14)
    named(found, "claims_manual.md")
    assert found["version"] == "2026.2"
    assert found["title"] == "Records"
    assert found["text"].startswith("## 14. Records")


def test_a_section_that_does_not_exist():
    with pytest.raises(ValueError, match="No section 99 in the claims manual"):
        server.read_section("claims_manual", 99)


def test_the_front_matter_is_never_part_of_a_section():
    wording = files.DOCUMENT_FILES["policy_wording"]
    assert wording["version"] == "2026.1"
    assert wording["source"]["owner"] == "Legal"
    assert all("reviewed:" not in s["text"] for s in wording["sections"])
    assert [s["number"] for s in wording["sections"]] == list(range(1, 13))


def test_every_tool_is_read_only_with_a_one_line_description_and_no_optional_inputs():
    # Not asyncio.run, which leaves the main thread with no loop for Mangum.
    loop = asyncio.new_event_loop()
    tools = loop.run_until_complete(server.build_server().list_tools())
    loop.close()
    assert {t.name for t in tools} == {tool.__name__ for tool in server.TOOLS}
    assert len(tools) == 7
    for tool in tools:
        assert tool.description
        assert "\n" not in tool.description
        assert tool.annotations
        assert tool.annotations.readOnlyHint
        assert set(tool.inputSchema.get("required", [])) == set(
            tool.inputSchema["properties"]
        )


def event(body: dict[str, Any]) -> dict[str, Any]:
    """An MCP request as a Lambda Function URL delivers it (payload version 2.0)."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/mcp",
        "rawQueryString": "",
        "headers": {
            "host": LAMBDA_URL,
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "ctx123",
            "domainName": LAMBDA_URL,
            "http": {
                "method": "POST",
                "path": "/mcp",
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.1",
                "userAgent": "test",
            },
            "requestId": "request-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "12/Nov/2026:12:00:00 +0000",
            "timeEpoch": 0,
        },
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def test_the_lambda_handler_answers_twice_in_one_process():
    listed = server.handler(
        event({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
        LAMBDA_CONTEXT,
    )
    assert listed["statusCode"] == 200
    assert len(json.loads(listed["body"])["result"]["tools"]) == 7
    called = server.handler(
        event(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "lookup_term", "arguments": {"term": "carrier"}},
            }
        ),
        LAMBDA_CONTEXT,
    )
    assert called["statusCode"] == 200
    result = json.loads(called["body"])["result"]
    assert not result["isError"]
    assert json.loads(result["content"][0]["text"])["term"] == "Carrier"
