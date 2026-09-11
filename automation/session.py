"""Single-session ownership and a bounded local operator mailbox. No extra service."""

import asyncio
import json
import sys
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from automation.contracts import Check, Model, Target


class ResumeRule(Model):
    before: Target
    checks: list[Check] = Field(min_length=1)


class HandoffConfig(Model):
    timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    max_interventions: int = Field(default=3, ge=1, le=10)
    rules: list[ResumeRule] = Field(min_length=1)
    record_controls: dict[str, str] = Field(default_factory=dict)

    def validate_inputs(self, inputs):
        for rule in self.rules:
            for check in rule.checks:
                if check.equals and check.equals.source == "input":
                    if check.equals.name not in inputs:
                        raise ValueError("resume rule references an unknown input")


class OperatorCommand(Model):
    request_id: str
    action: Literal["resume", "abort"]


class SessionStopped(Exception):
    """Fixed error codes only; no observed page content."""


def write_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def send_command(directory: Path, action: str, request_id: str | None = None):
    state = json.loads((directory / "intervention.json").read_text(encoding="utf-8"))
    if state["state"] != "HUMAN":
        raise ValueError("session is not waiting for an operator")
    if request_id is not None and state["request_id"] != request_id:
        raise ValueError("stale intervention request")
    command = OperatorCommand(request_id=state["request_id"], action=action)
    # Unique filenames avoid half-written commands and allow concurrent local submitters.
    path = directory / f"operator-{uuid.uuid4().hex}.json"
    write_json(path, command.model_dump())


class SessionController:
    def __init__(self, config, directory, event, *, run_name, operator_driver=None):
        self.config = config
        self.directory = directory
        self.event = event
        self.run_name = run_name
        self.operator_driver = operator_driver  # Tests only; real CLI uses the mailbox.
        self.state = "AUTOMATION"
        self.session_id = uuid.uuid4().hex
        self.interventions = 0
        self.human_events = 0
        self.epoch = 0
        self.request = None
        self.lock = asyncio.Lock()

    def require_automation(self):
        if self.state != "AUTOMATION":
            raise SessionStopped("automation_does_not_own_session")

    def transition(self, state):
        previous = self.state
        self.state = state
        self.event("ownership_changed", session_id=self.session_id, previous=previous, state=state)
        if self.request is not None:
            self.request["state"] = state
            write_json(self.directory / "intervention.json", self.request)

    async def attach(self, surface):
        self.surface = surface

        def record(source, payload):
            if (
                self.state != "HUMAN"
                or source["page"] != surface.page
                or source["frame"] != surface.page.main_frame
                or not isinstance(payload, dict)
                or payload.get("epoch") != self.epoch
            ):
                return
            kind, tag = payload.get("kind"), payload.get("tag")
            if kind not in {"click", "input", "change"}:
                return
            if tag not in {"button", "input", "select", "textarea", "a", "other"}:
                return
            self.human_events += 1
            control = payload.get("control")
            if control not in self.config.record_controls.values():
                control = "unmapped"
            self.event(
                "human_action",
                session_id=self.session_id,
                request_id=self.request["request_id"],
                action=kind,
                tag=tag,
                control=control,
            )

        await surface.page.expose_binding("__recordOperatorEvent", record)
        # Capture only event category/control kind, never text, values, keys, IDs or URLs.
        recorder = """(() => {
            const controls = __CONTROL_MAP__;
            let chain = Promise.resolve();
            window.__operatorEpoch = 0;
            window.__flushOperatorEvents = () => chain;
            for (const kind of ['click', 'input', 'change']) {
                document.addEventListener(kind, event => {
                    if (!event.isTrusted || !window.__operatorEpoch) return;
                    const element = event.target.closest('button,input,select,textarea,a');
                    const label = element ? (element.getAttribute('aria-label') ||
                        (element.labels && element.labels.length ? element.labels[0].textContent :
                        ['BUTTON','A'].includes(element.tagName) ? element.textContent : '')
                        ).trim() : '';
                    const payload = {kind, tag: element ? element.tagName.toLowerCase() : 'other',
                                     control: controls[label] || 'unmapped',
                                     epoch: window.__operatorEpoch};
                    chain = chain.then(() => window.__recordOperatorEvent(payload)).catch(() => {});
                }, true);
            }
        })();"""
        await surface.page.add_init_script(
            recorder.replace("__CONTROL_MAP__", json.dumps(self.config.record_controls))
        )

        async def navigation(frame):
            if frame == surface.page.main_frame and self.state == "HUMAN":
                # A new document needs the current ownership epoch; never save its URL.
                with suppress(Exception):
                    await frame.evaluate("epoch => { window.__operatorEpoch = epoch; }", self.epoch)
                self.event(
                    "human_navigation",
                    session_id=self.session_id,
                    request_id=self.request["request_id"],
                )

        surface.page.on("framenavigated", navigation)

    async def handoff(self, step, inputs, rule):
        """Called under the surface action lock before any mutating action starts."""
        self.require_automation()
        if self.interventions >= self.config.max_interventions:
            raise SessionStopped("intervention_limit")
        self.interventions += 1
        request_id = uuid.uuid4().hex
        self.request = {
            "request_id": request_id,
            "session_id": self.session_id,
            "capability": self.run_name,
            "step": step.id,
            "reason": "blocked_before_action",
            "state": "PAUSED",
            "expected": "blocker removed and configured resume checks pass",
            "snapshot": f"intervention-{request_id}-dom.json",
            "operator_kind": "test_driver" if self.operator_driver else "local_operator",
        }
        self.transition("PAUSED")
        await self.surface.structural_snapshot(self.directory / self.request["snapshot"])
        self.event("intervention_requested", **self.request)
        self.epoch += 1
        await self.surface.page.evaluate("epoch => { window.__operatorEpoch = epoch; }", self.epoch)
        self.transition("HUMAN")
        print(
            f"Intervention {request_id}: automation paused before step {step.id}.\n"
            f"Resolve the blocker in the existing browser. Then run:\n"
            f'  python -m automation operator "{self.directory}" resume '
            f"--request-id {request_id}\n"
            f"Use abort instead of resume to stop.",
            file=sys.stderr,
        )
        driver = (
            asyncio.create_task(self.operator_driver(self, self.surface))
            if self.operator_driver
            else None
        )
        deadline = time.monotonic() + self.config.timeout_seconds
        try:
            while time.monotonic() < deadline:
                if self.surface.page.is_closed():
                    raise SessionStopped("operator_closed_session")
                if driver and driver.done():
                    driver.result()
                for path in sorted(self.directory.glob("operator-*.json")):
                    try:
                        command = OperatorCommand.model_validate_json(path.read_text("utf-8"))
                    except (ValueError, ValidationError):
                        self.event("operator_command_rejected", reason="invalid_command")
                        path.unlink()
                        continue
                    path.unlink()
                    if command.request_id != request_id or self.state != "HUMAN":
                        self.event("operator_command_rejected", reason="stale_request")
                        continue
                    if command.action == "abort":
                        self.event("operator_aborted", request_id=request_id)
                        raise SessionStopped("operator_aborted")
                    # Drain records from the human epoch before changing ownership.
                    await self.surface.page.evaluate("() => window.__flushOperatorEvents?.()")
                    self.transition("RESUME_VALIDATION")
                    try:
                        self.surface.guard()
                        if await self.surface.has_blocker():
                            raise ValueError("blocker remains")
                        for check in rule.checks:
                            expected = check.equals
                            value = (
                                (
                                    inputs[expected.name]
                                    if expected.source == "input"
                                    else expected.value
                                )
                                if expected
                                else None
                            )
                            await self.surface.target_ready(check.target, value, step=step.id)
                        # Verify availability without executing the pending action.
                        target = await self.surface.target_ready(step.target, step=step.id)
                        if not await target.is_enabled():
                            raise ValueError("control disabled")
                    except Exception:
                        self.event(
                            "resume_rejected",
                            request_id=request_id,
                            reason="resume_checkpoint_failed",
                        )
                        self.transition("HUMAN")
                        continue
                    if time.monotonic() >= deadline:
                        raise SessionStopped("intervention_timeout")
                    await self.surface.page.evaluate("() => { window.__operatorEpoch = 0; }")
                    self.event(
                        "resume_verified",
                        request_id=request_id,
                        session_id=self.session_id,
                        pending_step=step.id,
                    )
                    self.transition("AUTOMATION")
                    return
                await asyncio.sleep(0.1)
            raise SessionStopped("intervention_timeout")
        finally:
            if driver and not driver.done():
                driver.cancel()
                await asyncio.gather(driver, return_exceptions=True)

    def close(self):
        self.transition("CLOSED")


async def run_with_budget(awaitable, seconds, session=None):
    """Human waiting has its own deadline and does not consume the execution budget."""
    if session is None:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    task = asyncio.create_task(awaitable)
    remaining, previous = seconds, time.monotonic()
    try:
        while not task.done():
            paused = session.state in {"PAUSED", "HUMAN"}
            await asyncio.wait({task}, timeout=0.05)
            now = time.monotonic()
            if not paused:
                remaining -= now - previous
            previous = now
            if remaining <= 0:
                raise TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
