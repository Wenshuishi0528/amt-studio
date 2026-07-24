from __future__ import annotations

import argparse
import json
import subprocess
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file


class ListeningReviewError(RuntimeError):
    """Raised when a listening-review package cannot be prepared."""


def validate_candidate_label(label: str) -> str:
    if not isinstance(label, str) or not label:
        raise ValueError("Candidate label must be a non-empty string")
    if label != label.strip():
        raise ValueError(f"Candidate label has leading or trailing whitespace: {label!r}")
    if label in {".", ".."}:
        raise ValueError(f"Candidate label cannot be a traversal component: {label!r}")
    if Path(label).is_absolute() or "/" in label or "\\" in label:
        raise ValueError(f"Candidate label must be one filename component: {label!r}")
    if any(unicodedata.category(character).startswith("C") for character in label):
        raise ValueError(f"Candidate label contains a control character: {label!r}")
    if label.startswith(".") or any(
        not (character.isalnum() or character in {"-", "_", "."}) for character in label
    ):
        raise ValueError(f"Candidate label contains an unsafe filename character: {label!r}")
    if unicodedata.normalize("NFKC", label).casefold() == "mix":
        raise ValueError(f"Candidate label is reserved for the original mix: {label!r}")
    return label


def validate_candidate_labels(labels: list[str]) -> None:
    normalized_labels: dict[str, str] = {}
    for label in labels:
        validate_candidate_label(label)
        normalized = unicodedata.normalize("NFKC", label).casefold()
        if normalized in normalized_labels:
            raise ValueError(
                "Candidate labels collide as filename components: "
                f"{normalized_labels[normalized]!r} and {label!r}"
            )
        normalized_labels[normalized] = label


def load_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Invalid --candidate value: {value}")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise ValueError(f"Invalid --candidate value: {value}")
    return validate_candidate_label(label), Path(raw_path).expanduser().resolve()


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_manifest.json"
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("worker") != "separator" or manifest.get("status") != "succeeded":
        raise ListeningReviewError(f"Candidate is not a succeeded separator run: {path}")
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise ListeningReviewError(f"Candidate has no run_id: {path}")
    return manifest


def verified_vocals(
    run_dir: Path,
    manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    relative_path = "raw/stems/vocals.flac"
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ListeningReviewError("Candidate manifest outputs must be a list")
    records = [
        record
        for record in outputs
        if isinstance(record, dict) and record.get("path") == relative_path
    ]
    if len(records) != 1:
        raise ListeningReviewError(
            f"Candidate manifest must contain exactly one output for {relative_path}"
        )

    vocals = run_dir / relative_path
    if not vocals.is_file():
        raise ListeningReviewError(f"Candidate vocals are missing: {vocals}")
    record = records[0]
    actual_size = vocals.stat().st_size
    if record.get("size_bytes") != actual_size:
        raise ListeningReviewError(
            f"Candidate vocals size mismatch for {vocals}: "
            f"{actual_size} != {record.get('size_bytes')}"
        )
    actual_hash = sha256_file(vocals)
    if record.get("sha256") != actual_hash:
        raise ListeningReviewError(
            f"Candidate vocals hash mismatch for {vocals}: {actual_hash} != {record.get('sha256')}"
        )
    return vocals, {
        "path": relative_path,
        "sha256": actual_hash,
        "size_bytes": actual_size,
    }


def render_clip(
    source: Path,
    destination: Path,
    *,
    start_sec: float,
    duration_sec: float,
) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-i",
        str(source),
        "-t",
        f"{duration_sec:.6f}",
        "-map",
        "0:a:0",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "flac",
        str(destination),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        raise ListeningReviewError(
            f"ffmpeg failed while rendering {destination}: {result.stderr.strip()}"
        )
    return command


def prepare_review(
    *,
    mix: Path,
    candidates: dict[str, Path],
    starts_sec: list[float],
    duration_sec: float,
    output_dir: Path,
) -> dict[str, Any]:
    validate_candidate_labels(list(candidates))
    if not mix.is_file():
        raise FileNotFoundError(f"Mix not found: {mix}")
    if len(candidates) < 2:
        raise ValueError("At least two separator candidates are required")
    if not starts_sec:
        raise ValueError("At least one listening-review start time is required")
    if duration_sec <= 0:
        raise ValueError("--duration must be positive")
    if output_dir.exists():
        raise ListeningReviewError(f"Refusing to reuse listening-review directory: {output_dir}")

    mix_sha256 = sha256_file(mix)
    resolved_candidates = {
        label: run_dir.expanduser().resolve() for label, run_dir in candidates.items()
    }
    if len(set(resolved_candidates.values())) != len(resolved_candidates):
        raise ListeningReviewError("Listening review requires distinct candidate run paths")
    candidate_records: dict[str, Any] = {}
    vocal_paths: dict[str, Path] = {}
    seen_run_ids: set[str] = set()
    for label, run_dir in sorted(resolved_candidates.items()):
        manifest = load_manifest(run_dir)
        run_id = manifest["run_id"]
        if run_id in seen_run_ids:
            raise ListeningReviewError("Listening review requires distinct candidate run_id values")
        seen_run_ids.add(run_id)

        inputs = manifest.get("inputs")
        if not isinstance(inputs, list) or len(inputs) != 1:
            raise ListeningReviewError(f"Candidate {run_id} must record exactly one mix input")
        input_record = inputs[0]
        if not isinstance(input_record, dict) or input_record.get("sha256") != mix_sha256:
            raise ListeningReviewError(
                f"Candidate {run_id} input SHA does not match the supplied mix"
            )

        vocals, vocals_record = verified_vocals(run_dir, manifest)
        manifest_path = run_dir / "run_manifest.json"
        vocal_paths[label] = vocals
        candidate_records[label] = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "preset": manifest["preset"],
            "model": manifest["model"],
            "model_bundle_sha256": manifest["model_provenance"]["bundle_sha256"],
            "input_mix_sha256": mix_sha256,
            "parent_manifest_path": str(manifest_path),
            "parent_manifest_sha256": sha256_file(manifest_path),
            "vocals": vocals_record,
            "vocals_sha256": vocals_record["sha256"],
        }

    output_dir.mkdir(parents=True)
    passages: list[dict[str, Any]] = []
    for index, start_sec in enumerate(starts_sec, start=1):
        if start_sec < 0:
            raise ValueError("Listening-review start times cannot be negative")
        passage_dir = output_dir / f"passage-{index:02d}-{start_sec:09.3f}s"
        passage_dir.mkdir()
        sources = {"mix": mix, **vocal_paths}
        outputs: dict[str, Any] = {}
        for label, source in sources.items():
            destination = passage_dir / f"{label}.flac"
            command = render_clip(
                source,
                destination,
                start_sec=start_sec,
                duration_sec=duration_sec,
            )
            outputs[label] = {
                "path": str(destination.relative_to(output_dir)),
                "sha256": sha256_file(destination),
                "size_bytes": destination.stat().st_size,
                "command": command,
            }
        passages.append(
            {
                "passage_id": f"passage-{index:02d}",
                "start_sec": start_sec,
                "end_sec": start_sec + duration_sec,
                "outputs": outputs,
                "review": {
                    "status": "awaiting_user",
                    "vocal_deletion": None,
                    "instrument_leakage": None,
                    "artifacts": None,
                    "preferred_candidate": None,
                    "notes": None,
                },
            }
        )

    result = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "awaiting_user",
        "mix": {
            "path": str(mix),
            "sha256": mix_sha256,
        },
        "candidates": candidate_records,
        "duration_sec": duration_sec,
        "passages": passages,
        "rubric": {
            "vocal_deletion": "Are audible lead-vocal syllables or note tails missing?",
            "instrument_leakage": "Are drums, bass, or accompaniment intrusive in vocals?",
            "artifacts": "Are there warbling, metallic, pumping, or transient artifacts?",
            "preferred_candidate": "Which vocal stem is more useful for transcription?",
        },
        "limitations": [
            "This manifest contains no listening result until a human reviewer fills it.",
            "Automated energy windows are only passage-selection aids.",
        ],
    }
    atomic_write_json(output_dir / "review_manifest.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render fixed original/vocal clips for a human separator review."
    )
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="LABEL=RUN_DIR",
        help="Candidate label and immutable separator run; repeat at least twice.",
    )
    parser.add_argument(
        "--start",
        action="append",
        type=float,
        default=[],
        help="Passage start in canonical-timeline seconds; repeat as needed.",
    )
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidates = dict(load_candidate(value) for value in args.candidate)
    if len(candidates) != len(args.candidate):
        raise ValueError("Duplicate listening-review candidate label")
    result = prepare_review(
        mix=args.mix.expanduser().resolve(),
        candidates=candidates,
        starts_sec=args.start,
        duration_sec=args.duration,
        output_dir=args.output_dir.expanduser().resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
