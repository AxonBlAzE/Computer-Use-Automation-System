# Milestone 2 — genuine discovery and deterministic replay

Recorded on 2026-09-10 against the local synthetic FastAPI app. No model response was
manually edited into the successful artifact.

## Successful run

- `discovery-tools/events.jsonl`: eight actual OpenRouter calls, seven model-selected
  UI actions, and independently verified completion in approximately 23 seconds.
- `discovery-tools/capability.json`: emitted from the executed actions. Entry navigation
  comes from the task; final assertions come from declared output expectations.
- `discovery-tools/provenance.json`: provider request IDs, model ID, token counts, and
  SHA-256 of the exact capability bytes.
- `replay-second-member/events.jsonl`: success for synthetic member `67890`, request
  type `address`, review status `ready`.
- `replay-not-found/events.jsonl`: `member_not_found` business outcome at step `s003`
  for synthetic member `99999`.

The discovery model was `anthropic/claude-sonnet-4.5` through OpenRouter. The task was
`examples/discovery-task.json`, with runtime values from `examples/inputs.json`.
The discovery code does not load `examples/review-request.json` or its action sequence.

Known business-outcome rules are explicitly operator-authored in the task contract.
The model selected the action sequence and output targets; the compiler bound outcome
rules to matching recorded clicks and generated output assertions. I kept error rules
in the task contract because a successful trace cannot establish unseen error behavior.

## Commands

With the demo server running:

```sh
uv run python -m automation discover examples/discovery-task.json --inputs examples/inputs.json --evidence-dir runs/new-discovery
uv run python -m automation replay runs/new-discovery/capability.json --inputs examples/inputs-second-member.json
uv run python -m automation replay runs/new-discovery/capability.json --inputs examples/inputs-not-found.json
```

The saved replay runs used the capability under `discovery-tools/`. Both were executed
with `OPENROUTER_API_KEY=disabled-for-replay` and `OPENROUTER_MODEL=disabled/invalid`
in the replay process. Replay does not load `.env` or import the model adapter and ran
inside the network-restricted environment with only local UI access.

## Failed attempts preserved

- `discovery/`: initial request returned HTTP 404. The model was listed in OpenRouter's
  catalog; removing `parallel_tool_calls` while retaining required-parameter routing
  allowed the next request through. This suggests a parameter-routing incompatibility;
  no raw provider error body was retained to establish a more specific diagnosis.
- `discovery-verified/`: the original nested decision-envelope schema returned an
  invalid response; no model action executed and no capability was published.
- Subsequent one-call diagnostics under ignored `runs/` localized a `dict_type` error
  to the envelope's `decision` field. I replaced that envelope at the provider boundary
  with separate typed tools, which produced the successful run above.

No raw API responses, credentials, or model reasoning are included. The successful
logs record fixed intent categories and validated actions, not a full transcript.
Observation hashes identify the in-memory observations but cannot reconstruct them.
Synthetic fixture values appear in this explanation; they are not real customer data.

Final integrity verification caught a Windows newline mismatch in the initial hash
calculation. The writer now hashes the saved bytes and emits LF line endings; the saved
artifact was normalized to LF and its hash corrected. No actions, targets, or other
semantic content changed. `.gitattributes` preserves evidence line endings on checkout.

## Limits

This evidence demonstrates one discovery and changed-input replay on the controlled surface.
It does not establish statistical reliability, human handoff, legacy-frame support,
desktop support, or tenant generalization. Automated tests use an explicitly scripted
offline model; those tests do not substitute for the live discovery evidence here.
