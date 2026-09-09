# Computer-Use Automation System

Milestone 1: a typed capability contract, a synthetic FastAPI banking UI, and a
deterministic Playwright replay executor. No LLM or API key is needed for this milestone.

The example artifact is **hand-authored**, not evidence of model discovery. Genuine
LLM discovery and same-session human takeover are future milestones.

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
- Evidence excludes page text, field values, URLs, model transcripts, and raw screenshots.
  Failure snapshots retain only structural tags, allowlisted roles, visibility, and disabled state.
- The route guard and action allowlist are safeguards for this controlled target, not a
  complete security boundary against malicious applications, WebSockets, popups, or downloads.
  Policy authors are trusted. Final-submit permission is absent rather than inferred from labels.
- The demo uses synthetic data and GET forms for simplicity; do not use real PII, credentials,
  externally exposed hosting, or production data with it. Browser URLs contain entered values.
- No model discovery, real handoff, desktop support, multi-tenant implementation, or final
  assessment report is claimed. These remain subsequent milestones.
