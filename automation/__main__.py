import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from automation.contracts import Capability
from automation.policy import Policy
from automation.replay import replay


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic UI capability replay")
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", help="Print the capability JSON Schema")
    schema.set_defaults(command="schema")
    run = commands.add_parser("replay")
    run.add_argument("artifact", type=Path)
    run.add_argument("--inputs", type=Path, required=True)
    run.add_argument("--policy", type=Path, default=Path("examples/policy.json"))
    run.add_argument("--headed", action="store_true")
    run.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps(Capability.model_json_schema(), indent=2))
        return 0
    try:
        capability = Capability.model_validate_json(args.artifact.read_text(encoding="utf-8"))
        policy = Policy.model_validate_json(args.policy.read_text(encoding="utf-8"))
        inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be an object")
    except (OSError, ValueError, ValidationError):
        print('{"status":"failure","code":"invalid_configuration"}')
        return 2
    destination = args.evidence_dir or Path("runs") / uuid.uuid4().hex
    try:
        result = asyncio.run(replay(capability, inputs, policy, destination, headed=args.headed))
    except FileExistsError:
        print('{"status":"failure","code":"evidence_directory_exists"}')
        return 2
    print(result.model_dump_json(indent=2))
    print(f"Evidence destination: {destination}", file=sys.stderr)
    return 1 if result.status == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
