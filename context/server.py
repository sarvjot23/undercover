"""UnderCover's context layer: an MCP server over data governance's files.

On the laptop, uv run -m context serves it at http://127.0.0.1:8006/mcp. On Lambda,
handler serves each request with a fresh server, since Mangum runs the app's
startup and shutdown around every request and a server's session manager can run
only once. The Function URL's IAM auth guards it there.
"""

from typing import Any, Literal

from mangum import Mangum
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from context.files import DOCUMENT_FILES, DOCUMENTS, YAML_FILES, answer

HOST = "127.0.0.1"
PORT = 8006

Document = Literal["policy_wording", "claims_manual"]


def words_in(query: str, text: str) -> bool:
    """Whether every word of the query is in the text, whatever its case."""
    return all(word in text.lower() for word in query.lower().split())


def lookup_term(term: str) -> dict[str, Any]:
    """Look up a term the policy wording defines, with the sections it comes from."""
    terms = YAML_FILES["glossary.yaml"]["terms"]
    for entry in terms:
        if entry["term"].lower() == term.strip().lower():
            return answer("glossary.yaml", **entry)
    return answer(
        "glossary.yaml",
        term=term,
        definition=None,
        defined_terms=[entry["term"] for entry in terms],
    )


def describe_fields(
    record: Literal["claim", "policy", "previous_claim"],
) -> dict[str, Any]:
    """Describe what each field means in a claim, a policy or a previous claim."""
    records = YAML_FILES["data_dictionary.yaml"]["records"]
    found = next(entry for entry in records if entry["record"] == record)
    return answer("data_dictionary.yaml", **found)


def get_plan(plan: Literal["economy", "premium", "first"]) -> dict[str, Any]:
    """Get a plan's limits, waiting periods and deductible, and the add-ons."""
    plans = YAML_FILES["plans.yaml"]
    return answer(
        "plans.yaml",
        plan=next(entry for entry in plans["plans"] if entry["plan"] == plan),
        deductible_applies_to=plans["deductible_applies_to"],
        add_ons=plans["add_ons"],
    )


def get_claim_rules() -> dict[str, Any]:
    """Get the rules claims operations applies to every claim, with their numbers."""
    return answer("claim_rules.yaml", rules=YAML_FILES["claim_rules.yaml"]["rules"])


def search_reference_data(query: str) -> dict[str, Any]:
    """Find outside facts, such as storms, strikes and prices, with every word."""
    facts = [
        {"topic": topic["topic"], "fact": fact}
        for topic in YAML_FILES["reference_data.yaml"]["topics"]
        for fact in topic["facts"]
        if words_in(query, fact)
    ]
    return answer("reference_data.yaml", query=query, facts=facts)


def search_documents(query: str) -> dict[str, Any]:
    """Find the sections of the wording and the manual that mention every word."""
    words = query.lower().split()
    found = [
        {
            "file": f"{document}.md",
            "source": prepared["source"],
            "document": document,
            "name": section["name"],
            "number": section["number"],
            "title": section["title"],
            "lines": [
                line.strip()
                for line in section["text"].splitlines()
                if any(word in line.lower() for word in words)
            ][:5],
        }
        for document, prepared in DOCUMENT_FILES.items()
        for section in prepared["sections"]
        if words_in(query, section["text"])
    ]
    return {"query": query, "found": found}


def read_section(document: Document, number: int) -> dict[str, Any]:
    """Read one numbered section of the policy wording or the claims manual."""
    prepared = DOCUMENT_FILES[document]
    for section in prepared["sections"]:
        if section["number"] == number:
            return answer(f"{document}.md", version=prepared["version"], **section)
    raise ValueError(f"No section {number} in the {DOCUMENTS[document].lower()}")


TOOLS = (
    lookup_term,
    describe_fields,
    get_plan,
    get_claim_rules,
    search_reference_data,
    search_documents,
    read_section,
)


def build_server(security: TransportSecuritySettings | None = None) -> FastMCP:
    """A stateless MCP server with JSON responses and read-only tools."""
    server = FastMCP(
        "undercover-context",
        host=HOST,
        port=PORT,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    for tool in TOOLS:
        server.add_tool(tool, annotations=ToolAnnotations(readOnlyHint=True))
    return server


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """The Lambda handler, behind a Function URL: a fresh server for each request."""
    any_host = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = build_server(any_host).streamable_http_app()
    return Mangum(app, lifespan="auto")(event, context)
