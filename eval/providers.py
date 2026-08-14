"""Non-Anthropic provider adapters, used only by the evaluation harness.

Why this exists
---------------
The shipped application talks to Claude and only Claude (`backend/app/llm/parser.py`). This
module is deliberately kept out of the product code: it exists so the *evaluation* can compare
model families without adding a second provider dependency to the thing that actually ships.

Each adapter exposes the same surface as `TranscriptParser` - `.parse(text, meeting_date)`
returning an `ExtractionResult` - so `run_eval.parse_run` treats every provider identically and
none of them gets accidentally favourable handling.

Schema fidelity is the whole point
----------------------------------
A model comparison only means anything if every model receives the *same* output contract. The
two providers here disagree about how to express it:

* **Mistral** takes JSON Schema more or less as-is (OpenAI-style function calling), so the tool's
  schema is passed through unchanged.
* **Gemini** does not. It takes an OpenAPI subset in which a nullable field is
  `{"type": "STRING", "nullable": true}` rather than `{"type": ["string", "null"]}`, so the
  schema must be translated - and a sloppy translation would silently change the contract and
  show up as a "model difference" that is really a harness bug.

`to_gemini_schema` is therefore written as an explicit schema-node walker rather than a generic
dict transform. That matters: an earlier bug in this harness (see the BARE_TOOL note in
run_eval.py) came from a generic walker that could not tell a *field named* "description" from a
schema *annotation* called "description". This walker reads annotations only from the node it is
on and recurses into `properties` values by name, so it cannot make that mistake.
`eval/test_providers.py` asserts the round-trip preserves fields, required list and enum.

No SDK is used. Raw HTTP keeps each request body exactly as written here - SDK helpers tend to
rewrite schemas on the way out, which is precisely what must not happen in this file.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- errors
class ProviderError(RuntimeError):
    """The provider never returned a usable answer.

    run_eval treats this as an *API* failure rather than a model-quality failure: it is excluded
    from scoring instead of being counted as the model finding nothing.
    """


class GeminiError(ProviderError):
    pass


class MistralError(ProviderError):
    pass


# ----------------------------------------------------------------------------- http
# A hung request is a common failure here, so the read timeout is deliberately short: several
# attempts that each give up quickly beat one that blocks the whole run for minutes.
REQUEST_TIMEOUT_S = 90
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _error_details(raw: str) -> list:
    try:
        return json.loads(raw).get("error", {}).get("details", []) or []
    except (ValueError, AttributeError):
        return []


def _is_daily_quota(raw: str) -> bool:
    """True when a 429 is a per-day cap rather than a per-minute burst limit."""
    for detail in _error_details(raw):
        for violation in detail.get("violations", []) or []:
            if "PerDay" in (violation.get("quotaId") or ""):
                return True
    return False


def _retry_after(raw: str) -> float | None:
    """The server's own RetryInfo hint, in seconds, when it supplies one."""
    for detail in _error_details(raw):
        value = detail.get("retryDelay")
        if isinstance(value, str) and value.endswith("s"):
            try:
                return float(value[:-1])
            except ValueError:
                pass
    return None


def _post_json(url: str, headers: dict, body: dict, error_cls, attempts: int = 6) -> dict:
    """POST with backoff over the transient failures these endpoints actually produce.

    Capacity pressure shows up three ways - HTTP 429, HTTP 5xx, and a connection that simply
    never answers - so all three are retried. Note that `socket.timeout` is not a `URLError`, so
    it needs catching in its own right or a hang escapes the retry loop.

    A *per-day* quota is the exception: it will not clear within any sane backoff, so it fails
    fast and says what actually happened rather than burning minutes on doomed retries.
    """
    payload = json.dumps(body).encode()
    last: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            if exc.code == 429 and _is_daily_quota(raw):
                raise error_cls(
                    "Free-tier DAILY quota exhausted for this model. Wait for the quota to "
                    "reset, or point the condition at a different model - noting that changing "
                    "model mid-experiment makes runs non-comparable."
                ) from exc
            last = error_cls(f"HTTP {exc.code}: {raw[:400]}")
            if exc.code not in RETRYABLE_STATUS:
                raise last from exc
            hinted = _retry_after(raw)
            if hinted is not None:
                time.sleep(min(hinted, 60))
                continue
        except socket.timeout:
            last = error_cls(f"request timed out after {REQUEST_TIMEOUT_S}s")
        except urllib.error.URLError as exc:
            last = error_cls(f"network error: {exc}")
        if attempt < attempts - 1:
            time.sleep(min(2 ** attempt, 30))
    raise last  # type: ignore[misc]


def _user_text(transcript_text: str, meeting_date) -> str:
    """Identical user message for every provider - the date anchor must not vary."""
    return f"Meeting date: {meeting_date.isoformat()}\n\nTranscript:\n{transcript_text}"


def _validated(args: dict):
    from app.schemas.schemas import ExtractionResult
    return ExtractionResult.model_validate(args or {})


# --------------------------------------------------------------------------- gemini
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Pinned rather than the floating "gemini-flash-latest" alias: an evaluation whose model can
# change underneath it is not reproducible.
#
# Why 3.6 and not 3.7: gemini-3.7-flash (version 3.7-flash-08-2026) is the newest Flash the API
# offers as of August 2026, but on this schema it was measured returning HTTP 503 "model is
# currently experiencing high demand" - or hanging until the socket timed out - on roughly three
# attempts in four. A benchmark cannot rest on a model that answers a quarter of the time. 3.6
# Flash (3.6-flash-07-2026) is the newest Flash that responds reliably, and when 3.7 did answer
# it returned the same item count. Override with GEMINI_MODEL to re-run on 3.7 later.
DEFAULT_MODEL = "gemini-3.6-flash"

_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def to_gemini_schema(node: dict) -> dict:
    """Translate one JSON-Schema node into Gemini's OpenAPI-subset Schema.

    Only the keywords this project's extraction schema actually uses are handled; anything
    unexpected raises rather than being dropped silently, so a schema change cannot quietly
    weaken the contract on one side of the comparison.
    """
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

    # An annotation on *this* node. Field names never reach here - they stay as the keys of the
    # `properties` map below and are recursed into by name.
    if "description" in node:
        out["description"] = node["description"]
    if "enum" in node:
        out["enum"] = list(node["enum"])
    if "items" in node:
        out["items"] = to_gemini_schema(node["items"])
    if "properties" in node:
        out["properties"] = {
            name: to_gemini_schema(sub) for name, sub in node["properties"].items()
        }
    if "required" in node:
        out["required"] = list(node["required"])

    unsupported = set(node) - {
        "type", "description", "enum", "items", "properties", "required",
    }
    if unsupported:
        raise ValueError(f"unhandled schema keywords: {sorted(unsupported)}")
    return out


def to_function_declaration(tool: dict) -> dict:
    """Anthropic tool definition -> Gemini functionDeclaration."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": to_gemini_schema(tool["input_schema"]),
    }


class GeminiParser:
    """Google Gemini via generateContent + forced function calling."""

    def __init__(self, system_prompt: str, tool: dict, model: str | None = None,
                 api_key: str | None = None, max_output_tokens: int = 8192):
        self.system_prompt = system_prompt
        self.function = to_function_declaration(tool)
        self.tool_name = tool["name"]
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set (expected in backend/.env)")
        # Flash 3.x is a thinking model and thinking tokens are drawn from this budget, so it is
        # set above what the other providers need. All are ceilings no response approaches, so
        # this does not advantage any of them.
        self.max_output_tokens = max_output_tokens

    def parse(self, transcript_text: str, meeting_date=None):
        from datetime import date as _date
        meeting_date = meeting_date or _date.today()
        body = {
            "systemInstruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [{"role": "user",
                          "parts": [{"text": _user_text(transcript_text, meeting_date)}]}],
            "tools": [{"functionDeclarations": [self.function]}],
            # mode ANY + an explicit name is Gemini's equivalent of Anthropic's
            # tool_choice={"type": "tool", ...}: the model must answer through the schema.
            "toolConfig": {"functionCallingConfig": {
                "mode": "ANY", "allowedFunctionNames": [self.tool_name]}},
            "generationConfig": {"maxOutputTokens": self.max_output_tokens},
        }
        url = f"{GEMINI_API_ROOT}/{self.model}:generateContent?key={self.api_key}"
        data = _post_json(url, {}, body, GeminiError)

        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError(f"no candidates returned: {json.dumps(data)[:400]}")
        for part in candidates[0].get("content", {}).get("parts") or []:
            if "functionCall" in part:
                return _validated(part["functionCall"].get("args"))
        raise GeminiError(
            f"no functionCall in response (finishReason={candidates[0].get('finishReason', '?')})")


# -------------------------------------------------------------------------- mistral
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# Tier-matched to the other models under comparison (Gemini Flash, Claude Haiku) rather than
# picking Mistral's largest: comparing a small model against two large ones would measure tier,
# not vendor. Pinned to the dated id so "latest" cannot move under the experiment.
MISTRAL_DEFAULT_MODEL = "mistral-small-2603"


class MistralParser:
    """Mistral via OpenAI-style chat completions + forced tool choice.

    Mistral accepts JSON Schema directly, so the tool schema is passed through *unchanged* - no
    translation step and therefore no translation risk. That is worth noting when reading the
    results: any difference against Gemini is a model difference, not a schema-dialect artefact.
    """

    def __init__(self, system_prompt: str, tool: dict, model: str | None = None,
                 api_key: str | None = None, max_tokens: int = 4096):
        self.system_prompt = system_prompt
        self.tool_name = tool["name"]
        self.tool = {"type": "function", "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        }}
        self.model = model or os.getenv("MISTRAL_MODEL") or MISTRAL_DEFAULT_MODEL
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("MISTRAL_API_KEY is not set (expected in backend/.env)")
        self.max_tokens = max_tokens

    def parse(self, transcript_text: str, meeting_date=None):
        from datetime import date as _date
        meeting_date = meeting_date or _date.today()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": _user_text(transcript_text, meeting_date)},
            ],
            "tools": [self.tool],
            # "any" forces a tool call; with a single tool declared this pins the answer to the
            # schema, matching the other two providers' forced-tool behaviour.
            "tool_choice": "any",
            "max_tokens": self.max_tokens,
        }
        data = _post_json(
            MISTRAL_URL, {"Authorization": f"Bearer {self.api_key}"}, body, MistralError)

        choices = data.get("choices") or []
        if not choices:
            raise MistralError(f"no choices returned: {json.dumps(data)[:400]}")
        calls = choices[0].get("message", {}).get("tool_calls") or []
        if not calls:
            raise MistralError(
                f"no tool_call in response (finish_reason={choices[0].get('finish_reason', '?')})")
        arguments = calls[0].get("function", {}).get("arguments")
        # Mistral returns the arguments as a JSON *string*, unlike the other two providers.
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                raise MistralError(f"tool arguments were not valid JSON: {arguments[:200]}") from exc
        return _validated(arguments)
