"""Tests for the reconciliation evaluation: its answer key and its scoring (no API calls)."""
import copy

from eval.reconcile_eval import TASK_ID_BASE, load_scenarios, score, simulate


def test_answer_key_is_achievable_under_the_apps_checks():
    # A stand-in model submits the key through the real review code. Every expected update must
    # pass the app's checks (an exact quote, the owner named in it), and none of the new tasks may
    # be held back by the app's wording check, or the key would ask for something impossible.
    r = score(simulate())
    assert r["repeats"]["app"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "new_tasks_held_back": 0}
    assert r["updates"]["exact"] == r["updates"]["expected_tasks"] == 26
    assert r["updates"]["fields"]["precision"] == r["updates"]["fields"]["recall"] == 1.0
    assert r["reviews"]["not_completed"] == 0


def perfect():
    return simulate()


def test_a_new_task_marked_as_a_repeat_counts_against_precision():
    preds = perfect()
    first = load_scenarios()[0]
    block = next(b for b in preds["scenarios"] if b["id"] == first["id"])
    block["existing_items"].append([first["expected"]["new_candidates"][0], TASK_ID_BASE])
    r = score(preds)
    assert r["repeats"]["agent"]["new_tasks_held_back"] == 1
    assert r["repeats"]["agent"]["precision"] < 1.0
    assert r["repeats"]["agent"]["recall"] == 1.0


def test_a_wrong_value_and_a_missed_update_are_scored():
    preds = perfect()
    block = preds["scenarios"][0]
    wrong = copy.deepcopy(block["updates"][0])
    wrong["after"]["owner"] = "Somebody Else"  # an extra, unexpected change on a right task
    block["updates"][0] = wrong
    del block["updates"][1]  # a missed update
    r = score(preds)
    assert r["updates"]["wrong_changes"] == 1
    assert r["updates"]["tasks"]["recall"] < 1.0
    assert r["updates"]["fields"]["precision"] < 1.0
    assert r["updates"]["exact"] == 24


def test_a_review_that_could_not_finish_finds_nothing_and_a_provider_error_is_excluded():
    preds = perfect()
    preds["scenarios"][0] = {"id": preds["scenarios"][0]["id"], "existing_items": [], "updates": [],
                             "questions": [], "error": "limit"}
    preds["scenarios"][1] = {"id": preds["scenarios"][1]["id"], "existing_items": [], "updates": [],
                             "questions": [], "error": "api"}
    r = score(preds)
    assert r["reviews"]["not_completed"] == 1
    assert r["reviews"]["provider_errors_excluded"] == 1
    assert r["reviews"]["scored"] == 7
    assert r["repeats"]["agent"]["recall"] < 1.0
