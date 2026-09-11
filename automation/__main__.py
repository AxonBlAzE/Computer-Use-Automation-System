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
    run.add_argument(
        "--handoff-config",
        type=Path,
        help="Enable same-session operator handoff (requires --headed)",
    )
    discovery = commands.add_parser("discover", help="Discover a capability using OpenRouter")
    discovery.add_argument("task", type=Path)
    discovery.add_argument("--inputs", type=Path, required=True)
    discovery.add_argument("--policy", type=Path, default=Path("examples/policy.json"))
    discovery.add_argument("--headed", action="store_true")
    discovery.add_argument("--evidence-dir", type=Path)
    discovery.add_argument(
        "--handoff-config",
        type=Path,
        help="Enable same-session operator handoff (requires --headed)",
    )
    discovery.add_argument("--model", help="OpenRouter model ID; overrides OPENROUTER_MODEL")
    discovery.add_argument(
        "--max-steps", type=int, default=24, choices=range(1, 49), metavar="1..48"
    )
    operator = commands.add_parser("operator", help="Control a paused local session")
    operator.add_argument("directory", type=Path)
    operator.add_argument("action", choices=["status", "resume", "abort"])
    operator.add_argument("--request-id", help="Reject commands for a different intervention")
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps(Capability.model_json_schema(), indent=2))
        return 0
    if args.command == "operator":
        from automation.session import send_command

        try:
            if args.action == "status":
                state = json.loads((args.directory / "intervention.json").read_text("utf-8"))
                print(json.dumps(state, indent=2))
            else:
                send_command(args.directory, args.action, args.request_id)
                print('{"status":"command_queued"}')
            return 0
        except (OSError, ValueError, KeyError):
            print('{"status":"failure","code":"operator_command_rejected"}')
            return 2
    try:
        if args.command == "replay":
            capability = Capability.model_validate_json(args.artifact.read_text(encoding="utf-8"))
        else:
            # Replay neither imports the model adapter nor reads .env.
            from automation.discovery_contracts import DiscoveryTask

            task = DiscoveryTask.model_validate_json(args.task.read_text(encoding="utf-8"))
        policy = Policy.model_validate_json(args.policy.read_text(encoding="utf-8"))
        inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be an object")
        handoff_config = None
        if args.handoff_config:
            from automation.session import HandoffConfig

            if not args.headed:
                raise ValueError("handoff requires --headed")
            handoff_config = HandoffConfig.model_validate_json(
                args.handoff_config.read_text(encoding="utf-8")
            )
            handoff_config.validate_inputs(inputs)
    except (OSError, ValueError, ValidationError):
        print('{"status":"failure","code":"invalid_configuration"}')
        return 2
    destination = args.evidence_dir or Path("runs") / uuid.uuid4().hex
    try:
        if args.command == "replay":
            result = asyncio.run(
                replay(
                    capability,
                    inputs,
                    policy,
                    destination,
                    headed=args.headed,
                    handoff_config=handoff_config,
                )
            )
        else:
            from automation.discovery import discover
            from automation.openrouter import ModelFailure, OpenRouterModel

            try:
                model = OpenRouterModel.from_environment(args.model)
            except ModelFailure:
                print('{"status":"failure","code":"missing_api_key"}')
                return 2
            result = asyncio.run(
                discover(
                    task,
                    inputs,
                    policy,
                    model,
                    destination,
                    headed=args.headed,
                    max_steps=args.max_steps,
                    handoff_config=handoff_config,
                )
            )
    except FileExistsError:
        print('{"status":"failure","code":"evidence_directory_exists"}')
        return 2
    print(result.model_dump_json(indent=2))
    print(f"Evidence destination: {destination}", file=sys.stderr)
    return 1 if result.status == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
