"""Offline scripted-model tests. These are not evidence of genuine LLM discovery."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from automation.contracts import Capability, Click, Constant, Target
from automation.discovery import discover
from automation.discovery_contracts import Act, DecisionEnvelope, DiscoveryTask, Finish
from automation.openrouter import ModelFailure, OpenRouterModel
from automation.policy import Policy
from automation.replay import replay


class ScriptedModel:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = 0

    async def decide(self, messages):
        self.calls += 1
        assert "12345" not in json.dumps(messages)
        assert "Please prepare a statement copy." not in json.dumps(messages)
        return DecisionEnvelope(decision=next(self.decisions)), {"provider_request_id": "offline"}


def fixtures(origin):
    task = DiscoveryTask.model_validate_json(Path("examples/discovery-task.json").read_text())
    cap = Capability.model_validate_json(Path("examples/review-request.json").read_text())
    policy = Policy.model_validate_json(Path("examples/policy.json").read_text())
    policy.origin = origin
    inputs = json.loads(Path("examples/inputs.json").read_text())
    actions = [Act(kind="act", intent="advance", step=s) for s in cap.steps[1:]]
    finish = Finish(
        kind="finish",
        intent="finish",
        outputs={name: output.target for name, output in cap.outputs.items()},
    )
    return task, policy, inputs, actions, finish


def test_discover_compile_then_replay_without_model(origin, tmp_path):
    task, policy, inputs, actions, finish = fixtures(origin)
    model = ScriptedModel([*actions, finish])
    result = asyncio.run(discover(task, inputs, policy, model, tmp_path / "discovery"))
    assert result.status == "success", result
    cap = Capability.model_validate_json((tmp_path / "discovery/capability.json").read_text())
    provenance = json.loads((tmp_path / "discovery/provenance.json").read_text())
    assert (
        provenance["capability_sha256"]
        == hashlib.sha256((tmp_path / "discovery/capability.json").read_bytes()).hexdigest()
    )
    calls = model.calls
    inputs.update(member_id="67890", request_type="address")
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "replay"))
    assert result.status == "success", result
    assert result.outputs["member_id"] == "67890"
    assert result.outputs["request_type"] == "address"
    assert model.calls == calls
    for file in (tmp_path / "discovery").iterdir():
        assert "12345" not in file.read_text()
        assert inputs["request_note"] not in file.read_text()


def test_false_completion_does_not_publish_artifact(origin, tmp_path):
    task, policy, inputs, _, finish = fixtures(origin)
    task.outcome_rules = []
    policy.timeout_ms = 200
    result = asyncio.run(discover(task, inputs, policy, ScriptedModel([finish]), tmp_path / "run"))
    assert result.status == "failure"
    assert result.code == "checkpoint_timeout"
    assert not (tmp_path / "run/capability.json").exists()


def test_discovery_enforces_action_policy(origin, tmp_path):
    task, policy, inputs, _, _ = fixtures(origin)
    action = Act(
        kind="act",
        intent="advance",
        step=Click(
            action="click", id="unsafe", target=Target(role="button", name="Submit request")
        ),
    )
    result = asyncio.run(discover(task, inputs, policy, ScriptedModel([action]), tmp_path / "run"))
    assert result.code == "policy_denied"
    assert not (tmp_path / "run/capability.json").exists()


def test_discovery_rejects_literal_input_values(origin, tmp_path):
    task, policy, inputs, actions, _ = fixtures(origin)
    actions[0].step.value = Constant(source="literal", value="12345")
    result = asyncio.run(discover(task, inputs, policy, ScriptedModel(actions), tmp_path / "run"))
    assert result.code == "input_reference_required"
    assert "12345" not in (tmp_path / "run/events.jsonl").read_text()


def test_discovery_is_bounded(origin, tmp_path):
    task, policy, inputs, actions, _ = fixtures(origin)
    result = asyncio.run(
        discover(task, inputs, policy, ScriptedModel(actions), tmp_path / "run", max_steps=1)
    )
    assert result.code == "step_limit"
    assert not (tmp_path / "run/capability.json").exists()


def test_discovery_known_outcome(origin, tmp_path):
    task, policy, inputs, actions, finish = fixtures(origin)
    inputs["member_id"] = "99999"
    result = asyncio.run(
        discover(task, inputs, policy, ScriptedModel([*actions, finish]), tmp_path / "run")
    )
    assert result.status == "business_outcome"
    assert result.code == "member_not_found"
    assert not (tmp_path / "run/capability.json").exists()


def response(decision):
    return {
        "id": "test-request",
        "model": "test-model",
        "usage": {"prompt_tokens": 10},
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "function": {"name": "finish", "arguments": decision},
                        }
                    ]
                },
            }
        ],
    }


def test_openrouter_transport_validates_and_omits_raw_reply():
    decision = json.dumps({"outputs": {}})

    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        # Parallel-call control is not portable across providers. Enforce one locally.
        assert "parallel_tool_calls" not in body
        assert "$ref" not in json.dumps(body["tools"])
        assert {tool["function"]["name"] for tool in body["tools"]} == {
            "fill",
            "select",
            "click",
            "check",
            "finish",
        }
        return httpx.Response(200, json=response(decision))

    model = OpenRouterModel("test-key", transport=httpx.MockTransport(handler))
    envelope, metadata = asyncio.run(model.decide([]))
    assert isinstance(envelope.decision, Finish)
    assert metadata["provider_request_id"] == "test-request"
    assert "outputs" not in json.dumps(metadata)


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, {"error": "SECRET"}, "model_http_401"),
        (200, response("not-json SECRET"), "invalid_model_response"),
        (200, {"choices": []}, "invalid_model_response"),
    ],
)
def test_openrouter_error_bodies_never_escape(status, body, code):
    model = OpenRouterModel(
        "SECRET", transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    )
    with pytest.raises(ModelFailure) as error:
        asyncio.run(model.decide([]))
    assert str(error.value) == code


def test_dotenv_does_not_override_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=file-key\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "existing-key")
    assert OpenRouterModel.from_environment().api_key == "existing-key"


def test_multiple_model_actions_are_rejected_before_execution():
    body = response('{"outputs": {}}')
    calls = body["choices"][0]["message"]["tool_calls"]
    calls.append(calls[0])
    model = OpenRouterModel(
        "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    with pytest.raises(ModelFailure, match="invalid_tool_selection"):
        asyncio.run(model.decide([]))


def test_input_tool_preserves_named_reference():
    body = response(
        json.dumps({"target": {"role": "textbox", "name": "Member ID"}, "input": "member_id"})
    )
    body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "fill"
    model = OpenRouterModel(
        "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    decision, _ = asyncio.run(model.decide([]))
    assert decision.decision.step.value.name == "member_id"
    assert decision.decision.step.value.source == "input"
