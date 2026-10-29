from pathlib import Path


def test_the_wording_has_twelve_sections(client):
    found = client.get("/api/documents/policy_wording/sections").json()
    assert found["name"] == "Policy wording"
    assert len(found["sections"]) == 12
    assert found["sections"][2] == {"number": 3, "title": "Trip Delay"}


def test_the_manual_has_fourteen_sections(client):
    sections = client.get("/api/documents/claims_manual/sections").json()["sections"]
    assert len(sections) == 14


def test_a_section_in_full(client):
    section = client.get("/api/documents/claims_manual/sections/7").json()
    assert section["title"] == "Interpretation notes"
    assert "**Wild animals.**" in section["text"]
    assert "## 8." not in section["text"]


def test_no_section_is_the_whole_document(client):
    whole = Path("data/policy_wording.md").read_text(encoding="utf-8")
    for number in range(1, 13):
        text = client.get(f"/api/documents/policy_wording/sections/{number}").json()
        assert len(text["text"]) < len(whole) / 2


def test_search(client):
    found = client.get("/api/documents/search/giraffes").json()
    assert [(f["document"], f["number"]) for f in found] == [("claims_manual", 7)]
    assert any("giraffes" in line for line in found[0]["lines"])
    assert client.get("/api/documents/search/zeppelin").json() == []


def test_unknown_documents_and_sections(client):
    assert client.get("/api/documents/evals/sections").status_code == 404
    assert client.get("/api/documents/claims_manual/sections/99").status_code == 404


def test_no_section_mentions_the_evals(client):
    text = ""
    for document in ("policy_wording", "claims_manual"):
        for section in client.get(f"/api/documents/{document}/sections").json()[
            "sections"
        ]:
            text += client.get(
                f"/api/documents/{document}/sections/{section['number']}"
            ).text
    for word in ("evals", "difficulty", "failure_class", "over_approval_limit"):
        assert word not in text
