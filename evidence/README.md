# Evidence index

| Directory | Origin | What it establishes |
| --- | --- | --- |
| [milestone-1](milestone-1/README.md) | Real browser execution of a hand-authored fixture | Initial deterministic replay and business outcomes |
| [milestone-2](milestone-2/README.md) | Genuine OpenRouter discovery plus model-free replay | Discovered sequence, parameterized artifact, changed-input success and not-found outcome |
| [milestone-3](milestone-3/README.md) | Real Chromium and operator CLI, simulated operator | Same-session ownership, resume validation, wrong-member rejection, and abort |

The primary discovered artifact is
[discovery-tools/capability.json](milestone-2/discovery-tools/capability.json).
Its provenance records the model requests and hashes its exact bytes; a regression
test checks both that hash and agreement with the recorded executed action sequence.

I kept the original run logs to preserve the evidence at each milestone. Later
milestones were verified with offline tests; they do not include another live-model
discovery. Failure snapshots are structural, and observation hashes do not reconstruct
UI content. Manual handoff reproduction instructions are in the root README.
