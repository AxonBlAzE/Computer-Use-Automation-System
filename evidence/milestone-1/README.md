# Milestone 1 replay evidence

These logs were produced by real Chromium executions against the local FastAPI app.
The source capability is `examples/review-request.json`, a **hand-authored fixture**.
These runs do not demonstrate LLM discovery or human handoff.

Commands (with the demo server already running):

```sh
uv run python -m automation replay examples/review-request.json --inputs examples/inputs-second-member.json --evidence-dir evidence/milestone-1/replay-success
uv run python -m automation replay examples/review-request.json --inputs examples/inputs-not-found.json --evidence-dir evidence/milestone-1/replay-not-found
```

Use new evidence destinations when repeating; replay refuses to overwrite existing runs.

- `replay-success/events.jsonl`: member `67890`, request type `address`; returned
  `success` with `review_status: ready` after checking member and request identity.
- `replay-not-found/events.jsonl`: member `99999`; returned `business_outcome`,
  code `member_not_found`, at step `search`.

The values above are synthetic fixture values. Persistent execution logs intentionally
exclude input values, extracted outputs, URLs, and page text.

Validation at this milestone: 20 pytest tests passed, including real Chromium replay,
slow loading, validation outcomes, blocked final submission, checkpoint verification,
and failure-evidence redaction. Ruff checks passed.
