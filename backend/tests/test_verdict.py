from backend.verdict import compare, keep_or_roll_back

# The lab's settings.
SETTINGS = {
    "objectives": {"accuracy": 0.6, "grade": 1.0},
    "noise": {
        "accuracy": 0.1,
        "grade": 0.15,
        "cost_per_claim": 0.15,
        "seconds_per_claim": 0.15,
    },
    "tolerance": {
        "accuracy": 0.1,
        "grade": 0.15,
        "cost_per_claim": 1.0,
        "seconds_per_claim": 0.25,
    },
}
OLD = {"accuracy": 0.7, "grade": 1.5, "cost_per_claim": 0.001, "seconds_per_claim": 40}


def new(**changes):
    return {**OLD, **changes}


def test_a_version_better_by_more_than_the_noise_is_kept():
    # Accuracy up 0.15, past the noise of 0.1. Cost up 50%, inside the tolerance
    # of 100%, and time up 12.5%, inside 25%.
    found = new(accuracy=0.85, cost_per_claim=0.0015, seconds_per_claim=45)
    assert keep_or_roll_back(found, OLD, SETTINGS) == (
        True,
        "accuracy improved by more than the noise",
    )


def test_a_version_below_an_objective_is_rolled_back():
    found = new(accuracy=0.55, grade=1.9)
    assert keep_or_roll_back(found, OLD, SETTINGS) == (
        False,
        "it missed the objectives on accuracy",
    )


def test_a_version_worse_than_its_tolerance_is_rolled_back():
    # Accuracy is better, but time is up 30%, past the tolerance of 25%.
    found = new(accuracy=0.85, seconds_per_claim=52)
    assert keep_or_roll_back(found, OLD, SETTINGS) == (
        False,
        "time per claim got worse by more than the tolerance",
    )


def test_a_version_where_nothing_beat_the_noise_is_rolled_back():
    # Accuracy up 0.05, the grade up 0.1, cost and time down 10%: all inside the noise.
    found = new(accuracy=0.75, grade=1.6, cost_per_claim=0.0009, seconds_per_claim=36)
    assert keep_or_roll_back(found, OLD, SETTINGS) == (
        False,
        "no score improved by more than the noise",
    )


def test_a_version_with_no_grade_is_rolled_back():
    keep, why = keep_or_roll_back(new(accuracy=0.95, grade=None), OLD, SETTINGS)
    assert keep is False
    assert "no grade" in why


def test_a_version_whose_evaluations_didnt_finish_is_rolled_back():
    assert keep_or_roll_back(None, OLD, SETTINGS)[0] is False


def test_cost_and_time_are_compared_as_fractions():
    # 20% cheaper is past the noise of 15%; 10% slower is inside the tolerance.
    better, worse = compare(
        new(cost_per_claim=0.0008, seconds_per_claim=44), OLD, SETTINGS
    )
    assert (better, worse) == (["cost_per_claim"], [])
    # Doubling the cost is just inside a tolerance of 100%; more than double isn't.
    assert compare(new(cost_per_claim=0.002), OLD, SETTINGS)[1] == []
    assert compare(new(cost_per_claim=0.00201), OLD, SETTINGS)[1] == ["cost_per_claim"]


def test_accuracy_and_the_grade_are_compared_as_differences():
    # Up 0.09 is inside the noise of 0.1.
    assert compare(new(accuracy=0.79), OLD, SETTINGS)[0] == []
    better, worse = compare(new(accuracy=0.81, grade=1.3), OLD, SETTINGS)
    assert better == ["accuracy"]
    assert worse == ["grade"]


def test_several_measures_are_named_together():
    found = new(accuracy=0.85, grade=1.7, cost_per_claim=0.0008)
    assert keep_or_roll_back(found, OLD, SETTINGS)[1] == (
        "accuracy, the grade and cost per claim improved by more than the noise"
    )


def test_an_old_version_with_no_grade_is_compared_on_the_rest():
    better, _ = compare(new(accuracy=0.85), {**OLD, "grade": None}, SETTINGS)
    assert better == ["accuracy"]
