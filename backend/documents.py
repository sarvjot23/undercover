"""The policy wording and the claims manual, split into their numbered sections."""

import re
from functools import cache
from typing import Any

from backend import db

DOCUMENTS = {
    "policy_wording": ("Policy wording", "policy_wording.md"),
    "claims_manual": ("Claims manual", "claims_manual.md"),
}

HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


@cache
def sections(document: str) -> list[dict[str, Any]]:
    """Return a document's sections in order: number, title and text."""
    text = (db.DATA / DOCUMENTS[document][1]).read_text(encoding="utf-8")
    headings = list(HEADING.finditer(text))
    return [
        {
            "number": int(heading[1]),
            "title": heading[2],
            "text": text[
                heading.start() : headings[i + 1].start()
                if i + 1 < len(headings)
                else len(text)
            ].strip(),
        }
        for i, heading in enumerate(headings)
    ]


def search(query: str) -> list[dict[str, Any]]:
    """Find the sections of both documents that hold every word of the query."""
    words = query.lower().split()
    found = []
    for document, (name, _) in DOCUMENTS.items():
        for section in sections(document):
            if all(word in section["text"].lower() for word in words):
                lines = [
                    line.strip()
                    for line in section["text"].splitlines()
                    if any(word in line.lower() for word in words)
                ]
                found.append(
                    {
                        "document": document,
                        "name": name,
                        "number": section["number"],
                        "title": section["title"],
                        "lines": lines,
                    }
                )
    return found
