"""Gemini backend for the extraction pipeline (Objective 2).

Gemini is the shipped parser: on the annotated test set it leads Claude Sonnet on recall,
precision and F1, each separated by an exact permutation test over eight runs
(docs/evaluation-report.md). It reaches the model through the same forced-tool-call contract
the Claude path uses, so the caller gets a validated ExtractionResult either way.

The one difference is the schema. Anthropic accepts JSON Schema directly; Gemini takes an
OpenAPI subset, so the tool definition is translated here. The translation raises on anything
it does not recognise rather than dropping it silently - a schema field that vanished in
translation would weaken the contract without any error to notice.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.6-flash"
REQUEST_TIMEOUT_S = 90

# Flash is a thinking model and thinking tokens come out of this budget, so it sits well above
# what the response itself needs.
MAX_OUTPUT_TOKENS = 8192

_TYPE_MAP = {
    "string": "STRING", "number": "NUMBER", "integer": "INTEGER",
    "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT",
}


class GeminiError(RuntimeError):
    """Raised when Gemini fails or returns something the schema contract cannot accept."""


def to_gemini_schema(node: dict) -> dict:
    """Translate one JSON-Schema node into Gemini's OpenAPI-subset Schema."""
    out: dict = {}
    declared = node.get("type")
    nullable = False
    if isinstance(declared, list):
        # JSON Schema spells "optional string" as ["string", "null"]; Gemini uses a flag.
        concrete = [t for t in declared if t != "null"]
        nullable = "null" in declared
        if len(concrete) != 1:
            raise ValueError(f"cannot translate union type {declared!r}")
        declared = concrete[0]
    if declared is not None:
        if declared not in _TYPE_MAP:
            raise ValueError(f"unknown JSON-Schema type {declared!r}")
        out["type"] = _TYPE_MAP[declared]
    if nullable:
        out["nullable"] = True
    if "description" in node:
        out["description"] = node["description"]
    if "enum" in node:
        out["enum"] = list(node["enum"])
    if "items" in node:
        out["items"] = to_gemini_schema(node["items"])
    if "properties" in node:
        out["properties"] = {n: to_gemini_schema(s) for n, s in node["properties"].items()}
    if "required" in node:
        out["required"] = list(node["required"])
    unsupported = set(node) - {"type", "description", "enum", "items", "properties", "required"}
    if unsupported:
        raise ValueError(f"unhandled schema keywords: {sorted(unsupported)}")
    return out


def to_function_declaration(tool: dict) -> dict:
    """An Anthropic-style tool definition as a Gemini functionDeclaration."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": to_gemini_schema(tool["input_schema"]),
    }


def call_tool(system_prompt: str, tool: dict, user_text: str, model: str | None = None) -> dict:
    """Force a schema-conforming function call and return its arguments.

    `mode: ANY` with an explicit name is Gemini's equivalent of Anthropic's
    tool_choice={"type": "tool", ...}: the model must answer through the schema.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not set")
    model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "tools": [{"functionDeclarations": [to_function_declaration(tool)]}],
        "toolConfig": {"functionCallingConfig": {
            "mode": "ANY", "allowedFunctionNames": [tool["name"]]}},
        "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
    }
    req = urllib.request.Request(
        f"{API_ROOT}/{model}:generateContent?key={api_key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise GeminiError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
    except OSError as exc:
        raise GeminiError(f"could not reach Gemini: {exc}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError(f"no candidates returned: {json.dumps(data)[:300]}")
    for part in candidates[0].get("content", {}).get("parts") or []:
        if "functionCall" in part:
            return part["functionCall"].get("args") or {}
    raise GeminiError(
        f"no functionCall in response (finishReason={candidates[0].get('finishReason', '?')})")


def user_text(transcript_text: str, meeting_date: date) -> str:
    """The same user turn the Claude path sends, so the two backends see identical input."""
    return f"Meeting date: {meeting_date.isoformat()}\n\nTranscript:\n{transcript_text}"
