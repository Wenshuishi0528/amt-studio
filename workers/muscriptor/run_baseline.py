from __future__ import annotations

import argparse
import json
import platform
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


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


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
    )
    return [
        {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def write_text_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one immutable MuScriptor JSONL+MIDI baseline and normalize it."
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
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument(
        "--prelude-forcing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    run_dir = project_dir / "runs" / args.run_id
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
    native_events = raw_dir / "events.native.jsonl"
    native_midi = raw_dir / "full.native.mid"
    jsonl_command = [
        *common,
        "--format",
        "jsonl",
        "--output",
        str(native_events),
    ]
    midi_command = [
        *common,
        "--format",
        "midi",
        "--output",
        str(native_midi),
    ]
    request = {
        "schema_version": 1,
        "run_id": args.run_id,
        "project_id": project_dir.name,
        "worker": "muscriptor",
        "model": pins["model"]["name"],
        "beam_size": args.beam_size,
        "prelude_forcing": args.prelude_forcing,
        "device": args.device,
        "dtype": args.dtype,
        "input": {
            "path": str(audio),
            "sha256": sha256_file(audio),
        },
        "commands": {
            "jsonl": jsonl_command,
            "midi": midi_command,
        },
    }
    atomic_write_json(run_dir / "request.json", request)

    diagnostics = worker_diagnostics(worker_python)
    diagnostics["hostname"] = platform.node()
    diagnostics["os"] = platform.platform()
    atomic_write_json(logs_dir / "device.json", diagnostics)

    for label, command in (
        ("help", [str(muscriptor), "--help"]),
        ("transcribe-help", [str(muscriptor), "transcribe", "--help"]),
        ("list-instruments", [str(muscriptor), "list-instruments"]),
    ):
        write_text_log(logs_dir / f"{label}.txt", run_capture(command))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": args.run_id,
        "project_id": project_dir.name,
        "worker": "muscriptor",
        "model": pins["model"]["name"],
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "command": jsonl_command,
        "commands": {
            "jsonl": jsonl_command,
            "midi": midi_command,
        },
        "inputs": [request["input"]],
        "outputs": [],
        "environment": diagnostics,
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
            run_id=args.run_id,
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
