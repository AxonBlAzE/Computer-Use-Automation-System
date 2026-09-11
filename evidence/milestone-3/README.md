# Milestone 3: same-session handoff verification

Recorded 2026-09-11 by real Chromium integration tests against the synthetic FastAPI
app with `DEMO_INTERRUPT=1`. **The operator is simulated by the test driver.** This is
not a recording of a person, and no new live LLM run is claimed for this milestone.

The runtime mechanism itself is real: the same browser stays open, automated actions
are blocked during HUMAN ownership, operator interaction is captured, and a separate
operator CLI can send a request-bound resume signal through the local mailbox.

## Included runs

- `same-session/`: the test driver clears the blocker in the original page and invokes
  the actual operator CLI in another process. Resume validates member identity and the
  pending control. Replay completes successfully. One session ID links the transitions.
- `wrong-member/`: the driver navigates to another member and requests resume. The
  identity checkpoint rejects it. Returning to the intended member allows completion.
- `abort/`: stale request handling and operator abort. No verified resume occurs.

Each directory contains the original test-produced event log, final intervention state,
and structural snapshots. Events explicitly mark `operator_kind: test_driver`. Human
action events record type, control kind, and trusted aliases such as `resolve_interruption`,
without field values. These are copied test outputs, not hand-written illustrations.

## Reproduce

```sh
uv run pytest tests/test_handoff.py -v
```

At this milestone, the full suite passed 45 tests, including 12 handoff tests covering the above scenarios plus premature resume,
timeouts, missing resume configuration, no handoff option, discovery reobservation,
discovery no-progress escalation, pause-aware budgets, input redaction, and route-policy
enforcement while the operator owns the browser. These tests do not use model credits.

The three-terminal **Manual handoff demo** in the root README reproduces the flow with
a person operating the browser. It uses the saved milestone-2 capability unchanged.
