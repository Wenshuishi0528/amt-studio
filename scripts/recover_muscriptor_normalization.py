#!/usr/bin/env python3
"""Create an immutable MuScriptor run from already-completed native inference."""

from __future__ import annotations

# ruff: noqa: E402, I001
import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amt_core.utils import atomic_write_json, sha256_file
from workers.muscriptor.normalize import normalize_native_events
from workers.muscriptor.run_baseline import (
    artifact_records,
    git_state,
    load_json,
    source_records,
    utc_now,
    validate_run_id,
)


def _record_for(manifest: dict[str, Any], relative_path: str) -> dict[str, Any]:
    matches = [
        record
        for record in manifest.get("outputs", [])
        if isinstance(record, dict) and record.get("path") == relative_path
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Source manifest must contain exactly one {relative_path!r} output record"
        )
    return matches[0]


def _verify_record(run_dir: Path, manifest: dict[str, Any], relative_path: str) -> Path:
    record = _record_for(manifest, relative_path)
    path = run_dir / relative_path
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"Source artifact is missing or unsafe: {path}")
    if record.get("size_bytes") != path.stat().st_size:
        raise RuntimeError(f"Source artifact size does not match its manifest: {relative_path}")
    if record.get("sha256") != sha256_file(path):
        raise RuntimeError(f"Source artifact hash does not match its manifest: {relative_path}")
    return path


def _local_input(
    project_dir: Path,
    source: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = source.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise RuntimeError("Source manifest must contain exactly one input record")
    expected_hash = inputs[0].get("sha256")
    canonical = project_dir / "audio" / "canonical" / "mix.flac"
    if not canonical.is_file() or canonical.is_symlink():
        raise RuntimeError(f"Local canonical mix is missing or unsafe: {canonical}")
    actual_hash = sha256_file(canonical)
    lineage = source.get("input_lineage")
    if lineage is None:
        if expected_hash != actual_hash:
            raise RuntimeError(
                "Local canonical mix hash does not match source inference input: "
                f"{actual_hash} != {expected_hash}"
            )
        return (
            {"path": str(canonical), "sha256": actual_hash},
            {
                "kind": "direct_canonical_mix",
                "canonical_mix_path": str(canonical),
                "canonical_mix_sha256": actual_hash,
            },
        )
    if not isinstance(lineage, dict):
        raise RuntimeError("Source input_lineage must be an object")
    if lineage.get("canonical_mix_sha256") != actual_hash:
        raise RuntimeError(
            "Local canonical mix hash does not match source lineage: "
            f"{actual_hash} != {lineage.get('canonical_mix_sha256')}"
        )
    if lineage.get("kind") == "direct_canonical_mix":
        if expected_hash != actual_hash:
            raise RuntimeError(
                "Local canonical mix hash does not match source inference input"
            )
        return (
            {"path": str(canonical), "sha256": actual_hash},
            {
                **lineage,
                "canonical_mix_path": str(canonical),
                "canonical_mix_sha256": actual_hash,
            },
        )
    if lineage.get("kind") != "separator_stem":
        raise RuntimeError("Recovery supports only canonical mix or separator stem input")

    parent_run_id = validate_run_id(lineage.get("parent_separator_run_id"))
    relative_value = lineage.get("parent_output_path")
    if not isinstance(relative_value, str) or not relative_value:
        raise RuntimeError("Separator-stem lineage has no parent output path")
    relative = PurePosixPath(relative_value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or tuple(relative.parts[:2]) != ("raw", "stems")
    ):
        raise RuntimeError("Separator-stem parent output path is unsafe")
    parent_dir = project_dir / "runs" / parent_run_id
    parent_manifest_path = parent_dir / "run_manifest.json"
    if not parent_manifest_path.is_file() or parent_manifest_path.is_symlink():
        raise RuntimeError("Local parent separator manifest is missing or unsafe")
    if (
        sha256_file(parent_manifest_path)
        != lineage.get("parent_manifest_sha256")
    ):
        raise RuntimeError("Local parent separator manifest hash does not match lineage")
    parent_manifest = load_json(parent_manifest_path)
    if (
        parent_manifest.get("run_id") != parent_run_id
        or parent_manifest.get("worker") != "separator"
        or parent_manifest.get("status") != "succeeded"
    ):
        raise RuntimeError("Local parent run is not the recorded separator result")
    parent_outputs = [
        record
        for record in parent_manifest.get("outputs", [])
        if isinstance(record, dict) and record.get("path") == relative_value
    ]
    if len(parent_outputs) != 1:
        raise RuntimeError("Local parent separator output record is missing or duplicate")
    stem = parent_dir.joinpath(*relative.parts)
    if not stem.is_file() or stem.is_symlink():
        raise RuntimeError("Local separator stem is missing or unsafe")
    stem_hash = sha256_file(stem)
    if (
        expected_hash != stem_hash
        or lineage.get("parent_stem_sha256") != stem_hash
        or parent_outputs[0].get("sha256") != stem_hash
        or parent_outputs[0].get("size_bytes") != stem.stat().st_size
    ):
        raise RuntimeError("Local separator stem does not match source lineage")
    return (
        {"path": str(stem), "sha256": stem_hash},
        {
            **lineage,
            "canonical_mix_path": str(canonical),
            "parent_manifest_path": str(parent_manifest_path),
        },
    )


def recover(project_dir: Path, *, source_run_id: str, run_id: str) -> Path:
    source_run_id = validate_run_id(source_run_id)
    run_id = validate_run_id(run_id)
    project_dir = project_dir.expanduser().resolve()
    runs_dir = project_dir / "runs"
    source_dir = runs_dir / source_run_id
    source_manifest_path = source_dir / "run_manifest.json"
    if not source_manifest_path.is_file() or source_manifest_path.is_symlink():
        raise RuntimeError(f"Source run manifest is missing or unsafe: {source_manifest_path}")
    source = load_json(source_manifest_path)
    if source.get("run_id") != source_run_id or source.get("worker") != "muscriptor":
        raise RuntimeError("Source run identity does not match a MuScriptor run")
    if source.get("status") != "failed":
        raise RuntimeError("Normalization recovery requires a failed source run")
    error = source.get("error")
    if not isinstance(error, dict) or error.get("type") not in {
        "EventValidationError",
        "NativeEventError",
    }:
        raise RuntimeError("Source run did not fail during native-event normalization")
    timings = source.get("timings")
    if not isinstance(timings, dict):
        raise RuntimeError("Source run has no inference timing evidence")
    required_inference = ["jsonl"]
    decoding = source.get("decoding")
    if not isinstance(decoding, dict):
        raise RuntimeError("Source run has no decoding record")
    if not decoding.get("skip_midi"):
        required_inference.append("midi")
    for label in required_inference:
        timing = timings.get(label)
        if not isinstance(timing, dict) or timing.get("exit_code") != 0:
            raise RuntimeError(f"Source {label} inference did not complete successfully")

    native_events = _verify_record(source_dir, source, "raw/events.native.jsonl")
    native_midi = (
        _verify_record(source_dir, source, "raw/full.native.mid")
        if "midi" in required_inference
        else None
    )
    local_input, local_lineage = _local_input(project_dir, source)
    target_dir = runs_dir / run_id
    if target_dir.exists():
        raise RuntimeError(f"Refusing to reuse immutable run directory: {target_dir}")

    runs_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=runs_dir))
    started_at = utc_now()
    started = time.perf_counter()
    try:
        raw_dir = temporary_dir / "raw"
        normalized_dir = temporary_dir / "normalized"
        raw_dir.mkdir()
        normalized_dir.mkdir()
        copied_events = raw_dir / "events.native.jsonl"
        shutil.copy2(native_events, copied_events)
        if native_midi is not None:
            shutil.copy2(native_midi, raw_dir / "full.native.mid")

        model_provenance = source.get("model_provenance")
        if not isinstance(model_provenance, dict):
            raise RuntimeError("Source run has no model provenance")
        repository = model_provenance.get("repository")
        revision = model_provenance.get("revision")
        if not isinstance(repository, str) or not isinstance(revision, str):
            raise RuntimeError("Source model provenance lacks repository or revision")
        source_model = f"{repository}@{revision}"
        summary = normalize_native_events(
            copied_events,
            normalized_dir / "events.jsonl",
            normalized_dir / "summary.json",
            run_id=run_id,
            source_model=source_model,
            rejected_path=normalized_dir / "rejected_events.json",
        )
        if summary["rejected_events"]["count"] < 1:
            raise RuntimeError("Recovery found no quarantinable zero-duration native event")
        summary["rejected_events"]["path"] = "normalized/rejected_events.json"
        atomic_write_json(normalized_dir / "summary.json", summary)

        source_manifest_sha256 = sha256_file(source_manifest_path)
        request = {
            "schema_version": 1,
            "run_id": run_id,
            "project_id": project_dir.name,
            "worker": "muscriptor",
            "mode": "normalization_recovery",
            "source_run": {
                "run_id": source_run_id,
                "manifest_sha256": source_manifest_sha256,
            },
            "input": local_input,
            "input_lineage": local_lineage,
        }
        atomic_write_json(temporary_dir / "request.json", request)

        sources = source_records()
        sources.append(
            {
                "path": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
                "sha256": sha256_file(Path(__file__).resolve()),
            }
        )
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "project_id": project_dir.name,
            "worker": "muscriptor",
            "model": source.get("model"),
            "started_at": started_at,
            "ended_at": utc_now(),
            "status": "succeeded",
            "command": [sys.executable, *sys.argv],
            "inputs": [local_input],
            "input_lineage": request["input_lineage"],
            "outputs": [],
            "environment": source.get("environment"),
            "normalization_environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
            },
            "code": {
                **git_state(REPO_ROOT),
                "pins_sha256": sha256_file(REPO_ROOT / "workers" / "muscriptor" / "pins.json"),
                "source_files": sources,
            },
            "model_provenance": model_provenance,
            "decoding": decoding,
            "reproducibility": source.get("reproducibility"),
            "timings": {
                "source_inference": timings,
                "normalization_wall_time_sec": round(time.perf_counter() - started, 6),
            },
            "recovery": {
                "source_run_id": source_run_id,
                "source_manifest_sha256": source_manifest_sha256,
                "source_status": source.get("status"),
                "source_error": error,
                "inference_reused": True,
                "native_jsonl_sha256": sha256_file(copied_events),
                "native_midi_sha256": (
                    sha256_file(raw_dir / "full.native.mid")
                    if native_midi is not None
                    else None
                ),
                "normalization_policy": "quarantine_exact_zero_duration_only",
            },
            "metrics": {
                "descriptive_event_summary": summary,
                "accuracy_claimed": False,
            },
            "error": None,
        }
        manifest["outputs"] = artifact_records(temporary_dir)
        atomic_write_json(temporary_dir / "run_manifest.json", manifest)
        os.replace(temporary_dir, target_dir)
        return target_dir
    except Exception:
        shutil.rmtree(temporary_dir)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recover normalization into a new immutable run while preserving and "
            "hash-verifying a completed MuScriptor native inference."
        )
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = recover(
        args.project,
        source_run_id=args.source_run_id,
        run_id=args.run_id,
    )
    manifest = load_json(run_dir / "run_manifest.json")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
