"""Data governance's seven files, read once when the process starts.

Each file names its source: the system it comes from, its owner and when it was
last reviewed. The documents are split at their numbered headings into sections,
and a document's front matter is its source and version, never part of a section.
"""

import re
from pathlib import Path
from typing import Any

import yaml

FOLDER = Path(__file__).parent
HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
DOCUMENTS = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}


def read_yaml(name: str) -> dict[str, Any]:
    """One of the YAML files."""
    return yaml.safe_load((FOLDER / name).read_text(encoding="utf-8"))


def split(document: str) -> dict[str, Any]:
    """A document's source, version and sections, each tagged with where it's from."""
    text = (FOLDER / f"{document}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    headings = list(HEADING.finditer(body))
    sections = [
        {
            "document": document,
            "name": DOCUMENTS[document],
            "number": int(heading[1]),
            "title": heading[2],
            "text": body[
                heading.start() : headings[i + 1].start()
                if i + 1 < len(headings)
                else len(body)
            ].strip(),
        }
        for i, heading in enumerate(headings)
    ]
    return {"source": meta["source"], "version": meta["version"], "sections": sections}


YAML_FILES = {
    name: read_yaml(name)
    for name in (
        "data_dictionary.yaml",
        "glossary.yaml",
        "plans.yaml",
        "claim_rules.yaml",
        "reference_data.yaml",
    )
}
DOCUMENT_FILES = {document: split(document) for document in DOCUMENTS}


def source(name: str) -> dict[str, str]:
    """A file's source: its system, owner and review date."""
    if name.endswith(".md"):
        return DOCUMENT_FILES[name.removesuffix(".md")]["source"]
    return YAML_FILES[name]["source"]


def answer(name: str, /, **found: Any) -> dict[str, Any]:
    """An answer that names the file it came from, with the file's source."""
    return {"file": name, "source": source(name), **found}
