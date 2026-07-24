from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.contracts import RESULT_CONTRACT, ArtifactRecord, WorkerRequestV1
from amt_core.utils import atomic_write_json, sha256_file

try:
    from .normalize import NativeRhythmError, normalize_native_rhythm
except ImportError:
    from normalize import NativeRhythmError, normalize_native_rhythm

WORKER_DIR = Path(__file__).resolve().parent
REPO_ROOT = WORKER_DIR.parents[1]
DEFAULT_PINS = WORKER_DIR / "pins.json"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z", re.ASCII)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError("--run-id is missing or unsafe")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def run_capture(
    argv: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
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


def worker_diagnostics(worker_python: Path, checkpoint: Path) -> dict[str, Any]:
    source = """
import importlib.metadata
import json
import platform
import sys

import torch
import torchaudio
from beat_this.inference import load_checkpoint

checkpoint = load_checkpoint(sys.argv[1], "cpu")
print(json.dumps({
    "python": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "beat_this": importlib.metadata.version("beat-this"),
    "torch": torch.__version__,
    "torchaudio": torchaudio.__version__,
    "numpy": importlib.metadata.version("numpy"),
    "soundfile": importlib.metadata.version("soundfile"),
    "soxr": importlib.metadata.version("soxr"),
    "einops": importlib.metadata.version("einops"),
    "rotary_embedding_torch": importlib.metadata.version("rotary-embedding-torch"),
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_version": torch.version.cuda,
    "cuda_device_count": torch.cuda.device_count(),
    "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "checkpoint_keys": sorted(checkpoint),
}))
"""
    result = run_capture([str(worker_python), "-c", source, str(checkpoint)])
    if result.returncode != 0:
        raise RuntimeError(f"Beat This diagnostics failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Beat This diagnostics returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Beat This diagnostics did not return an object")
    return value


def probe_audio(ffprobe: Path, path: Path) -> dict[str, Any]:
    argv = [
        str(ffprobe),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = run_capture(argv)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
        stream = value["streams"][0]
        duration = float(value["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe returned malformed audio metadata") from exc
    if duration <= 0 or sample_rate <= 0 or channels <= 0:
        raise RuntimeError("ffprobe returned invalid audio metadata")
    return {
        "command": argv,
        "duration_sec": duration,
        "sample_rate": sample_rate,
        "channels": channels,
    }


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
    started = time.perf_counter()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        result = subprocess.run(
            argv,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    return {
        "argv": argv,
        "started_at": started_at,
        "ended_at": utc_now(),
        "wall_time_sec": round(time.perf_counter() - started, 6),
        "exit_code": result.returncode,
        "peak_child_rss_bytes": maximum_child_rss_bytes(),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def artifact_records(run_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(run_dir)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "run_manifest.json"
    ]


def source_records(pins_path: Path) -> list[dict[str, str]]:
    paths = (
        pins_path,
        WORKER_DIR / "pyproject.toml",
        WORKER_DIR / "uv.lock",
        WORKER_DIR / "normalize.py",
        Path(__file__).resolve(),
        REPO_ROOT / "src" / "amt_core" / "canonical.py",
        REPO_ROOT / "src" / "amt_core" / "contracts.py",
        REPO_ROOT / "src" / "amt_core" / "utils.py",
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "26_beat_this_baseline.slurm",
    )
    return [
        {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def slurm_context() -> dict[str, str | None]:
    return {
        name.lower(): os.environ.get(name)
        for name in (
            "SLURM_JOB_ID",
            "SLURM_JOB_NAME",
            "SLURM_JOB_PARTITION",
            "SLURM_JOB_ACCOUNT",
            "SLURM_JOB_QOS",
            "SLURMD_NODENAME",
            "SLURM_CPUS_PER_TASK",
        )
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one immutable Beat This baseline on the canonical mix."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--require-cuda", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id)
    project_dir = args.project.expanduser().resolve()
    worker_env = args.worker_env.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve()
    ffprobe = args.ffprobe.expanduser().resolve()
    worker_python = worker_env / "bin" / "python"
    worker_cli = worker_env / "bin" / "beat_this"
    expected_worker_root = WORKER_DIR.resolve()
    try:
        worker_env.relative_to(expected_worker_root)
    except ValueError as exc:
        raise ValueError("Beat This environment must be inside workers/beat_this") from exc
    if not worker_python.is_file() or not worker_cli.is_file():
        raise FileNotFoundError("Beat This worker environment is incomplete")
    if not checkpoint.is_file() or not pins_path.is_file() or not ffprobe.is_file():
        raise FileNotFoundError("Beat This checkpoint, pins, or ffprobe is unavailable")

    project_manifest_path = project_dir / "manifest.json"
    project = load_json(project_manifest_path)
    project_id = project.get("project_id")
    canonical = project.get("canonical_audio")
    if not isinstance(project_id, str) or project_id != project_dir.name:
        raise ValueError("project identity does not match its directory")
    if not isinstance(canonical, dict) or not isinstance(canonical.get("path"), str):
        raise ValueError("project canonical audio record is malformed")
    audio = (project_dir / canonical["path"]).resolve(strict=True)
    expected_audio = (project_dir / "audio" / "canonical" / "mix.flac").resolve()
    if audio != expected_audio or not audio.is_file():
        raise ValueError("Beat This input must be the project canonical mix")
    audio_sha256 = sha256_file(audio)
    if canonical.get("sha256") != audio_sha256:
        raise ValueError("canonical mix hash does not match the project manifest")

    pins = load_json(pins_path)
    if pins.get("schema_version") != 1:
        raise ValueError("unsupported Beat This pins")
    package_pin = pins.get("package")
    model_pin = pins.get("model")
    runtime_pin = pins.get("runtime")
    decoding_pin = pins.get("decoding")
    if not all(
        isinstance(value, dict) for value in (package_pin, model_pin, runtime_pin, decoding_pin)
    ):
        raise ValueError("Beat This pins are incomplete")
    checkpoint_sha256 = sha256_file(checkpoint)
    if (
        checkpoint.name != model_pin.get("filename")
        or checkpoint_sha256 != model_pin.get("sha256")
        or checkpoint.stat().st_size != model_pin.get("size_bytes")
    ):
        raise ValueError("Beat This checkpoint does not match pins")

    diagnostics = worker_diagnostics(worker_python, checkpoint)
    if diagnostics.get("beat_this") != package_pin.get("version"):
        raise RuntimeError("installed Beat This version does not match pins")
    if diagnostics.get("torch") != runtime_pin.get("torch_distribution"):
        raise RuntimeError("installed Torch distribution does not match pins")
    if diagnostics.get("torchaudio") != runtime_pin.get("torchaudio_distribution"):
        raise RuntimeError("installed Torchaudio distribution does not match pins")
    if diagnostics.get("numpy") != runtime_pin.get("numpy"):
        raise RuntimeError("installed NumPy version does not match pins")
    if diagnostics.get("soundfile") != runtime_pin.get("soundfile"):
        raise RuntimeError("installed SoundFile version does not match pins")
    if args.require_cuda and not diagnostics.get("cuda_available"):
        raise RuntimeError("CUDA is required but unavailable")
    if args.require_cuda and diagnostics.get("cuda_version") != runtime_pin.get("cuda_runtime"):
        raise RuntimeError("CUDA runtime does not match pins")

    run_dir = project_dir / "runs" / run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise FileExistsError(f"immutable run already exists: {run_dir}")
    raw_dir = run_dir / "raw" / "native"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    raw_dir.mkdir(parents=True)
    normalized_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    manifest_path = run_dir / "run_manifest.json"
    started_at = utc_now()
    command: list[str] = []
    timings: dict[str, Any] = {}
    status = "failed"
    error: dict[str, str] | None = None
    audio_metrics: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    request = WorkerRequestV1(
        request_id=run_id,
        run_id=run_id,
        project_id=project_id,
        worker="beat_this",
        created_at=started_at,
        input=ArtifactRecord(
            path=str(audio),
            sha256=audio_sha256,
            size_bytes=audio.stat().st_size,
        ),
        configuration={
            "checkpoint": model_pin.get("name"),
            "dbn": decoding_pin.get("dbn"),
            "float16": decoding_pin.get("float16"),
            "gpu_index": decoding_pin.get("gpu_index"),
            "activations": decoding_pin.get("activations"),
            "postprocessor": decoding_pin.get("postprocessor"),
            "frame_rate_hz": decoding_pin.get("frame_rate_hz"),
        },
        requested_outputs=(
            "raw/native/mix.beats",
            "raw/native/mix.npy",
            "normalized/rhythm.json",
            "normalized/summary.json",
        ),
    )
    request.write(run_dir / "request.json")
    try:
        audio_metrics = probe_audio(ffprobe, audio)
        device_index = decoding_pin.get("gpu_index")
        command = [
            str(worker_cli),
            str(audio),
            "--model",
            str(checkpoint),
            "--output",
            str(raw_dir / "mix.beats"),
            "--gpu",
            str(device_index),
            "--activations",
        ]
        if decoding_pin.get("dbn"):
            command.append("--dbn")
        else:
            command.append("--no-dbn")
        if decoding_pin.get("float16"):
            command.append("--float16")
        help_result = run_capture([str(worker_cli), "--help"])
        (logs_dir / "help.txt").write_text(
            f"exit_code={help_result.returncode}\n{help_result.stdout}\n{help_result.stderr}",
            encoding="utf-8",
        )
        atomic_write_json(logs_dir / "device.json", diagnostics)
        timings["inference"] = run_logged(
            command,
            stdout_path=logs_dir / "inference.stdout",
            stderr_path=logs_dir / "inference.stderr",
        )
        if timings["inference"]["exit_code"] != 0:
            raise RuntimeError("Beat This inference command failed")
        beats_path = raw_dir / "mix.beats"
        activations_path = raw_dir / "mix.npy"
        if (
            not beats_path.is_file()
            or beats_path.stat().st_size == 0
            or not activations_path.is_file()
            or activations_path.stat().st_size == 0
        ):
            raise RuntimeError("Beat This did not produce native beats and activations")
        rhythm, summary = normalize_native_rhythm(
            beats_path,
            activations_path,
            run_id=run_id,
            source_model=model_pin["name"],
            canonical_audio_sha256=audio_sha256,
            duration_sec=audio_metrics["duration_sec"],
            frame_rate_hz=decoding_pin["frame_rate_hz"],
        )
        atomic_write_json(normalized_dir / "rhythm.json", rhythm.to_dict())
        atomic_write_json(normalized_dir / "summary.json", summary)
        status = "succeeded"
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        manifest = {
            "schema_version": 1,
            "contract_version": RESULT_CONTRACT,
            "run_id": run_id,
            "project_id": project_id,
            "worker": "beat_this",
            "model": model_pin.get("name"),
            "started_at": started_at,
            "ended_at": utc_now(),
            "status": status,
            "command": command,
            "inputs": [
                {
                    "path": str(audio),
                    "sha256": audio_sha256,
                    "size_bytes": audio.stat().st_size,
                }
            ],
            "input_lineage": {
                "kind": "direct_canonical_mix",
                "timeline_basis": "original_canonical_mix_seconds",
                "canonical_mix_path": str(audio),
                "canonical_mix_sha256": audio_sha256,
            },
            "configuration": request.configuration,
            "environment": {
                **diagnostics,
                "hostname": platform.node(),
            },
            "scheduler": slurm_context(),
            "code": {
                **git_state(REPO_ROOT),
                "pins_sha256": sha256_file(pins_path),
                "source_files": source_records(pins_path),
                "upstream_commit": package_pin.get("upstream_git_commit"),
            },
            "model_provenance": {
                "package": package_pin,
                "checkpoint": {
                    **model_pin,
                    "path": str(checkpoint),
                },
            },
            "timings": timings,
            "metrics": {
                "accuracy_claimed": False,
                "audio": audio_metrics,
                "descriptive_rhythm_summary": summary,
            },
            "reproducibility": {
                "dbn": decoding_pin.get("dbn"),
                "float16": decoding_pin.get("float16"),
                "repeatability_assessed_separately": False,
            },
            "outputs": artifact_records(run_dir),
            "error": error,
        }
        atomic_write_json(manifest_path, manifest)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (NativeRhythmError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
