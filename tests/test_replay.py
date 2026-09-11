"""Real Chromium tests against a local HTTP application; no model credentials required."""

import asyncio
import json
from pathlib import Path

import pytest

from automation.contracts import Capability, Click, Target
from automation.policy import Policy
from automation.replay import replay


def setup(origin):
    cap = Capability.model_validate_json(Path("examples/review-request.json").read_text())
    policy = Policy.model_validate_json(Path("examples/policy.json").read_text())
    policy.origin = origin
    inputs = json.loads(Path("examples/inputs.json").read_text())
    return cap, policy, inputs


@pytest.mark.parametrize(
    "member,kind,scenario",
    [
        ("12345", "statement", "normal"),
        ("67890", "address", "normal"),
        ("12345", "statement", "slow"),
    ],
)
def test_replay_new_inputs_and_slow_load(origin, tmp_path, member, kind, scenario):
    cap, policy, inputs = setup(origin)
    inputs.update(member_id=member, request_type=kind, scenario=scenario)
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.status == "success", result
    assert result.outputs == {
        "member_id": member,
        "request_type": kind,
        "review_status": "ready",
    }
    evidence = (tmp_path / "run/events.jsonl").read_text()
    assert member not in evidence
    assert inputs["request_note"] not in evidence


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"member_id": "99999"}, "member_not_found"),
        ({"request_note": "bad"}, "validation_error"),
    ],
)
def test_known_business_outcomes(origin, tmp_path, patch, code):
    cap, policy, inputs = setup(origin)
    inputs.update(patch)
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.status == "business_outcome", result
    assert result.code == code


def test_irreversible_action_blocked_and_failure_evidence_redacted(origin, tmp_path):
    cap, policy, inputs = setup(origin)
    inputs["request_note"] = "SENSITIVE_SENTINEL_DO_NOT_PERSIST"
    cap.steps.append(
        Click(id="submit", action="click", target=Target(role="button", name="Submit request"))
    )
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.status == "failure"
    assert result.code == "policy_denied"
    assert result.step == "submit"
    assert (tmp_path / "run/failure-dom.json").is_file()
    for file in (tmp_path / "run").iterdir():
        assert inputs["request_note"] not in file.read_text()
        assert inputs["member_id"] not in file.read_text()


def test_checkpoint_is_verified(origin, tmp_path):
    cap, policy, inputs = setup(origin)
    cap.success.equals.value = "wrong"
    policy.timeout_ms = 200
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.status == "failure"
    assert result.code == "checkpoint_timeout"


def test_invalid_input_does_not_launch_browser(tmp_path):
    cap, policy, inputs = setup("http://127.0.0.1:1")
    inputs["request_type"] = "unauthorized"
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.code == "invalid_input"
    assert not (tmp_path / "run").exists()
