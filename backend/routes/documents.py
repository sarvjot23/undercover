"""The wording and the manual, read a section at a time, the way a handler would."""

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.documents import DOCUMENTS, search, sections

router = APIRouter(prefix="/api/documents")


def find_document(document: str) -> list[dict[str, Any]]:
    """Return a document's sections, or raise 404."""
    if document not in DOCUMENTS:
        raise HTTPException(404, f"No document {document}")
    return sections(document)


@router.get("/search/{query}", operation_id="search_documents")
def search_documents(query: str) -> list[dict[str, Any]]:
    """Find the sections of the wording and the manual that mention every word."""
    return search(query)


@router.get("/{document}/sections", operation_id="list_sections")
def list_sections(document: str) -> dict[str, Any]:
    """List a document's numbered sections."""
    found = find_document(document)
    return {
        "document": document,
        "name": DOCUMENTS[document][0],
        "sections": [
            {"number": section["number"], "title": section["title"]}
            for section in found
        ],
    }


@router.get("/{document}/sections/{number}", operation_id="read_section")
def read_section(document: str, number: int) -> dict[str, Any]:
    """Read one section of a document in full."""
    for section in find_document(document):
        if section["number"] == number:
            return {"document": document, "name": DOCUMENTS[document][0], **section}
    raise HTTPException(404, f"No section {number} in {document}")
