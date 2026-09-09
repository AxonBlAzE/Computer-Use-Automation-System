import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from automation.contracts import Capability
from automation.policy import Policy, PolicyDenied


def fixture():
    return json.loads(Path("examples/review-request.json").read_text())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.update(schema_version="2.0"),
        lambda c: c["steps"][1]["value"].update(name="undeclared"),
        lambda c: c["steps"][1].update(id="open"),
        lambda c: c["steps"][0].update(script="arbitrary code"),
        lambda c: c["outcomes"][0].update(after_step="missing"),
    ],
)
def test_rejects_invalid_artifacts(mutation):
    document = fixture()
    mutation(document)
    with pytest.raises(ValidationError):
        Capability.model_validate(document)


def test_inputs_are_strict_and_parameterized():
    capability = Capability.model_validate(fixture())
    inputs = json.loads(Path("examples/inputs.json").read_text())
    capability.validate_inputs(inputs)
    inputs["member_id"] = 12345
    with pytest.raises(ValueError):
        capability.validate_inputs(inputs)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://127.0.0.1:8000/commit",
        "http://127.0.0.1:8000/review/extra",
        "http://localhost:8000/",
        "http://127.0.0.1:8001/",
        "file:///etc/passwd",
    ],
)
def test_policy_rejects_unapproved_destinations(url):
    policy = Policy.model_validate_json(Path("examples/policy.json").read_text())
    with pytest.raises(PolicyDenied):
        policy.check_url(url)
