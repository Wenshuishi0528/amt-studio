from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file


class RepeatabilityError(RuntimeError):
    """Raised when two runs cannot be compared under the same protocol."""


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_manifest.json"
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("status") != "succeeded":
        raise RepeatabilityError(f"Run did not succeed: {path}")
    if manifest.get("worker") != "separator":
        raise RepeatabilityError(f"Not a separator run: {path}")
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise RepeatabilityError(f"Separator run has no run_id: {path}")
    return manifest


def verified_stem_path(
    run_dir: Path,
    manifest: dict[str, Any],
    stem_name: str,
) -> Path:
    relative_path = f"raw/stems/{stem_name}.flac"
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise RepeatabilityError("Separator manifest outputs must be a list")
    records = [
        record
        for record in outputs
        if isinstance(record, dict) and record.get("path") == relative_path
    ]
    if len(records) != 1:
        raise RepeatabilityError(
            f"Manifest must contain exactly one output record for {relative_path}"
        )

    path = run_dir / relative_path
    if not path.is_file():
        raise RepeatabilityError(f"Missing fixed-name stem for comparison: {stem_name}")
    record = records[0]
    actual_size = path.stat().st_size
    if record.get("size_bytes") != actual_size:
        raise RepeatabilityError(
            f"Manifest size mismatch for {path}: {actual_size} != {record.get('size_bytes')}"
        )
    actual_hash = sha256_file(path)
    if record.get("sha256") != actual_hash:
        raise RepeatabilityError(
            f"Manifest hash mismatch for {path}: {actual_hash} != {record.get('sha256')}"
        )
    return path


def decoded_pcm_record(path: Path) -> dict[str, Any]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-f",
        "f32le",
        "pipe:1",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RepeatabilityError("ffmpeg stdout pipe was not created")
    digest = hashlib.sha256()
    size_bytes = 0
    while chunk := process.stdout.read(1024 * 1024):
        digest.update(chunk)
        size_bytes += len(chunk)
    process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    if process.stderr is not None:
        process.stderr.close()
    return_code = process.wait()
    if return_code != 0:
        raise RepeatabilityError(f"ffmpeg failed while decoding {path}: {stderr.strip()}")
    if size_bytes == 0:
        raise RepeatabilityError(f"Decoded stem is empty: {path}")
    return {
        "file_sha256": sha256_file(path),
        "decoded_pcm_sha256": digest.hexdigest(),
        "decoded_pcm_size_bytes": size_bytes,
    }


def compare_runs(run_a: Path, run_b: Path) -> dict[str, Any]:
    run_a = run_a.expanduser().resolve()
    run_b = run_b.expanduser().resolve()
    if run_a == run_b:
        raise RepeatabilityError("Repeatability requires two distinct run paths")

    manifest_a = load_manifest(run_a)
    manifest_b = load_manifest(run_b)
    if manifest_a["run_id"] == manifest_b["run_id"]:
        raise RepeatabilityError("Repeatability requires two distinct run_id values")

    comparable_fields = {
        "preset": (manifest_a.get("preset"), manifest_b.get("preset")),
        "model": (manifest_a.get("model"), manifest_b.get("model")),
        "configuration": (
            manifest_a.get("configuration"),
            manifest_b.get("configuration"),
        ),
        "model_bundle_sha256": (
            manifest_a.get("model_provenance", {}).get("bundle_sha256"),
            manifest_b.get("model_provenance", {}).get("bundle_sha256"),
        ),
        "input_sha256": (
            manifest_a.get("inputs", [{}])[0].get("sha256"),
            manifest_b.get("inputs", [{}])[0].get("sha256"),
        ),
    }
    mismatched = [
        name for name, (value_a, value_b) in comparable_fields.items() if value_a != value_b
    ]
    if mismatched:
        raise RepeatabilityError(
            "Runs do not share the same repeatability protocol: " + ", ".join(mismatched)
        )

    stems_a = manifest_a["metrics"]["audio"]["stems"]
    stems_b = manifest_b["metrics"]["audio"]["stems"]
    if set(stems_a) != set(stems_b):
        raise RepeatabilityError("Runs contain different stem labels")

    stem_results: dict[str, Any] = {}
    for name in sorted(stems_a):
        path_a = verified_stem_path(run_a, manifest_a, name)
        path_b = verified_stem_path(run_b, manifest_b, name)
        record_a = decoded_pcm_record(path_a)
        record_b = decoded_pcm_record(path_b)
        metadata_fields = ("sample_rate_hz", "channels", "sample_frames")
        metadata_equal = all(
            stems_a[name].get(field) == stems_b[name].get(field) for field in metadata_fields
        )
        stem_results[name] = {
            "run_a": record_a,
            "run_b": record_b,
            "metadata_equal": metadata_equal,
            "decoded_pcm_equal": (record_a["decoded_pcm_sha256"] == record_b["decoded_pcm_sha256"]),
            "container_bytes_equal": (record_a["file_sha256"] == record_b["file_sha256"]),
        }

    exact = all(
        result["metadata_equal"] and result["decoded_pcm_equal"] for result in stem_results.values()
    )
    return {
        "schema_version": 1,
        "status": "exact" if exact else "different",
        "run_a": manifest_a["run_id"],
        "run_b": manifest_b["run_id"],
        "protocol": {name: values[0] for name, values in comparable_fields.items()},
        "stems": stem_results,
        "accuracy_claimed": False,
        "interpretation": (
            "Exact means decoded PCM and key audio metadata match for this "
            "input and configuration; it is not a separation-quality score."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare decoded PCM from two immutable separator runs."
    )
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_runs(
        args.run_a.expanduser().resolve(),
        args.run_b.expanduser().resolve(),
    )
    output = args.output.expanduser().resolve()
    atomic_write_json(output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "exact" else 1


if __name__ == "__main__":
    raise SystemExit(main())
