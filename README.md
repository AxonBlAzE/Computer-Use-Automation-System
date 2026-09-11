# Computer-Use Automation System

Milestone 2: an OpenRouter model discovers a workflow on a synthetic FastAPI banking UI,
then a saved typed capability replays through Playwright without model decisions.
Discovery needs an API key; replay and automated tests do not.

`examples/review-request.json` is the original hand-authored fixture.
`evidence/milestone-2/discovery-tools/capability.json` was produced by a genuine model
run and successfully replayed with different inputs. Human takeover is still a future milestone.

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
- Unexpected browser dialogs are dismissed and return `intervention_required`; this is
  **not** a human handoff implementation. In-page unknown states fail their checkpoints.
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
- Real handoff, desktop support, multi-tenant implementation, and the final assessment
  report remain subsequent milestones.
