from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bundle import (
    BundleBuildError,
    build_canonical_bundle,
    build_game_vocal_bundle,
    build_muscriptor_multitrack_bundle,
    parse_candidate,
)
from .canonical import CanonicalValidationError
from .contracts import ContractValidationError
from .doctor import checks_as_dict, required_checks_pass, run_doctor
from .events import EventValidationError, read_jsonl
from .midi import MidiExportError
from .project import ProjectError, initialize_project, load_project
from .workers import muscriptor_baseline_command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amt", description="AMT Studio orchestration core")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local prerequisites")
    doctor.add_argument("--json", action="store_true", help="Emit JSON")

    init_project = subparsers.add_parser("init-project", help="Create a private song project")
    init_project.add_argument("audio", type=Path)
    init_project.add_argument("--output", type=Path, required=True)
    init_project.add_argument("--title")
    init_project.add_argument(
        "--reference-original",
        action="store_true",
        help="Do not copy the original into the project; canonical audio is still created",
    )

    show = subparsers.add_parser("show", help="Show a project manifest")
    show.add_argument("project", type=Path)

    validate_events = subparsers.add_parser("validate-events", help="Validate canonical JSONL")
    validate_events.add_argument("events", type=Path)

    command = subparsers.add_parser(
        "worker-command", help="Print a suggested command for an isolated worker"
    )
    command.add_argument("worker", choices=["muscriptor"])
    command.add_argument("project", type=Path)
    command.add_argument("--model", default="large")

    canonical = subparsers.add_parser(
        "build-canonical",
        help="Build a Task005 canonical bundle from immutable worker results",
    )
    canonical.add_argument("project", type=Path)
    canonical.add_argument("--beat-run", type=Path, required=True)
    canonical.add_argument(
        "--candidate",
        action="append",
        required=True,
        metavar="LABEL=RUN_DIR",
    )
    canonical.add_argument("--output", type=Path, required=True)
    canonical.add_argument("--score-subdivision", type=int, default=4)

    muscriptor_bundle = subparsers.add_parser(
        "build-muscriptor-multitrack",
        help="Split one MuScriptor full-song run into an editable multitrack bundle",
    )
    muscriptor_bundle.add_argument("project", type=Path)
    muscriptor_bundle.add_argument("--run", type=Path, required=True)
    muscriptor_bundle.add_argument("--output", type=Path, required=True)
    muscriptor_bundle.add_argument("--default-bpm", type=float, default=120.0)
    muscriptor_bundle.add_argument(
        "--beat-run",
        type=Path,
        help="Optional verified Beat This run used for BPM, meter, and beat positions",
    )

    game_bundle = subparsers.add_parser(
        "build-game-vocal",
        help="Build a one-track singing-voice bundle from a verified GAME run",
    )
    game_bundle.add_argument("project", type=Path)
    game_bundle.add_argument("--run", type=Path, required=True)
    game_bundle.add_argument("--output", type=Path, required=True)
    game_bundle.add_argument("--default-bpm", type=float, default=120.0)
    game_bundle.add_argument(
        "--beat-run",
        type=Path,
        help="Optional verified Beat This run used for BPM, meter, and beat positions",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            checks = run_doctor()
            if args.json:
                print(json.dumps(checks_as_dict(checks), ensure_ascii=False, indent=2))
            else:
                for check in checks:
                    marker = "OK" if check.ok else ("MISSING" if check.required else "OPTIONAL")
                    print(f"[{marker:8}] {check.name}: {check.detail}")
            return 0 if required_checks_pass(checks) else 2

        if args.command == "init-project":
            manifest = initialize_project(
                args.audio,
                args.output,
                title=args.title,
                copy_original=not args.reference_original,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0

        if args.command == "show":
            print(json.dumps(load_project(args.project), ensure_ascii=False, indent=2))
            return 0

        if args.command == "validate-events":
            events = read_jsonl(args.events)
            print(json.dumps({"valid": True, "event_count": len(events)}, indent=2))
            return 0

        if args.command == "worker-command":
            worker = muscriptor_baseline_command(args.project, model=args.model)
            print(
                json.dumps(
                    {"name": worker.name, "argv": worker.argv, "notes": worker.notes},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "build-canonical":
            candidates: dict[str, Path] = {}
            for value in args.candidate:
                label, run_dir = parse_candidate(value)
                if label in candidates:
                    raise BundleBuildError(f"duplicate candidate label: {label}")
                candidates[label] = run_dir
            manifest = build_canonical_bundle(
                args.project,
                args.beat_run,
                candidates,
                args.output,
                score_subdivision=args.score_subdivision,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0

        if args.command == "build-muscriptor-multitrack":
            manifest = build_muscriptor_multitrack_bundle(
                args.project,
                args.run,
                args.output,
                default_bpm=args.default_bpm,
                beat_run_dir=args.beat_run,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0

        if args.command == "build-game-vocal":
            manifest = build_game_vocal_bundle(
                args.project,
                args.run,
                args.output,
                default_bpm=args.default_bpm,
                beat_run_dir=args.beat_run,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0

        raise AssertionError(f"Unhandled command: {args.command}")
    except (
        BundleBuildError,
        CanonicalValidationError,
        ContractValidationError,
        EventValidationError,
        MidiExportError,
        ProjectError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
