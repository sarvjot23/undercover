"""Our rule for keeping a new version or rolling it back, as in the Week 2 Day 5 lab.

A new version is kept when its held-out scores meet the objectives, at least one
measure improves by more than its noise, and none gets worse by more than its
tolerance. Accuracy and the grade are compared as differences, cost and time as
fractions of the old value. The settings are the round's own copy.
"""

from typing import Any

RULE = (
    "A new version is kept when it meets the objectives on the held-out set, at "
    "least one score improves by more than the noise and none gets worse by more "
    "than the tolerance. Accuracy and the grade are compared as differences, cost "
    "and time per claim as fractions of the old value."
)
DIFFERENCES = ("accuracy", "grade")
FRACTIONS = ("cost_per_claim", "seconds_per_claim")
LABELS = {
    "accuracy": "accuracy",
    "grade": "the grade",
    "cost_per_claim": "cost per claim",
    "seconds_per_claim": "time per claim",
}


def compare(
    new: dict[str, Any], old: dict[str, Any], settings: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Which scores got better by more than the noise, and worse by more than the
    tolerance. A measure the old version has no value for can't be compared."""
    noise, tolerance = settings["noise"], settings["tolerance"]
    better, worse = [], []
    for name in DIFFERENCES:
        if old.get(name) is None:
            continue
        if new[name] > old[name] + noise[name]:
            better.append(name)
        if new[name] < old[name] - tolerance[name]:
            worse.append(name)
    for name in FRACTIONS:
        if new[name] < old[name] * (1 - noise[name]):
            better.append(name)
        if new[name] > old[name] * (1 + tolerance[name]):
            worse.append(name)
    return better, worse


def named(names: list[str]) -> str:
    """Measures as words, such as accuracy and time per claim."""
    words = [LABELS[name] for name in names]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def keep_or_roll_back(
    new: dict[str, Any] | None, old: dict[str, Any], settings: dict[str, Any]
) -> tuple[bool, str]:
    """Decide whether to keep a new version from its held-out scores and the
    current version's, and say why."""
    if new is None:
        return False, "its evaluations didn't all finish"
    if new.get("grade") is None:
        return False, "it has no grade: the judge graded none of its claims"
    objectives = settings["objectives"]
    missed = [name for name, floor in objectives.items() if new[name] < floor]
    better, worse = compare(new, old, settings)
    if missed:
        return False, f"it missed the objectives on {named(missed)}"
    if worse:
        return False, f"{named(worse)} got worse by more than the tolerance"
    if not better:
        return False, "no score improved by more than the noise"
    return True, f"{named(better)} improved by more than the noise"
