"""Unit tests for the evaluation matcher and the ablation conditions (no API calls)."""
from eval.run_eval import (
    BARE_TOOL,
    CONDITIONS,
    EXTRACTION_TOOL,
    _jaccard,
    _match_overlap,
    _norm_owner,
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
    assert set(CONDITIONS) == {"naive", "prod"}

    basic_prompt, basic_tool = CONDITIONS["naive"]
    improved_prompt, improved_tool = CONDITIONS["prod"]

    # guidance is absent in one and present in the other, on both channels
    assert basic_prompt != improved_prompt
    assert basic_tool is not improved_tool
    assert improved_tool is EXTRACTION_TOOL      # Improved is exactly what ships
    assert basic_tool is BARE_TOOL

    # the output contract itself is unchanged (shape asserted in the test above)
    assert basic_tool["input_schema"]["required"] == \
        EXTRACTION_TOOL["input_schema"]["required"]
