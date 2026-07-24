from __future__ import annotations

import argparse
import json
import platform
import re
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file

try:
    from .normalize import NativeEventError, normalize_native_events
except ImportError:
    from normalize import NativeEventError, normalize_native_events


WORKER_DIR = Path(__file__).resolve().parent
REPO_ROOT = WORKER_DIR.parents[1]
DEFAULT_PINS = WORKER_DIR / "pins.json"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", re.ASCII)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError(
            "--run-id must be 1-200 ASCII letters, digits, dots, underscores, "
            "or hyphens; it must start with a letter or digit and cannot contain '..'"
        )
    return value


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def normalize_instruments(value: str | None) -> list[str] | None:
    if value is None:
        return None
    raw_names = value.split(",")
    if not raw_names or any(not name.strip() for name in raw_names):
        raise ValueError("--instruments must be a comma-separated list of names")
    names = [name.strip().lower() for name in raw_names]
    if len(set(names)) != len(names):
        raise ValueError("--instruments contains duplicate names")
    return names


def run_capture(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def git_state(repo_root: Path) -> dict[str, Any]:
    commit = run_capture(["git", "rev-parse", "HEAD"], cwd=repo_root)
    status = run_capture(["git", "status", "--porcelain"], cwd=repo_root)
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def worker_diagnostics(worker_python: Path) -> dict[str, Any]:
    source = """
import importlib.metadata
import json
import platform
import torch

print(json.dumps({
    "python": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "muscriptor": importlib.metadata.version("muscriptor"),
    "torch": torch.__version__,
    "mps_built": bool(torch.backends.mps.is_built()),
    "mps_available": bool(torch.backends.mps.is_available()),
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_version": torch.version.cuda,
    "cuda_device_count": torch.cuda.device_count(),
}))
"""
    result = run_capture([str(worker_python), "-c", source])
    if result.returncode != 0:
        raise RuntimeError(f"Worker diagnostics failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def maximum_child_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def run_logged(
    argv: list[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    started_at = utc_now()
    start = time.perf_counter()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        result = subprocess.run(
            argv,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    ended_at = utc_now()
    return {
        "argv": argv,
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_time_sec": round(time.perf_counter() - start, 6),
        "exit_code": result.returncode,
        "peak_child_rss_bytes": maximum_child_rss_bytes(),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def artifact_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "run_manifest.json":
            continue
        records.append(
            {
                "path": str(path.relative_to(run_dir)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def source_records() -> list[dict[str, str]]:
    paths = (
        WORKER_DIR / "pins.json",
        WORKER_DIR / "pyproject.toml",
        WORKER_DIR / "uv.lock",
        WORKER_DIR / "normalize.py",
        Path(__file__).resolve(),
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "17_muscriptor_stem_compare.slurm",
    )
    return [
        {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def input_lineage(
    project_dir: Path,
    audio: Path,
    *,
    audio_sha256: str,
) -> dict[str, Any]:
    canonical_mix = (project_dir / "audio" / "canonical" / "mix.flac").resolve()
    if audio == canonical_mix:
        return {
            "kind": "direct_canonical_mix",
            "canonical_mix_path": str(canonical_mix),
            "canonical_mix_sha256": audio_sha256,
        }

    runs_dir = (project_dir / "runs").resolve()
    try:
        relative_to_runs = audio.relative_to(runs_dir)
    except ValueError:
        return {
            "kind": "unresolved_audio",
            "canonical_mix_path": None,
            "canonical_mix_sha256": None,
            "reason": "Input is neither the canonical mix nor a project separator stem.",
        }

    parts = relative_to_runs.parts
    if len(parts) < 4 or parts[1:3] != ("raw", "stems"):
        return {
            "kind": "unresolved_audio",
            "canonical_mix_path": None,
            "canonical_mix_sha256": None,
            "reason": "Project run input is not under raw/stems.",
        }

    parent_run_id = parts[0]
    parent_run_dir = runs_dir / parent_run_id
    parent_manifest_path = parent_run_dir / "run_manifest.json"
    if not parent_manifest_path.is_file():
        raise FileNotFoundError(
            f"Parent separator manifest not found for stem input: {parent_manifest_path}"
        )
    parent_manifest = load_json(parent_manifest_path)
    if parent_manifest.get("worker") != "separator" or parent_manifest.get("status") != "succeeded":
        raise RuntimeError(
            f"Parent stem run is not a succeeded separator run: {parent_manifest_path}"
        )

    relative_to_parent = str(audio.relative_to(parent_run_dir))
    output_records = [
        record
        for record in parent_manifest.get("outputs", [])
        if isinstance(record, dict) and record.get("path") == relative_to_parent
    ]
    if len(output_records) != 1:
        raise RuntimeError(
            "Parent separator manifest must contain exactly one matching stem output "
            f"record for {relative_to_parent}"
        )
    parent_output = output_records[0]
    if parent_output.get("sha256") != audio_sha256:
        raise RuntimeError(
            "Stem input hash does not match its parent separator manifest: "
            f"{audio_sha256} != {parent_output.get('sha256')}"
        )

    parent_inputs = parent_manifest.get("inputs")
    if not isinstance(parent_inputs, list) or len(parent_inputs) != 1:
        raise RuntimeError("Parent separator manifest must record exactly one mix input")
    parent_mix = parent_inputs[0]
    if not isinstance(parent_mix, dict) or not isinstance(parent_mix.get("sha256"), str):
        raise RuntimeError("Parent separator manifest has no valid canonical mix hash")

    stem_name = Path(parts[-1]).stem
    audio_metrics = parent_manifest.get("metrics", {}).get("audio", {})
    mix_metrics = audio_metrics.get("mix", {}) if isinstance(audio_metrics, dict) else {}
    stem_metrics = (
        audio_metrics.get("stems", {}).get(stem_name, {}) if isinstance(audio_metrics, dict) else {}
    )
    return {
        "kind": "separator_stem",
        "canonical_mix_path": parent_mix.get("path"),
        "canonical_mix_sha256": parent_mix["sha256"],
        "parent_separator_run_id": parent_manifest.get("run_id", parent_run_id),
        "parent_separator_preset": parent_manifest.get("preset"),
        "parent_manifest_path": str(parent_manifest_path),
        "parent_manifest_sha256": sha256_file(parent_manifest_path),
        "parent_output_path": relative_to_parent,
        "parent_stem_name": stem_name,
        "parent_stem_sha256": audio_sha256,
        "timeline": {
            "mix_duration_sec": mix_metrics.get("duration_sec"),
            "stem_duration_sec": stem_metrics.get("duration_sec"),
            "stem_duration_drift_sec": stem_metrics.get("duration_drift_sec"),
        },
    }


def write_text_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one immutable MuScriptor baseline and normalize its JSONL."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--audio",
        type=Path,
        help="Optional fixed excerpt; defaults to the project's canonical mix.",
    )
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--weight-provenance", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--dtype",
        choices=("float16", "float32", "bfloat16"),
        help="Optional explicit MuScriptor transformer dtype.",
    )
    parser.add_argument(
        "--instruments",
        help="Optional comma-separated MuScriptor instrument group allowlist.",
    )
    parser.add_argument(
        "--skip-midi",
        action="store_true",
        help="Run and preserve JSONL only; do not run the second MIDI decode.",
    )
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument(
        "--prelude-forcing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id)
    instruments = normalize_instruments(args.instruments)
    project_dir = args.project.expanduser().resolve()
    worker_env = args.worker_env.expanduser().resolve()
    provenance_path = args.weight_provenance.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve()
    pins = load_json(pins_path)
    provenance = load_json(provenance_path)
    if provenance.get("repository") != pins["model"]["repository"]:
        raise RuntimeError("Weight provenance repository does not match pins.json")
    if provenance.get("revision") != pins["model"]["revision"]:
        raise RuntimeError("Weight provenance revision does not match pins.json")

    worker_python = worker_env / "bin" / "python"
    muscriptor = worker_env / "bin" / "muscriptor"
    audio = (
        args.audio.expanduser().resolve()
        if args.audio is not None
        else project_dir / "audio" / "canonical" / "mix.flac"
    )
    run_dir = project_dir / "runs" / run_id
    if run_dir.exists():
        raise RuntimeError(f"Refusing to reuse immutable run directory: {run_dir}")
    if not audio.is_file():
        raise FileNotFoundError(f"Canonical audio not found: {audio}")
    if not worker_python.is_file() or not muscriptor.is_file():
        raise FileNotFoundError(f"MuScriptor worker environment is incomplete: {worker_env}")
    if args.beam_size < 1:
        raise ValueError("--beam-size must be at least 1")

    weight_path = Path(provenance["weight"]["path"]).expanduser().resolve()
    config_path = Path(provenance["config"]["path"]).expanduser().resolve()
    expected_weight_hash = provenance["weight"]["sha256"]
    if not weight_path.is_file():
        raise FileNotFoundError(f"Pinned model weight not found: {weight_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"Pinned model config not found: {config_path}")
    actual_weight_hash = sha256_file(weight_path)
    actual_config_hash = sha256_file(config_path)
    if actual_weight_hash != expected_weight_hash:
        raise RuntimeError(
            "Pinned model weight hash mismatch: "
            f"expected {expected_weight_hash}, got {actual_weight_hash}"
        )
    if actual_config_hash != provenance["config"]["sha256"]:
        raise RuntimeError(
            "Pinned model config hash mismatch: "
            f"expected {provenance['config']['sha256']}, got {actual_config_hash}"
        )

    audio_sha256 = sha256_file(audio)
    lineage = input_lineage(
        project_dir,
        audio,
        audio_sha256=audio_sha256,
    )
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for path in (raw_dir, normalized_dir, logs_dir):
        path.mkdir(parents=True)

    started_at = utc_now()
    source_model = f"{provenance['repository']}@{provenance['revision']}"
    prelude_arg = "--prelude-forcing" if args.prelude_forcing else "--no-prelude-forcing"
    common = [
        str(muscriptor),
        "transcribe",
        str(audio),
        "--model",
        str(weight_path),
        "--device",
        args.device,
        "--beam-size",
        str(args.beam_size),
        prelude_arg,
    ]
    if args.dtype is not None:
        common.extend(["--dtype", args.dtype])
    if instruments is not None:
        common.extend(["--instruments", ",".join(instruments)])
    native_events = raw_dir / "events.native.jsonl"
    native_midi = raw_dir / "full.native.mid"
    jsonl_command = [
        *common,
        "--format",
        "jsonl",
        "--output",
        str(native_events),
    ]
    midi_command = None
    if not args.skip_midi:
        midi_command = [
            *common,
            "--format",
            "midi",
            "--output",
            str(native_midi),
        ]
    commands = {"jsonl": jsonl_command}
    if midi_command is not None:
        commands["midi"] = midi_command
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "muscriptor",
        "model": pins["model"]["name"],
        "beam_size": args.beam_size,
        "prelude_forcing": args.prelude_forcing,
        "instruments": instruments,
        "skip_midi": args.skip_midi,
        "device": args.device,
        "dtype": args.dtype,
        "input": {
            "path": str(audio),
            "sha256": audio_sha256,
        },
        "input_lineage": lineage,
        "commands": commands,
    }
    atomic_write_json(run_dir / "request.json", request)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "muscriptor",
        "model": pins["model"]["name"],
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "command": jsonl_command,
        "commands": commands,
        "inputs": [request["input"]],
        "input_lineage": lineage,
        "outputs": [],
        "environment": None,
        "code": {
            **git_state(REPO_ROOT),
            "pins_sha256": sha256_file(pins_path),
            "source_files": source_records(),
        },
        "model_provenance": {
            "package": pins["package"],
            "repository": provenance["repository"],
            "revision": provenance["revision"],
            "license": provenance["license"],
            "weight_filename": provenance["weight"]["filename"],
            "weight_sha256": actual_weight_hash,
            "weight_size_bytes": provenance["weight"]["size_bytes"],
            "config_sha256": provenance["config"]["sha256"],
        },
        "decoding": {
            "beam_size": args.beam_size,
            "prelude_forcing": args.prelude_forcing,
            "sampling": False,
            "cfg_coef": 1.0,
            "dtype": args.dtype,
            "instruments": instruments,
            "device": args.device,
            "skip_midi": args.skip_midi,
        },
        "reproducibility": {
            "random_seed": None,
            "random_seed_reason": (
                "MuScriptor 0.2.2 CLI exposes no seed option; sampling is disabled."
            ),
            "torch_deterministic_algorithms_requested": False,
            "repeatability_assessed_separately": True,
        },
        "timings": {},
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)

    try:
        diagnostics = worker_diagnostics(worker_python)
        diagnostics["hostname"] = platform.node()
        diagnostics["os"] = platform.platform()
        manifest["environment"] = diagnostics
        atomic_write_json(logs_dir / "device.json", diagnostics)
        atomic_write_json(run_dir / "run_manifest.json", manifest)

        for label, command in (
            ("help", [str(muscriptor), "--help"]),
            ("transcribe-help", [str(muscriptor), "transcribe", "--help"]),
            ("list-instruments", [str(muscriptor), "list-instruments"]),
        ):
            write_text_log(logs_dir / f"{label}.txt", run_capture(command))

        jsonl_result = run_logged(
            jsonl_command,
            stdout_path=logs_dir / "transcribe-jsonl.stdout",
            stderr_path=logs_dir / "transcribe-jsonl.stderr",
        )
        manifest["timings"]["jsonl"] = jsonl_result
        if jsonl_result["exit_code"] != 0:
            raise RuntimeError("MuScriptor native JSONL command failed")
        if not native_events.is_file() or native_events.stat().st_size == 0:
            raise RuntimeError("MuScriptor reported success without native JSONL output")

        if midi_command is not None:
            midi_result = run_logged(
                midi_command,
                stdout_path=logs_dir / "transcribe-midi.stdout",
                stderr_path=logs_dir / "transcribe-midi.stderr",
            )
            manifest["timings"]["midi"] = midi_result
            if midi_result["exit_code"] != 0:
                raise RuntimeError("MuScriptor native MIDI command failed")
            if not native_midi.is_file() or native_midi.stat().st_size == 0:
                raise RuntimeError("MuScriptor reported success without native MIDI output")

        summary = normalize_native_events(
            native_events,
            normalized_dir / "events.jsonl",
            normalized_dir / "summary.json",
            run_id=run_id,
            source_model=source_model,
        )
        manifest["metrics"] = {
            "descriptive_event_summary": summary,
            "accuracy_claimed": False,
        }
        manifest["status"] = "succeeded"
    except (NativeEventError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        manifest["ended_at"] = utc_now()
        manifest["outputs"] = artifact_records(run_dir)
        atomic_write_json(run_dir / "run_manifest.json", manifest)

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
