"""Real browser handoff with a simulated operator, never claimed as a human recording."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from playwright.async_api import Error as BrowserError
from test_discovery import ScriptedModel, fixtures

from automation.contracts import Capability, Click, Target
from automation.discovery import discover
from automation.policy import Policy
from automation.replay import replay
from automation.session import (
    HandoffConfig,
    SessionStopped,
    run_with_budget,
    send_command,
)


def setup(origin):
    cap = Capability.model_validate_json(
        Path("evidence/milestone-2/discovery-tools/capability.json").read_text()
    )
    policy = Policy.model_validate_json(Path("examples/policy.json").read_text())
    policy.origin = origin
    policy.timeout_ms = 300
    config = HandoffConfig.model_validate_json(Path("examples/handoff.json").read_text())
    inputs = json.loads(Path("examples/inputs.json").read_text())
    return cap, policy, config, inputs


def events(directory):
    return [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]


async def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("test driver timed out")
        await asyncio.sleep(0.02)


async def resolve_and_resume(session, surface):
    await surface.page.get_by_role("button", name="Resolve interruption", exact=True).click()
    send_command(session.directory, "resume", session.request["request_id"])


def test_same_session_handoff_and_operator_cli(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    directory = tmp_path / "run"
    identities = []

    async def operator(session, surface):
        original_page = surface.page
        identities.append(session.session_id)
        assert session.state == "HUMAN"
        with pytest.raises(SessionStopped, match="automation_does_not_own_session"):
            await surface.execute_step(
                Click(
                    action="click",
                    id="concurrent",
                    target=Target(role="button", name="New service request"),
                ),
                inputs,
            )
        await surface.page.get_by_role("button", name="Resolve interruption", exact=True).click()
        assert surface.page is original_page
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "automation",
            "operator",
            str(directory),
            "resume",
            "--request-id",
            session.request["request_id"],
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        assert process.returncode == 0, stdout

    result = asyncio.run(
        replay(cap, inputs, policy, directory, handoff_config=config, operator_driver=operator)
    )
    assert result.status == "success", result
    recorded = events(directory)
    assert [event["state"] for event in recorded if event["event"] == "ownership_changed"] == [
        "PAUSED",
        "HUMAN",
        "RESUME_VALIDATION",
        "AUTOMATION",
        "CLOSED",
    ]
    human = [event for event in recorded if event["event"] == "human_action"]
    assert any(event["action"] == "click" and event["tag"] == "button" for event in human)
    assert any(event["control"] == "resolve_interruption" for event in human)
    assert {event["session_id"] for event in recorded if "session_id" in event} == set(identities)
    assert json.loads((directory / "intervention.json").read_text())["state"] == "CLOSED"
    assert (
        sum(event["event"] == "step_completed" and event.get("index") == 3 for event in recorded)
        == 1
    )  # The search click was not repeated.
    for file in directory.glob("*.json*"):
        assert inputs["request_note"] not in file.read_text()
        assert inputs["member_id"] not in file.read_text()


def test_premature_resume_stays_human(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    directory = tmp_path / "run"

    async def operator(session, surface):
        send_command(directory, "resume")
        await wait_for(lambda: any(e["event"] == "resume_rejected" for e in events(directory)))
        assert session.state == "HUMAN"
        await resolve_and_resume(session, surface)

    result = asyncio.run(
        replay(cap, inputs, policy, directory, handoff_config=config, operator_driver=operator)
    )
    assert result.status == "success", result
    assert sum(e["event"] == "resume_verified" for e in events(directory)) == 1


def test_wrong_member_cannot_resume(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    directory = tmp_path / "run"

    async def operator(session, surface):
        await surface.page.goto(interruption_origin + "/members?member_id=67890")
        await surface.page.get_by_role("button", name="Resolve interruption", exact=True).click()
        send_command(directory, "resume")
        await wait_for(lambda: any(e["event"] == "resume_rejected" for e in events(directory)))
        assert session.state == "HUMAN"
        await surface.page.goto(interruption_origin + "/members?member_id=12345")
        await resolve_and_resume(session, surface)

    result = asyncio.run(
        replay(cap, inputs, policy, directory, handoff_config=config, operator_driver=operator)
    )
    assert result.status == "success", result
    assert result.outputs["member_id"] == "12345"


def test_abort_and_stale_request(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    directory = tmp_path / "run"

    async def operator(session, surface):
        with pytest.raises(ValueError, match="stale"):
            send_command(directory, "resume", "old-request")
        (directory / "operator-000.json").write_text(
            '{"request_id":"old-request","action":"resume"}'
        )
        send_command(directory, "abort")

    result = asyncio.run(
        replay(cap, inputs, policy, directory, handoff_config=config, operator_driver=operator)
    )
    assert result.code == "operator_aborted"
    assert any(e["event"] == "operator_command_rejected" for e in events(directory))
    assert not any(e["event"] == "resume_verified" for e in events(directory))
    assert json.loads((directory / "intervention.json").read_text())["state"] == "CLOSED"


def test_handoff_timeout_closes_session(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    config.timeout_seconds = 0.25

    async def idle(session, surface):
        await asyncio.sleep(10)

    result = asyncio.run(
        replay(cap, inputs, policy, tmp_path / "run", handoff_config=config, operator_driver=idle)
    )
    assert result.code == "intervention_timeout"


def test_missing_resume_rule_stops(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    config.rules[0].before = Target(role="button", name="Unrelated control")
    result = asyncio.run(
        replay(
            cap,
            inputs,
            policy,
            tmp_path / "run",
            handoff_config=config,
            operator_driver=resolve_and_resume,
        )
    )
    assert result.code == "resume_checkpoint_not_configured"


def test_no_handoff_option_stops_on_modal(interruption_origin, tmp_path):
    cap, policy, _, inputs = setup(interruption_origin)
    result = asyncio.run(replay(cap, inputs, policy, tmp_path / "run"))
    assert result.code == "intervention_required"


def test_discovery_reobserves_after_operator(interruption_origin, tmp_path):
    task, policy, inputs, actions, finish = fixtures(interruption_origin)
    config = HandoffConfig.model_validate_json(Path("examples/handoff.json").read_text())
    result = asyncio.run(
        discover(
            task,
            inputs,
            policy,
            ScriptedModel([*actions, finish]),
            tmp_path / "run",
            handoff_config=config,
            operator_driver=resolve_and_resume,
        )
    )
    assert result.status == "success", result
    provenance = json.loads((tmp_path / "run/provenance.json").read_text())
    assert provenance["human_interventions"] == 1
    cap = Capability.model_validate_json((tmp_path / "run/capability.json").read_text())
    assert all(
        getattr(s, "target", None) != Target(role="button", name="Resolve interruption")
        for s in cap.steps
    )


def test_human_wait_does_not_consume_automation_budget():
    class Session:
        state = "HUMAN"

    async def scenario():
        session = Session()

        async def task():
            await asyncio.sleep(0.2)
            session.state = "AUTOMATION"
            await asyncio.sleep(0.01)
            return "done"

        return await run_with_budget(task(), 0.1, session)

    assert asyncio.run(scenario()) == "done"


def test_operator_input_is_recorded_without_values(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)
    directory = tmp_path / "run"
    sentinel = "PRIVATE_OPERATOR_NOTE_123"

    async def operator(session, surface):
        await surface.page.goto(interruption_origin + "/request?member_id=12345")
        await surface.page.wait_for_function("window.__operatorEpoch > 0")
        await surface.page.get_by_role("textbox", name="Request note", exact=True).fill(sentinel)
        await surface.page.evaluate("() => window.__flushOperatorEvents()")
        await surface.page.goto(interruption_origin + "/members?member_id=12345")
        await resolve_and_resume(session, surface)

    result = asyncio.run(
        replay(cap, inputs, policy, directory, handoff_config=config, operator_driver=operator)
    )
    assert result.status == "success", result
    assert any(
        e["event"] == "human_action" and e["action"] == "input" and e["control"] == "request_note"
        for e in events(directory)
    )
    assert all(sentinel not in p.read_text() for p in directory.glob("*.json*"))


def test_route_policy_remains_active_during_handoff(interruption_origin, tmp_path):
    cap, policy, config, inputs = setup(interruption_origin)

    async def operator(session, surface):
        with pytest.raises(BrowserError):
            await surface.page.goto(interruption_origin + "/commit")
        assert surface.blocked
        send_command(session.directory, "abort")

    result = asyncio.run(
        replay(
            cap, inputs, policy, tmp_path / "run", handoff_config=config, operator_driver=operator
        )
    )
    assert result.code == "operator_aborted"


def test_discovery_no_progress_routes_to_operator(origin, tmp_path):
    task, policy, inputs, actions, finish = fixtures(origin)
    config = HandoffConfig.model_validate_json(Path("examples/handoff.json").read_text())
    repeated = [*actions[:3], actions[3], actions[3], actions[3], *actions[4:], finish]

    async def operator(session, surface):
        send_command(session.directory, "resume")

    result = asyncio.run(
        discover(
            task,
            inputs,
            policy,
            ScriptedModel(repeated),
            tmp_path / "run",
            handoff_config=config,
            operator_driver=operator,
        )
    )
    assert result.status == "success", result
    assert any(e["event"] == "resume_verified" for e in events(tmp_path / "run"))
