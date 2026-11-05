"""What a version of a text changed from the one before, with difflib as in the lab."""

import difflib
from typing import Literal, TypedDict

CONTEXT = 2


class Line(TypedDict):
    """A line of a diff: kept, added, removed, or a gap for unchanged lines left out."""

    kind: Literal["same", "add", "remove", "gap"]
    text: str


KINDS: dict[str, Literal["same", "add", "remove"]] = {
    " ": "same",
    "+": "add",
    "-": "remove",
}


def paired(found: list[Line]) -> list[Line]:
    """Each removed line just above the line that replaced it, so a reader sees what
    each one became; difflib gives a block of removals, then a block of additions."""
    result: list[Line] = []
    removed: list[Line] = []
    added: list[Line] = []

    def flush() -> None:
        for number in range(max(len(removed), len(added))):
            result.extend(removed[number : number + 1])
            result.extend(added[number : number + 1])
        removed.clear()
        added.clear()

    for line in found:
        if line["kind"] == "remove" and not added:
            removed.append(line)
        elif line["kind"] == "add":
            added.append(line)
        else:
            flush()
            if line["kind"] == "remove":
                removed.append(line)
            else:
                result.append(line)
    flush()
    return result


def lines(old: str, new: str) -> list[Line]:
    """The changed lines with a little context, and a gap between distant changes."""
    found: list[Line] = []
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=CONTEXT
    )
    for line in diff:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            if found:
                found.append({"kind": "gap", "text": ""})
            continue
        found.append({"kind": KINDS[line[0]], "text": line[1:]})
    return paired(found)
