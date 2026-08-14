"""Unit tests for the evaluation matcher and the ablation conditions (no API calls)."""
from eval.run_eval import (
    BARE_TOOL,
    BASELINE_PROMPT,
    COMPARISON_CONDITIONS,
    CONDITIONS,
    EXTRACTION_TOOL,
    SYSTEM_PROMPT,
    _jaccard,
    _match_overlap,
    _norm_owner,
    runs_with,
)


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
    matches = _match_overlap(expected, predicted)
    assert len(matches) == 2
    matched_pred = {pi for _, pi, _ in matches}
    assert 2 not in matched_pred  # the unrelated item is not matched


def _descriptions(node):
    """Every 'description' value anywhere in a schema fragment."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "description" and isinstance(v, str):
                found.append(v)
            found.extend(_descriptions(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_descriptions(v))
    return found


def test_bare_tool_keeps_shape_but_drops_guidance():
    """The control must differ from the shipped schema ONLY in guidance text.

    Regression test: an earlier stripper removed every key named "description", which also
    deleted the *field* called "description" from the properties map. That left the control
    requiring a field it no longer defined - a malformed schema rather than an unguided one.
    """
    bare = BARE_TOOL["input_schema"]["properties"]["action_items"]["items"]
    rich = EXTRACTION_TOOL["input_schema"]["properties"]["action_items"]["items"]

    # identical output shape: same fields, same types, same enum, same required list
    assert set(bare["properties"]) == set(rich["properties"])
    assert "description" in bare["properties"]
    assert bare["required"] == rich["required"]
    assert bare["properties"]["status"]["enum"] == ["todo", "in_progress", "done"]
    assert bare["properties"]["owner"]["type"] == ["string", "null"]

    # ...but no guidance text survives anywhere in the control
    assert _descriptions(BARE_TOOL["input_schema"]) == []
    assert _descriptions(EXTRACTION_TOOL["input_schema"]) != []


def test_two_conditions_differing_only_in_guidance():
    """Basic vs Improved must differ in guidance and in nothing else.

    The guidance is evaluated as one layer because the prompt rules and the schema field
    descriptions carry the same instructions and always ship together.
    """
    basic, improved = CONDITIONS["naive"], CONDITIONS["prod"]

    # guidance is absent in one and present in the other, on both channels
    assert basic.prompt != improved.prompt
    assert basic.tool is not improved.tool
    assert improved.tool is EXTRACTION_TOOL      # Improved is exactly what ships
    assert basic.tool is BARE_TOOL

    # the output contract itself is unchanged (shape asserted in the test above)
    assert basic.tool["input_schema"]["required"] == \
        EXTRACTION_TOOL["input_schema"]["required"]


def test_the_2x2_is_actually_a_2x2():
    """Every group carrying a Basic arm must also carry an Improved arm, and vice versa.

    Groups exist for two purposes: the guidance 2x2 (both arms) and the model comparison
    (Improved only). A group with a Basic arm but no Improved one - or the reverse - would mean
    a half-built cross silently scoring as if it were complete.
    """
    by_group = {}
    for cond in CONDITIONS.values():
        by_group.setdefault(cond.group, {})[cond.guidance] = cond

    crossed = {g: arms for g, arms in by_group.items() if len(arms) == 2}
    assert set(crossed) == {"claude", "gemini"}, "the guidance 2x2 is claude x gemini"

    for group, arms in crossed.items():
        assert set(arms) == {"Basic", "Improved"}, group
        # the guidance carried into each model is identical to the other model's
        assert arms["Basic"].prompt == BASELINE_PROMPT
        assert arms["Basic"].tool is BARE_TOOL
        assert arms["Improved"].prompt == SYSTEM_PROMPT
        assert arms["Improved"].tool is EXTRACTION_TOOL

    # every non-crossed group is Improved-only - never a stranded Basic arm
    for group, arms in by_group.items():
        if group not in crossed:
            assert set(arms) == {"Improved"}, group


def test_comparison_conditions_vary_only_the_model():
    """The model comparison must vary the model and nothing else.

    If any row differed in prompt or schema, a configuration difference would be reported as a
    vendor difference.
    """
    assert len(COMPARISON_CONDITIONS) >= 2
    for key in COMPARISON_CONDITIONS:
        cond = CONDITIONS[key]
        assert cond.guidance == "Improved", key
        assert cond.prompt is SYSTEM_PROMPT, key
        assert cond.tool is EXTRACTION_TOOL, key

    # one row per model - a duplicated group would double-count a vendor
    assert len({CONDITIONS[k].group for k in COMPARISON_CONDITIONS}) == len(COMPARISON_CONDITIONS)
    # the incumbent must be present: a candidate list without the model being replaced
    # cannot answer "should this project switch?"
    assert "prod" in COMPARISON_CONDITIONS


def test_every_condition_has_a_distinct_label():
    """Labels key the report tables; a duplicate would silently merge two rows."""
    labels = [c.label for c in CONDITIONS.values()]
    assert len(set(labels)) == len(labels)


def test_runs_with_isolates_conditions():
    """A run holds one provider, so aggregates must filter - not assume a uniform run list.

    Without this, appending a Gemini run would silently change the cached Claude figures.
    """
    cache = {"runs": [
        {"conditions": {"naive": [], "prod": []}},
        {"conditions": {"gemini_naive": [], "gemini_prod": []}},
    ]}
    assert len(runs_with(cache, "naive")) == 1
    assert len(runs_with(cache, "gemini_prod")) == 1
    assert runs_with(cache, "never_parsed") == []
