"""Small HTTP adapter for OpenRouter's documented tool-calling protocol.

No agent framework, provider-specific browser tool, or model dependency in replay.
"""

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from automation.contracts import Check, Click, Fill, InputRef, Model, Select, Target
from automation.discovery_contracts import Act, DecisionEnvelope, Finish

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class InputAction(Model):
    target: Target
    input: str


class TargetAction(Model):
    target: Target


class FinishAction(Model):
    outputs: dict[str, Target]


TOOL_MODELS = {
    "fill": InputAction,
    "select": InputAction,
    "click": TargetAction,
    "check": TargetAction,
    "finish": FinishAction,
}


def tool_schema(model):
    """Inline references for provider portability; runtime validation stays strict."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].rsplit("/", 1)[-1]])
            return {key: expand(item) for key, item in value.items()}
        return value

    return expand(schema)


def parse_call(call):
    name = call["function"]["name"]
    if name not in TOOL_MODELS:
        raise ModelFailure("invalid_tool_selection")
    arguments = TOOL_MODELS[name].model_validate_json(call["function"]["arguments"])
    if name == "finish":
        return DecisionEnvelope(
            decision=Finish(
                kind="finish",
                intent="finish",
                outputs=arguments.outputs,
            )
        )
    if name in {"fill", "select"}:
        step_type = Fill if name == "fill" else Select
        step = step_type(
            action=name,
            id="pending",
            target=arguments.target,
            value=InputRef(source="input", name=arguments.input),
        )
        intent = "enter_input"
    else:
        step_type = Click if name == "click" else Check
        step = step_type(action=name, id="pending", target=arguments.target)
        intent = "advance" if name == "click" else "verify"
    return DecisionEnvelope(decision=Act(kind="act", intent=intent, step=step))


class ModelFailure(Exception):
    """Only fixed codes leave this boundary; never include provider response bodies."""

    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details


class OpenRouterModel:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *, transport=None):
        self.api_key = api_key
        self.model = model
        self.transport = transport

    @classmethod
    def from_environment(cls, model: str | None = None):
        # Only discovery calls this. Explicit path; existing environment takes precedence.
        load_dotenv(Path(".env"), override=False, interpolate=False)
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ModelFailure("missing_api_key")
        return cls(key, model or os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL)

    async def decide(self, messages: list[dict]) -> tuple[DecisionEnvelope, dict]:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            "Fill or select a control using a named task input, "
                            "never a literal value."
                            if name in {"fill", "select"}
                            else "Finish by mapping every output name to a visible control "
                            "containing its value."
                            if name == "finish"
                            else "Click a visible control."
                            if name == "click"
                            else "Verify a uniquely identified visible control."
                        ),
                        "parameters": tool_schema(schema),
                    },
                }
                for name, schema in TOOL_MODELS.items()
            ],
            "tool_choice": "required",
            "provider": {"require_parameters": True},
            "temperature": 0,
            "max_tokens": 1200,
        }
        try:
            async with httpx.AsyncClient(timeout=45, transport=self.transport) as client:
                response = await client.post(
                    ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError:
            raise ModelFailure("model_transport_error") from None
        if response.status_code != 200:
            raise ModelFailure(f"model_http_{response.status_code}")
        try:
            data = response.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") != "tool_calls":
                raise ModelFailure("incomplete_model_response")
            calls = choice["message"]["tool_calls"]
            if len(calls) != 1:
                raise ModelFailure("invalid_tool_selection")
            decision = parse_call(calls[0])
            usage = data.get("usage") or {}
            # Whitelisted metadata only; no model prose, tool arguments, or hidden reasoning.
            metadata = {
                "provider_request_id": data.get("id"),
                "model": data.get("model", self.model),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            }
            return decision, metadata
        except ValidationError as error:
            # Error categories are safe diagnostics; raw rejected arguments are not.
            safe_fields = {
                "decision",
                "act",
                "finish",
                "step",
                "fill",
                "select",
                "click",
                "navigate",
                "check",
                "target",
                "value",
                "equals",
                "outputs",
            }
            raise ModelFailure(
                "invalid_model_response",
                [
                    {
                        "type": item["type"],
                        "path": [part if part in safe_fields else "field" for part in item["loc"]],
                    }
                    for item in error.errors(include_input=False)
                ],
            ) from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelFailure("invalid_model_response") from None
