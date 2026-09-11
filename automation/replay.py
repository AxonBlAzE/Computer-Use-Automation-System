"""Execute a reviewed capability against a live browser without model decisions."""

import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import Error as BrowserError
from playwright.async_api import Page, async_playwright

from automation.contracts import (
    BusinessOutcome,
    Capability,
    Check,
    Constant,
    Failure,
    InputRef,
    RunResult,
    Success,
    Target,
)
from automation.policy import Policy, PolicyDenied
from automation.session import SessionController, SessionStopped, run_with_budget


class ReplayStopped(Exception):
    def __init__(self, result: RunResult):
        self.result = result


class BrowserSurface:
    """Browser-specific targeting stays here, outside the capability model."""

    def __init__(self, page: Page, policy: Policy, session=None):
        self.page = page
        self.policy = policy
        self.blocked = False
        self.dialog_seen = False
        self.session = session

    async def has_blocker(self):
        dialogs = self.page.locator('dialog[open], [role="dialog"][aria-modal="true"]')
        for dialog in await dialogs.all():
            if await dialog.is_visible():
                return True
        return False

    async def intervene_if_blocked(self, inputs, step=None, *, force=False):
        if not force and not await self.has_blocker():
            return
        if not self.session:
            raise ReplayStopped(
                Failure(
                    code="intervention_required",
                    step=step.id if step else None,
                    expected="unblocked UI",
                    observed="modal blocks automation",
                )
            )
        rule = None
        for candidate in self.session.config.rules:
            if step is not None and step.action != "check" and candidate.before != step.target:
                continue
            locator = self.locate(candidate.before)
            if (
                step is not None
                and candidate.before == step.target
                or await locator.count() == 1
                and await locator.is_visible()
            ):
                rule = candidate
                break
        if rule is None:
            raise SessionStopped("resume_checkpoint_not_configured")
        pending = step or Check(id="discovery_observation", action="check", target=rule.before)
        await self.session.handoff(pending, inputs, rule)

    async def before_observation(self, inputs, *, force=False):
        if self.session:
            self.session.require_automation()
            async with self.session.lock:
                await self.intervene_if_blocked(inputs, force=force)
        else:
            await self.intervene_if_blocked(inputs, force=force)

    async def guard_request(self, route):
        try:
            self.policy.check_url(route.request.url)
        except PolicyDenied:
            self.blocked = True
            await route.abort()
        else:
            await route.continue_()

    async def dismiss_dialog(self, dialog):
        # This milestone stops; a later session controller will transfer to a human.
        self.dialog_seen = True
        await dialog.dismiss()

    def guard(self):
        if self.blocked:
            raise PolicyDenied("browser request was blocked")
        if self.dialog_seen:
            raise ReplayStopped(
                Failure(
                    code="intervention_required",
                    step=None,
                    expected="no unexpected dialog",
                    observed="browser dialog encountered",
                )
            )
        self.policy.check_url(self.page.url)

    def locate(self, target: Target):
        return self.page.get_by_role(target.role, name=target.name, exact=True)

    async def target_ready(self, target: Target, expected=None, *, inspect=None, step=None):
        deadline = time.monotonic() + self.policy.timeout_ms / 1000
        while True:
            self.guard()
            if inspect:
                await inspect()
            locator = self.locate(target)
            count = await locator.count()
            if count > 1:
                raise ReplayStopped(
                    Failure(
                        code="ambiguous_target",
                        step=step,
                        expected="exactly one matching control",
                        observed="multiple matches",
                    )
                )
            if count == 1 and await locator.is_visible():
                if expected is None or (await locator.inner_text()).strip() == expected:
                    return locator
            if time.monotonic() >= deadline:
                raise ReplayStopped(
                    Failure(
                        code="checkpoint_timeout",
                        step=step,
                        expected="unique visible target and declared checkpoint",
                        observed="target absent, hidden, or content did not match",
                    )
                )
            await asyncio.sleep(0.05)

    async def execute_step(self, step, inputs, *, inspect=None):
        """One policy-checked executor shared by discovery and deterministic replay."""
        if self.session:
            self.session.require_automation()
            async with self.session.lock:
                self.session.require_automation()
                return await self._execute_step(step, inputs, inspect=inspect)
        return await self._execute_step(step, inputs, inspect=inspect)

    async def _execute_step(self, step, inputs, *, inspect=None):

        def resolve(value):
            return inputs[value.name] if isinstance(value, InputRef) else value.value

        if step.action == "navigate":
            if self.page.url != "about:blank":
                self.guard()
            await self.page.goto(self.policy.url(step.path), wait_until="domcontentloaded")
        else:
            self.guard()
            if step.action != "check":
                self.policy.check_action(step.action, step.target)
            await self.intervene_if_blocked(inputs, step)
            expected = resolve(step.equals) if step.action == "check" and step.equals else None
            try:
                locator = await self.target_ready(
                    step.target,
                    expected,
                    inspect=inspect,
                    step=step.id,
                )
            except ReplayStopped as stopped:
                if (
                    not self.session
                    or getattr(stopped.result, "code", None) != "checkpoint_timeout"
                ):
                    raise
                # This wait failed before dispatch. Never use this path to retry a click.
                await self.intervene_if_blocked(inputs, step, force=True)
                locator = await self.target_ready(
                    step.target,
                    expected,
                    inspect=inspect,
                    step=step.id,
                )
            if step.action == "fill":
                await locator.fill(resolve(step.value))
            elif step.action == "select":
                await locator.select_option(resolve(step.value))
            elif step.action == "click":
                # Never retry a click: its business effect might already have happened.
                await locator.click()
        self.guard()

    async def structural_snapshot(self, path: Path):
        # Richer failure signal with no text, input values, URLs, or arbitrary attributes.
        nodes = await self.page.locator("body").evaluate("""body =>
            Array.from(body.querySelectorAll('*')).slice(0, 200).map(el => ({
                tag: el.tagName.toLowerCase(),
                role: ['heading','status','alert','button','textbox','combobox']
                    .includes(el.getAttribute('role')) ? el.getAttribute('role') : null,
                visible: !!(el.getClientRects().length),
                disabled: el.matches(':disabled')
            }))""")
        path.write_text(json.dumps(nodes, indent=2), encoding="utf-8")


async def replay(
    capability: Capability,
    inputs: dict[str, object],
    policy: Policy,
    evidence_dir: Path,
    *,
    headed: bool = False,
    handoff_config=None,
    operator_driver=None,
) -> RunResult:
    """Outputs go to the caller; persistent evidence deliberately excludes their values."""
    try:
        capability.validate_inputs(inputs)
        if handoff_config:
            handoff_config.validate_inputs(inputs)
            if not headed and operator_driver is None:
                raise ValueError("human handoff requires a headed browser")
    except ValueError:
        return Failure(
            code="invalid_input",
            step=None,
            expected="declared input contract",
            observed="invalid input shape or value",
        )

    evidence_dir.mkdir(parents=True, exist_ok=False)
    log = evidence_dir / "events.jsonl"
    current: str | None = None
    completed: set[str] = set()
    surface: BrowserSurface | None = None

    def event(kind: str, **fields):
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": kind, **fields}) + "\n")

    session = (
        SessionController(
            handoff_config,
            evidence_dir,
            event,
            run_name=capability.name,
            operator_driver=operator_driver,
        )
        if handoff_config
        else None
    )

    def resolve(value: InputRef | Constant) -> str:
        return inputs[value.name] if isinstance(value, InputRef) else value.value

    async def detect_outcome():
        for outcome in capability.outcomes:
            if outcome.after_step in completed:
                locator = surface.locate(outcome.target)
                count = await locator.count()
                if count > 1:
                    raise ReplayStopped(
                        Failure(
                            code="ambiguous_target",
                            step=current,
                            expected="one outcome marker",
                            observed="multiple matches",
                        )
                    )
                if count == 1 and await locator.is_visible():
                    raise ReplayStopped(BusinessOutcome(code=outcome.code, step=current))

    async def target_ready(target: Target, expected: str | None = None):
        return await surface.target_ready(target, expected, inspect=detect_outcome, step=current)

    async def execute():
        nonlocal current
        for index, step in enumerate(capability.steps):
            current = step.id
            event("step_started", index=index, action=step.action)
            await surface.execute_step(step, inputs, inspect=detect_outcome)
            completed.add(step.id)
            surface.guard()
            await detect_outcome()
            event("step_completed", index=index, action=step.action)

        current = capability.success.id
        await surface.before_observation(inputs)
        checkpoint: Check = capability.success
        await target_ready(
            checkpoint.target, resolve(checkpoint.equals) if checkpoint.equals else None
        )
        outputs = {}
        for name, output in capability.outputs.items():
            locator = await target_ready(output.target)
            value = (await locator.inner_text()).strip()
            if not output.field.accepts(value):
                raise ReplayStopped(
                    Failure(
                        code="invalid_output",
                        step=current,
                        expected="declared output contract",
                        observed="extracted value invalid",
                    )
                )
            outputs[name] = value
        return Success(outputs=outputs)

    event("run_started", schema_version=capability.schema_version)
    result: RunResult
    try:
        async with async_playwright() as browser_api:
            browser = await browser_api.chromium.launch(headless=not headed)
            try:
                context = await browser.new_context(service_workers="block")
                page = await context.new_page()
                surface = BrowserSurface(page, policy, session)
                page.set_default_timeout(policy.timeout_ms)
                await context.route("**/*", surface.guard_request)
                page.on("dialog", surface.dismiss_dialog)
                if session:
                    await session.attach(surface)
                try:
                    result = await run_with_budget(execute(), 60, session)
                except SessionStopped as stopped:
                    result = Failure(
                        code=str(stopped),
                        step=current,
                        expected="safe operator handoff and verified resume",
                        observed="session stopped without further automation",
                    )
                except ReplayStopped as stopped:
                    result = stopped.result
                    if isinstance(result, Failure) and result.step is None:
                        result.step = current
                except PolicyDenied:
                    result = Failure(
                        code="policy_denied",
                        step=current,
                        expected="allowlisted action and destination",
                        observed="policy rejected the operation",
                    )
                except TimeoutError:
                    result = Failure(
                        code="run_timeout",
                        step=current,
                        expected="completion within 60 seconds",
                        observed="run budget exhausted",
                    )
                except BrowserError:
                    result = Failure(
                        code="policy_denied" if surface.blocked else "browser_error",
                        step=current,
                        expected="permitted browser operation completes",
                        observed="request blocked"
                        if surface.blocked
                        else "browser operation failed",
                    )
                if isinstance(result, Failure):
                    try:
                        await asyncio.wait_for(
                            surface.structural_snapshot(evidence_dir / "failure-dom.json"),
                            timeout=2,
                        )
                    except (BrowserError, TimeoutError):
                        event("failure_snapshot_unavailable")
            finally:
                if session:
                    session.close()
                await browser.close()
    except BrowserError:
        result = Failure(
            code="browser_unavailable",
            step=current,
            expected="installed Chromium can launch",
            observed="browser launch or lifecycle failed",
        )
    event(
        "run_finished",
        status=result.status,
        **({"code": result.code} if not isinstance(result, Success) else {}),
    )
    return result
