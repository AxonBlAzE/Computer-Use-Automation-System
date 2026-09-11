# Computer-Use Automation System

Milestone 3: an OpenRouter model discovers a workflow on a synthetic FastAPI banking UI,
then a saved typed capability replays through Playwright without model decisions.
Optional operator handoff pauses before an action, preserves the live browser, and
requires verified checkpoints before resuming.
Discovery needs an API key; replay and automated tests do not.

`examples/review-request.json` is the original hand-authored fixture.
`evidence/milestone-2/discovery-tools/capability.json` was produced by a genuine model
run and successfully replayed with different inputs. Operator handoff is implemented
and browser-tested with a simulated operator; a person can run the manual demo below.

## Setup

Use Python 3.11+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```sh
uv sync --locked
uv run playwright install chromium
```

On Linux, browser system dependencies may also require `uv run playwright install --with-deps chromium`.

For the already provisioned Windows workspace, dependencies are in `.venv` and Chromium
is in `.browsers`. In each PowerShell terminal, set
`$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.browsers"`, then replace `uv run python` with
`.venv/Scripts/python.exe` and `uv run uvicorn` with `.venv/Scripts/python.exe -m uvicorn`.
The portable `uv` setup above remains the recommended path for a fresh checkout.

## Run the demo

Start the synthetic target app in one terminal (disable access logs because demo forms
use GET query parameters):

```sh
uv run uvicorn demo_app.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000 to inspect the target manually. Only synthetic members
`12345` and `67890` exist. In a second terminal:

```sh
uv run python -m automation replay examples/review-request.json --inputs examples/inputs.json --headed
uv run python -m automation replay examples/review-request.json --inputs examples/inputs-second-member.json
uv run python -m automation replay examples/review-request.json --inputs examples/inputs-not-found.json
```

The first two runs return `success` with the supplied member ID, request type, and
`review_status: ready`. The third returns `business_outcome` with `member_not_found`.
Exit status is 0 for success/business outcomes, 1 for execution failure, 2 for invalid
configuration. Remove `--headed` to run headlessly.

Real CLI replay logs are included in `evidence/milestone-1/`, with their provenance
and commands documented there. The milestone passed 20 tests, including browser integration.

## Discover, then replay

Keep the demo server running. Put your OpenRouter key in the repository-root `.env`:

```dotenv
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
```

`.env` is ignored by Git; `.env.example` contains placeholders only. Discovery loads
this file without overriding existing environment variables. `--model` overrides the
model setting. Replay never loads `.env` or imports the OpenRouter adapter.

```sh
uv run python -m automation discover examples/discovery-task.json --inputs examples/inputs.json --evidence-dir runs/my-discovery --headed
uv run python -m automation replay runs/my-discovery/capability.json --inputs examples/inputs-second-member.json --headed
uv run python -m automation replay runs/my-discovery/capability.json --inputs examples/inputs-not-found.json
```

Choose a new discovery destination each time; directories are never overwritten.
For the provisioned Windows environment, use the `.venv` substitutions and browser
environment variable from Setup. No new API calls are needed to demo the saved capability:

```sh
uv run python -m automation replay evidence/milestone-2/discovery-tools/capability.json --inputs examples/inputs-second-member.json --headed
```

The task file contains a natural-language goal, typed inputs, output expectations, and
operator-supplied business-outcome rules. It contains **no ordered action sequence**.
The model observes the live accessibility snapshot and chooses one typed tool at a time.
Fill/select tools accept input names; Python resolves the values locally. The model
chooses output targets, and Python verifies their values before publishing a capability.
Output assertions are generated from the task contract. Outcome rules are bound to
the discovered clicks; they are not inferred from a successful trace.

Discovery defaults to at most 24 decisions, 45 seconds per HTTP call, and 240 seconds
overall. `--max-steps` accepts 1–48. Repeated identical decisions against unchanged
observations stop as `no_progress`. API errors, malformed decisions, policy violations,
and failed completion checks stop without publishing a capability. There are no
automatic model-call retries or model fallbacks.

Discovery evidence includes executed parameterized actions, intent categories, model
request IDs/token counts, observation hashes, and an artifact hash. Raw conversations
and page snapshots are not persisted. Exact known free-text input values are replaced
in observations before sending them to OpenRouter; other visible page text is still
sent, so use synthetic data only. This is not a general PII detection system.

The successful live run made eight calls using `anthropic/claude-sonnet-4.5` and took
about 23 seconds. Its generated artifact replayed for member `67890` with request type
`address`, and returned `member_not_found` for `99999`. Both replays ran with invalid
model credentials and an invalid model ID. See `evidence/milestone-2/README.md`.

Each valid run creates a unique `runs/<id>/events.jsonl`; failures also attempt a
sanitized structural `failure-dom.json`. Use `--evidence-dir <new-directory>` to choose
the destination. Existing directories are never overwritten. Declared outputs are
returned on stdout, not persisted into the event log. Treat stdout as potentially sensitive.

## Manual handoff demo

This demo reuses the saved model-generated capability; it needs no model credits.
The injected runtime interruption is part of the target app, not an extra recorded step.
Use three PowerShell terminals, all in the repository root.

**Terminal 1:** stop an existing demo server with Ctrl+C, then start it with the blocker:

```powershell
$env:DEMO_INTERRUPT = "1"
.venv\Scripts\python.exe -m uvicorn demo_app.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

**Terminal 2:** start replay with a visible browser and operator configuration:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/.browsers"
.venv\Scripts\python.exe -m automation replay evidence/milestone-2/discovery-tools/capability.json --inputs examples/inputs.json --headed --handoff-config examples/handoff.json --evidence-dir runs/my-handoff
```

Choose a new run directory each time. Replay finds the member, sees the interruption,
and prints an intervention request. The original browser remains open.

**Terminal 3:** inspect the request:

```powershell
.venv\Scripts\python.exe -m automation operator runs/my-handoff status
```

Click **Resolve interruption** in the browser opened by replay. Do not advance to the
next screen manually. Then signal resume:

```powershell
.venv\Scripts\python.exe -m automation operator runs/my-handoff resume
```

The runner checks that the modal is gone, the member ID still matches the invocation,
the Member details screen is present, and the pending control is enabled. It then
continues the original run and returns success. To stop instead:

```powershell
.venv\Scripts\python.exe -m automation operator runs/my-handoff abort
```

The runner also prints a command with `--request-id` to protect against submitting a
command for a different intervention. Without it, the CLI addresses the currently
displayed request. Commands for expired requests are rejected.

Try `resume` before resolving the modal: validation fails and ownership stays HUMAN.
Aborting or waiting beyond the configured 180-second deadline closes the run. To return
to the normal demo, stop Terminal 1's server, remove the environment variable with
`Remove-Item Env:DEMO_INTERRUPT`, and restart the server.

The same `--headed --handoff-config examples/handoff.json` options work with `discover`.
Discovery reobserves after handoff rather than executing an old model decision. A
configured checkpoint can also support handoff after repeated no-progress decisions
or a pre-action target timeout. Unconfigured resume locations stop conservatively.

`intervention.json` shows the current state; event logs preserve ownership transitions,
the same session ID, resume acceptance/rejection, and operator interactions. Control
names are mapped to trusted aliases; field values, keystrokes, and raw URLs are omitted.
DOM snapshots are structural only. The mailbox is a local filesystem interface for a
trusted operator, not an authenticated remote operator service.

## Contract and execution

```sh
uv run python -m automation schema
uv run pytest -q
uv run ruff check .
```

- `automation/contracts.py`: strict Pydantic discriminated action types, explicit input
  references, versioned capabilities, typed string outputs, checkpoints, and outcomes.
- `automation/replay.py`: bounded execution with exact role/name targets. Ambiguous
  targets stop execution. Readiness checks poll within a deadline; clicks are never retried.
- `automation/policy.py`: trusted origin/route and action/target allowlists, configured
  independently in `examples/policy.json`. `/commit` and the Submit button are disallowed.
- `automation/discovery_contracts.py`: task intent and output expectations, separate from steps.
- `automation/discovery.py`: bounded observation/decision loop and artifact compilation.
- `automation/openrouter.py`: direct HTTP tool-calling adapter, strict response validation,
  and discovery-only `.env` loading. Simple tool schemas keep the provider boundary small.
- `automation/session.py`: ownership, local operator commands, bounded waiting, action
  recording, and checkpoint validation. `examples/handoff.json` is trusted operator configuration.
- `demo_app/app.py`: multi-page search, member detail, request form, and review flow.

Every run uses a fresh browser context. Replay validates invocation inputs before
launching Chromium, verifies member and request identity, validates final success,
and extracts declared outputs. It never reads the demo's internal data or calls a
business API. Both invalid form notes and missing members have explicit outcomes.

## Scope and limits

- This milestone supports exact accessible role/name targeting on one browser surface.
  `BrowserSurface` holds browser-specific behavior; frame/desktop adapters are not implemented.
- The input/output type vocabulary deliberately supports strings and string enums only.
- A `slow` scenario demonstrates bounded loading; no write retries or automated recovery
  after uncertain side effects are implemented.
- Handoff supports in-page modal blockers and configured pre-action checkpoints. Native
  browser dialogs retain stop behavior; they are not handed over mid-action. Failed or
  uncertain in-flight clicks are never automatically retried.
- Operator waiting has its own deadline and does not consume the automation execution
  budget. At most three interventions are allowed by the example configuration.
- Ownership is enforced inside the runner, not by locking the OS mouse/keyboard. A
  cooperative operator should touch the browser only while the request says HUMAN.
  HTTP route policy remains active during human ownership; handoff is not a policy override.
- Browser interaction capture is lightweight telemetry, not an immutable audit trail or
  a complete recording. Unmapped controls are recorded by control kind only; interactions
  are not converted automatically into reusable capability steps.
- Persistent observations exclude page text, field values, URLs, transcripts, and screenshots.
  Discovery additionally records validated target labels and parameter references.
  Failure snapshots retain only structural tags, allowlisted roles, visibility, and disabled state.
- The route guard and action allowlist are safeguards for this controlled target, not a
  complete security boundary against malicious applications, WebSockets, popups, or downloads.
  Policy authors are trusted. Final-submit permission is absent rather than inferred from labels.
- The demo uses synthetic data and GET forms for simplicity; do not use real PII, credentials,
  externally exposed hosting, or production data with it. Browser URLs contain entered values.
- Discovery currently requires a task contract; arbitrary goals without declared output
  expectations are not supported. The model does not invent outcome rules or policies.
- Desktop support, multi-tenant implementation, and the final assessment report remain
  outstanding. Handoff evidence uses a simulated operator and is labeled accordingly.
