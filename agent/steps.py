"""How each of the model's tool results is recorded as a step on the claim.

A lookup in the context layer says what was looked up, with each file it came from
and the file's source, so the claim page can group them by file. A refusal says
who refused. A search of memory says what it searched for and found.
"""

import json
import re
from collections.abc import Callable
from typing import Any

STEP_LENGTH = 600
REFUSED = re.compile(r"^Refused by (.+?): ")

Args = dict[str, Any]
LOOKUPS: dict[str, Callable[[Args, Args], str]] = {
    "lookup_term": lambda args, found: f"The term “{args['term']}”",
    "describe_fields": lambda args, found: (
        f"What the fields of a {args['record'].replace('_', ' ')} mean"
    ),
    "get_plan": lambda args, found: f"The {args['plan']} plan",
    "get_claim_rules": lambda args, found: "The claim rules",
    "search_reference_data": lambda args, found: f"Outside facts on “{args['query']}”",
    "search_documents": lambda args, found: f"The documents, for “{args['query']}”",
    "read_section": lambda args, found: (
        f"{found['name']} · {found['number']}. {found['title']}"
    ),
}


def files_of(found: Args) -> list[Args]:
    """Each file an answer came from, once, with its source."""
    entries = found.get("found", [found])
    files: dict[str, Args] = {}
    for entry in entries:
        files.setdefault(entry["file"], {"file": entry["file"], **entry["source"]})
    return list(files.values())


def describe(
    name: str, routed: str, args: Args, text: str
) -> tuple[str, str, Args | None]:
    """A tool result's step: its kind, its text and its detail."""
    refused = REFUSED.match(text)
    if refused:
        return "refusal", f"{routed}: {text[:STEP_LENGTH]}", {"by": refused[1]}
    if name == "search_memory":
        query = args["query"]
        searched = f"Searched memory for {query!r}: {text[:STEP_LENGTH]}"
        return "memory_search", searched, {"query": query}
    if name in LOOKUPS:
        found = json.loads(text)
        looked_up = LOOKUPS[name](args, found)
        detail = {"looked_up": looked_up, "files": files_of(found)}
        return "lookup", looked_up, detail
    return "tool_result", f"{routed}: {text[:STEP_LENGTH]}", None
