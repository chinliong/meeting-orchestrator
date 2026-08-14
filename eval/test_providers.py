"""Schema-fidelity tests for the Gemini adapter (no API calls).

The cross-model comparison is only meaningful if both providers receive the same output
contract. Gemini needs its own schema dialect, so the schema is translated - and a translation
bug would show up in the results as a "model difference" that is really a harness defect. These
tests pin the translation.
"""
import pytest

from eval.providers import to_function_declaration, to_gemini_schema
# Imported via run_eval rather than app.llm.parser directly: run_eval is what puts backend/ on
# sys.path, so importing app first would fail at collection time.
from eval.run_eval import BARE_TOOL, EXTRACTION_TOOL


def _item_props(tool):
    """The action-item object's property map, in Anthropic form."""
    return tool["input_schema"]["properties"]["action_items"]["items"]


def _gem_item(tool):
    """The same node after translation to Gemini's dialect."""
    return to_gemini_schema(tool["input_schema"])["properties"]["action_items"]["items"]


@pytest.mark.parametrize("tool", [EXTRACTION_TOOL, BARE_TOOL], ids=["improved", "basic"])
def test_translation_preserves_the_output_contract(tool):
    """Fields, required list and enum must survive translation for BOTH conditions."""
    src, gem = _item_props(tool), _gem_item(tool)

    assert set(gem["properties"]) == set(src["properties"])
    assert gem["required"] == src["required"]
    assert gem["properties"]["status"]["enum"] == ["todo", "in_progress", "done"]
    assert gem["type"] == "OBJECT"


@pytest.mark.parametrize("tool", [EXTRACTION_TOOL, BARE_TOOL], ids=["improved", "basic"])
def test_field_named_description_is_not_mistaken_for_an_annotation(tool):
    """Regression guard, same bug class as the BARE_TOOL stripper.

    The schema has a *field* called "description" as well as schema *annotations* called
    "description". A generic dict walker conflates them; this one must not.
    """
    gem = _gem_item(tool)
    assert "description" in gem["properties"]
    assert gem["properties"]["description"]["type"] == "STRING"


def test_nullable_union_becomes_a_flag():
    """["string", "null"] has no equivalent in Gemini's dialect and becomes nullable: true."""
    gem = _gem_item(EXTRACTION_TOOL)
    assert gem["properties"]["owner"]["type"] == "STRING"
    assert gem["properties"]["owner"]["nullable"] is True
    assert gem["properties"]["deadline"]["nullable"] is True
    # a non-nullable field must not pick up the flag
    assert "nullable" not in gem["properties"]["description"]


def test_guidance_is_the_only_difference_after_translation():
    """The Basic/Improved contrast must survive translation unchanged: same shape, no guidance.

    This is the Gemini-side equivalent of test_matching.test_bare_tool_keeps_shape_but_drops_guidance.
    """
    basic, improved = _gem_item(BARE_TOOL), _gem_item(EXTRACTION_TOOL)

    assert set(basic["properties"]) == set(improved["properties"])
    assert basic["required"] == improved["required"]
    assert basic["properties"]["status"]["enum"] == improved["properties"]["status"]["enum"]

    assert _descriptions(basic) == []
    assert _descriptions(improved) != []


def test_unknown_keywords_raise_rather_than_being_dropped():
    """Silently dropping a keyword would weaken one side of the comparison without warning."""
    with pytest.raises(ValueError, match="unhandled schema keywords"):
        to_gemini_schema({"type": "string", "pattern": "^x$"})
    with pytest.raises(ValueError, match="union type"):
        to_gemini_schema({"type": ["string", "integer"]})


def test_function_declaration_shape():
    fn = to_function_declaration(EXTRACTION_TOOL)
    assert fn["name"] == "record_extraction"
    assert fn["parameters"]["type"] == "OBJECT"
    assert set(fn["parameters"]["properties"]) == {"decisions", "action_items"}


def _descriptions(node):
    """Every annotation value anywhere below this node, ignoring field names."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "description" and isinstance(v, str):
                found.append(v)
            elif k == "properties" and isinstance(v, dict):
                for sub in v.values():           # keys are field names - do not inspect them
                    found.extend(_descriptions(sub))
            else:
                found.extend(_descriptions(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_descriptions(v))
    return found
