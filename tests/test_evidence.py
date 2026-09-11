"""Guard the checked-in live-run evidence against accidental semantic edits."""

import hashlib
import json
from pathlib import Path

from automation.contracts import Capability


def test_live_discovery_artifact_matches_recorded_actions_and_hash():
    directory = Path("evidence/milestone-2/discovery-tools")
    payload = (directory / "capability.json").read_bytes()
    provenance = json.loads((directory / "provenance.json").read_text())
    assert hashlib.sha256(payload).hexdigest() == provenance["capability_sha256"]
    capability = Capability.model_validate_json(payload)
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    executed = [event["step"] for event in events if event["event"] == "action_completed"]
    recorded = [step.model_dump() for step in capability.steps[1 : 1 + len(executed)]]
    assert recorded == executed
    assert events[-1]["status"] == "success"
    responses = [event for event in events if event["event"] == "model_responded"]
    assert len(responses) == len(provenance["model_calls"]) == 8
    assert {response["provider_request_id"] for response in responses} == {
        call["provider_request_id"] for call in provenance["model_calls"]
    }
