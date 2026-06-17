"""Unit tests for the evaluation matcher (no API calls)."""
from eval.run_eval import _jaccard, _match_items, _norm_owner


def test_jaccard_overlap():
    assert _jaccard("finish the APAC mapping", "Finish APAC cost center mapping") > 0.3
    assert _jaccard("schedule a pen test", "review the open items report") < 0.1


def test_norm_owner():
    assert _norm_owner("Daniel Tan") == "daniel"
    assert _norm_owner(None) is None
    assert _norm_owner("  ") is None


def test_greedy_matching_is_one_to_one():
    expected = [
        {"description": "finish the APAC cost center mapping"},
        {"description": "confirm the new cost center codes"},
    ]
    predicted = [
        {"description": "Confirm cost center codes"},
        {"description": "Finish APAC mapping"},
        {"description": "Totally unrelated task about catering"},
    ]
    matches = _match_items(expected, predicted)
    assert len(matches) == 2
    matched_pred = {pi for _, pi, _ in matches}
    assert 2 not in matched_pred  # the unrelated item is not matched
