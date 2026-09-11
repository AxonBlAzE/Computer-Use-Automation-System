# Computer-Use Automation System — Design Report

## Architecture

The system learns a UI workflow once and executes a typed capability without a model
on subsequent invocations. I chose Python to keep the backend small: FastAPI serves a synthetic
target; Playwright operates its UI; Pydantic validates contracts; OpenRouter supplies
discovery decisions. One runner owns one browser context. JSON files replace a database.

Discovery and replay share the policy-checked `BrowserSurface.execute_step` implementation.
The model chooses actions from live accessibility observations; it cannot execute code.
Replay neither imports the model adapter nor reads `.env`. A separate local operator
command controls paused sessions. The runner never calls the target's business API or
reads its internal member data.

I built replay first with a hand-authored fixture to isolate executor correctness.
The later live discovery produced a separate artifact. Evidence records eight actual
OpenRouter calls; changed-input replay succeeded with invalid model credentials.

## Artifact schema

A capability declares schema/capability versions, typed inputs and outputs, ordered
actions, exact role/name targets, business-outcome markers, and a success checkpoint.
Strict discriminated unions reject unknown action fields. Explicit input references
separate invocation values from constants. Strings and string enums suffice for this flow.

The discovery task supplies a goal, output expectations, and known error rules, but
no action sequence. The model selects controls and output targets. Fill/select tools
accept input names, resolved locally, so parameterization does not depend on guessing
which transcript values should become variables. The compiler preserves executed steps,
adds output assertions, and binds configured outcomes to recorded clicks.

Completion is independently checked before publication. Error branches are operator
knowledge, not claimed to have been learned from a happy path. Artifacts contain no
executable snippets. A provenance hash detects accidental file changes; it is not a
signature or approval system. I initially exposed a nested decision schema to the
provider. After the live integration returned an invalid envelope, I switched to
separate typed tools while retaining strict internal validation.

## Determinism & error handling

Determinism means fixed execution rules without model decisions, not immutable business
data. Exact role/name targeting must resolve uniquely. Readiness checks wait within a
deadline; assertions verify the member and request type, then final readiness. Missing,
ambiguous, or mismatched targets stop rather than silently selecting a fallback.

The result contract distinguishes success with outputs, a business outcome such as
`member_not_found` or `validation_error`, and failure with a step, expected condition,
and sanitized observation. Slow loading is handled by bounded waiting. Recovery depth
is intentionally limited: I do not automatically retry clicks because a timed-out
write could already have completed. Unknown modal blockers can require an operator;
policy violations stop. Native dialogs retain conservative stop behavior.

Replay has a 60-second execution budget. Discovery additionally bounds decisions and
HTTP calls. Human waiting has a separate deadline. Tests cover real browser execution,
changed inputs, negative outcomes, policy blocking, false completion, and lifecycle
failures. Logs and structural failure snapshots support diagnosis without raw form values.

## Heterogeneity & multi-tenant

I implemented one browser surface with labeled controls and table-based pages,
without test IDs. I have not validated it against an inaccessible legacy application.
Browser-specific behavior lives in `BrowserSurface`, but its current schema and observation
method still assume accessibility roles, so supporting other surfaces requires changes
to both targeting and observation.

I would extend this with tagged target strategies and explicit frame/window scope.
Legacy web could use frame-scoped accessibility targets or configured visual anchors;
desktop could resolve equivalent controls through OS accessibility. Where those fail,
deterministic image/OCR matching would require fixed capture conditions, confidence and
uniqueness thresholds, and state checks. Unsupported strategies would fail at capability
validation. Replay would never silently switch to model reasoning or guessed coordinates.

For tenant reuse, I would store a reviewed vendor-level capability plus a constrained tenant
profile: entry origin, supported application version, locale/control aliases, and narrow
target overrides. Credentials and runtime values would stay outside both. I would validate
the composed artifact and policy per tenant so overrides cannot expand allowed actions.
I would pin base/profile versions, check application/version markers and required controls
before execution, and quarantine incompatible profiles. Changes would go to a small tenant
set before wider rollout. Independent browser contexts, namespaced evidence, access control, and
resource limits would be needed at scale; no tenant scheduler or storage system is built.

## Escalation & handoff

Ownership follows `AUTOMATION → PAUSED → HUMAN → RESUME_VALIDATION → AUTOMATION`.
Illegal transitions are rejected. Handoff happens before dispatch or after a pre-action
readiness failure, not by retrying an uncertain action. Discovery reobserves after takeover.

A request carries the capability, pending step, session/request IDs, reason, and structural
snapshot. The browser remains open. The operator acts in that same session and sends a
request-bound resume or abort command through an atomic local mailbox. The action lock
and ownership checks prevent the runner from acting during human control.

Resume checks both screen state and member identity; seeing the same button on the wrong
member is insufficient. Premature/invalid resume returns to human control. Timeout, abort,
or browser closure ends the run. Interaction telemetry records types and trusted control
aliases without values. Tests simulate the operator and invoke the actual CLI; saved
evidence is labeled accordingly. The README includes manual reproduction instructions.

## Safety

Trusted configuration separately allowlists origins/routes and action/target pairs.
The final-submit action and route are absent. HTTP request interception remains active
during operator control; handoff is not a policy override. Task content and UI observations
do not grant permissions. Model output is validated before execution.

Keys are loaded locally only for discovery. Input references avoid embedding invocation
values in artifacts. Known free-text values are replaced in model observations; other
visible text can still leave the machine. Persistent evidence omits raw observations,
screenshots, provider replies, and entered values. Outputs go to the caller on stdout.

These are safeguards for synthetic data, not production financial-data compliance. Exact
replacement is not general PII detection; GET-form URLs contain inputs. The local mailbox
is not authenticated remote access, and cooperative ownership does not lock OS input.
Malicious pages, downloads, WebSockets, and tamper-proof auditing need stronger boundaries.

## Cuts

The working slice covers discovery, compilation, replay, outcomes, policy, evidence, and
same-session intervention. I left out desktop/frame implementations, tenant infrastructure,
general workflow branching, numeric/object contracts, artifact approval, and a polished
operator console. No statistical reliability claim follows from one successful discovery.

Before production use, I would prioritize stronger data minimization and execution isolation,
authenticated operator access, uncertain-write reconciliation, broader runtime failures,
and validation against a legacy surface. The README provides
reproducible commands; evidence distinguishes live model runs from simulated operators.
