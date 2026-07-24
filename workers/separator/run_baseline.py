from __future__ import annotations

import argparse
import hashlib
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

from amt_core.utils import atomic_write_json, sha256_file

try:
    from .metrics import AudioMetricError, analyze_stem_set
except ImportError:
    from metrics import AudioMetricError, analyze_stem_set


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
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"Unsupported JSON object in {path}")
    return value


def run_capture(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def write_text_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
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
import shutil
import subprocess
import onnxruntime as ort
import torch

def executable_probe(name):
    path = shutil.which(name)
    if path is None:
        return {"path": None, "version": None}
    result = subprocess.run(
        [path, "-version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    first_line = result.stdout.splitlines()[0] if result.stdout else None
    return {"path": path, "version": first_line, "exit_code": result.returncode}

cuda_available = bool(torch.cuda.is_available())
print(json.dumps({
    "python": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "audio_separator": importlib.metadata.version("audio-separator"),
    "numpy": importlib.metadata.version("numpy"),
    "numba": importlib.metadata.version("numba"),
    "onnxruntime": importlib.metadata.version("onnxruntime"),
    "onnxruntime_providers": ort.get_available_providers(),
    "ffmpeg": executable_probe("ffmpeg"),
    "ffprobe": executable_probe("ffprobe"),
    "torch": torch.__version__,
    "cuda_available": cuda_available,
    "cuda_version": torch.version.cuda,
    "cuda_device_count": torch.cuda.device_count(),
    "cuda_device_name": torch.cuda.get_device_name(0) if cuda_available else None,
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
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started_at = utc_now()
    start = time.perf_counter()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        result = subprocess.run(
            argv,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
        )
    return {
        "argv": argv,
        "started_at": started_at,
        "ended_at": utc_now(),
        "wall_time_sec": round(time.perf_counter() - start, 6),
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
        WORKER_DIR / "metrics.py",
        Path(__file__).resolve(),
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "16_separator_baseline.slurm",
    )
    records: list[dict[str, str]] = []
    for path in paths:
        try:
            display_path = str(path.relative_to(REPO_ROOT))
        except ValueError:
            display_path = str(path)
        records.append(
            {
                "path": display_path,
                "sha256": sha256_file(path),
            }
        )
    return records


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def model_bundle_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


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
        )
    }


def verify_model_files(
    model_dir: Path,
    expected_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not expected_files:
        raise RuntimeError(
            "Preset has no pinned expected_files; complete the model download/hash step first"
        )
    verified: list[dict[str, Any]] = []
    for record in expected_files:
        relative_path = Path(record["path"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Unsafe pinned model path: {relative_path}")
        path = model_dir / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Pinned separator model file not found: {path}")
        actual_hash = sha256_file(path)
        expected_hash = record.get("sha256")
        if not expected_hash:
            raise RuntimeError(
                f"Pinned separator model hash is missing for {relative_path}; "
                "run the setup/hash phase and update pins.json before inference"
            )
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Pinned separator model hash mismatch for {relative_path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        expected_size = record.get("size_bytes")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise RuntimeError(
                f"Pinned separator model size mismatch for {relative_path}: "
                f"expected {expected_size}, got {path.stat().st_size}"
            )
        verified.append(
            {
                "path": str(relative_path),
                "sha256": actual_hash,
                "size_bytes": path.stat().st_size,
                "source": record.get("source"),
            }
        )
    return verified


def build_separator_command(
    executable: Path,
    *,
    audio: Path,
    output_dir: Path,
    model_dir: Path,
    preset: dict[str, Any],
) -> list[str]:
    parameters = preset["parameters"]
    command = [
        str(executable),
        str(audio),
        "--model_filename",
        preset["model_filename"],
        "--model_file_dir",
        str(model_dir),
        "--output_dir",
        str(output_dir),
        "--output_format",
        "FLAC",
        "--normalization",
        str(parameters["normalization"]),
        "--amplification",
        str(parameters["amplification"]),
        "--sample_rate",
        str(parameters["sample_rate"]),
        "--use_soundfile",
        "--custom_output_names",
        json.dumps(preset["custom_output_names"], separators=(",", ":")),
    ]
    if parameters.get("autocast"):
        command.append("--use_autocast")
    if parameters.get("chunk_duration_sec") is not None:
        command.extend(
            ["--chunk_duration", str(parameters["chunk_duration_sec"])]
        )
    if preset["architecture"] == "MDXC":
        command.extend(
            [
                "--mdxc_overlap",
                str(parameters["mdxc_overlap"]),
                "--mdxc_batch_size",
                str(parameters["mdxc_batch_size"]),
            ]
        )
    if preset["architecture"] == "Demucs":
        command.extend(
            [
                "--demucs_shifts",
                str(parameters["demucs_shifts"]),
                "--demucs_overlap",
                str(parameters["demucs_overlap"]),
            ]
        )
    return command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one immutable audio-separator baseline and analyze its stems."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--audio",
        type=Path,
        help="Optional fixed excerpt; defaults to the project's canonical mix.",
    )
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id)
    project_dir = args.project.expanduser().resolve()
    worker_env = args.worker_env.expanduser().resolve()
    model_dir = args.model_dir.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve()
    pins = load_json(pins_path)
    if args.preset not in pins["presets"]:
        raise ValueError(f"Unknown separator preset: {args.preset}")
    preset = pins["presets"][args.preset]

    audio = (
        args.audio.expanduser().resolve()
        if args.audio is not None
        else project_dir / "audio" / "canonical" / "mix.flac"
    )
    worker_python = worker_env / "bin" / "python"
    separator = worker_env / "bin" / "audio-separator"
    run_dir = project_dir / "runs" / run_id
    if run_dir.exists():
        raise RuntimeError(f"Refusing to reuse immutable run directory: {run_dir}")
    if not audio.is_file():
        raise FileNotFoundError(f"Separator input audio not found: {audio}")
    if not worker_python.is_file() or not separator.is_file():
        raise FileNotFoundError(f"Separator worker environment is incomplete: {worker_env}")
    verified_model_files = verify_model_files(model_dir, preset["expected_files"])
    preset_sha256 = canonical_json_sha256(preset)
    model_bundle_hash = model_bundle_sha256(verified_model_files)

    raw_dir = run_dir / "raw"
    stems_dir = raw_dir / "stems"
    logs_dir = run_dir / "logs"
    metrics_dir = run_dir / "metrics"
    for path in (stems_dir, logs_dir, metrics_dir):
        path.mkdir(parents=True)

    command = build_separator_command(
        separator,
        audio=audio,
        output_dir=stems_dir,
        model_dir=model_dir,
        preset=preset,
    )
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "separator",
        "preset": args.preset,
        "preset_sha256": preset_sha256,
        "model_filename": preset["model_filename"],
        "input": {
            "path": str(audio),
            "sha256": sha256_file(audio),
        },
        "command": command,
        "configuration": preset["parameters"],
        "model_bundle_sha256": model_bundle_hash,
    }
    atomic_write_json(run_dir / "request.json", request)

    started_at = utc_now()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "separator",
        "model": preset["model_filename"],
        "preset": args.preset,
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "command": command,
        "inputs": [request["input"]],
        "outputs": [],
        "environment": None,
        "code": {
            **git_state(REPO_ROOT),
            "source_files": source_records(pins_path),
        },
        "model_provenance": {
            "package": pins["package"],
            "preset": args.preset,
            "preset_sha256": preset_sha256,
            "friendly_name": preset["friendly_name"],
            "architecture": preset["architecture"],
            "model_filename": preset["model_filename"],
            "files": verified_model_files,
            "bundle_sha256": model_bundle_hash,
            "license": preset["license"],
        },
        "configuration": preset["parameters"],
        "reproducibility": {
            "random_seed": None,
            "random_seed_reason": (
                "audio-separator 0.44.5 CLI exposes no seed option; Demucs "
                "random shifts are disabled and no sampling option is used."
            ),
            "demucs_random_shifts": preset["parameters"].get("demucs_shifts"),
            "autocast": preset["parameters"].get("autocast", False),
            "torch_deterministic_algorithms_requested": False,
            "repeatability_assessed_separately": True,
        },
        "scheduler": slurm_context(),
        "timings": {},
        "metrics": {},
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)

    try:
        command_environment = os.environ.copy()
        command_environment.pop("AUDIO_SEPARATOR_MODEL_DIR", None)
        command_environment.setdefault("PYTHONHASHSEED", "0")
        command_environment.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

        diagnostics = worker_diagnostics(worker_python)
        diagnostics["hostname"] = platform.node()
        diagnostics["os"] = platform.platform()
        manifest["environment"] = diagnostics
        atomic_write_json(logs_dir / "device.json", diagnostics)
        for executable_name in ("ffmpeg", "ffprobe"):
            executable = diagnostics.get(executable_name)
            if (
                not isinstance(executable, dict)
                or not executable.get("path")
                or executable.get("exit_code") != 0
            ):
                raise RuntimeError(
                    f"Separator inference requires a working {executable_name} executable"
                )
        ffmpeg_version = diagnostics["ffmpeg"].get("version") or ""
        if not ffmpeg_version.startswith(
            f"ffmpeg version {pins['runtime']['ffmpeg']}"
        ):
            raise RuntimeError(
                "FFmpeg version does not match pins.json: "
                f"{ffmpeg_version!r} != {pins['runtime']['ffmpeg']!r}"
            )
        if not diagnostics.get("cuda_available"):
            raise RuntimeError("Separator inference requires a CUDA Slurm allocation")
        if diagnostics["audio_separator"] != pins["package"]["version"]:
            raise RuntimeError(
                "audio-separator version does not match pins.json: "
                f"{diagnostics['audio_separator']} != {pins['package']['version']}"
            )
        for package_name in ("numpy", "numba", "onnxruntime"):
            if diagnostics[package_name] != pins["runtime"][package_name]:
                raise RuntimeError(
                    f"{package_name} version does not match pins.json: "
                    f"{diagnostics[package_name]} != "
                    f"{pins['runtime'][package_name]}"
                )
        if diagnostics["torch"].split("+", 1)[0] != pins["runtime"]["torch"]:
            raise RuntimeError(
                "torch version does not match pins.json: "
                f"{diagnostics['torch']} != {pins['runtime']['torch']}"
            )
        expected_ort_provider = pins["runtime"]["onnxruntime_provider"]
        if expected_ort_provider not in diagnostics["onnxruntime_providers"]:
            raise RuntimeError(
                "Pinned ONNX Runtime provider is unavailable: "
                f"{expected_ort_provider} not in "
                f"{diagnostics['onnxruntime_providers']}"
            )

        for label, diagnostic_command in (
            ("help", [str(separator), "--help"]),
            ("env-info", [str(separator), "--env_info"]),
            (
                "list-model",
                [
                    str(separator),
                    "--model_file_dir",
                    str(model_dir),
                    "--list_models",
                    "--list_filter",
                    preset["model_filename"],
                    "--list_limit",
                    "5",
                    "--list_format",
                    "json",
                ],
            ),
        ):
            write_text_log(
                logs_dir / f"{label}.txt",
                run_capture(diagnostic_command, env=command_environment),
            )

        result = run_logged(
            command,
            stdout_path=logs_dir / "separator.stdout",
            stderr_path=logs_dir / "separator.stderr",
            env=command_environment,
        )
        manifest["timings"]["separation"] = result
        if result["exit_code"] != 0:
            raise RuntimeError("audio-separator command failed")

        stems: dict[str, Path] = {
            name: stems_dir / f"{name}.flac"
            for name in preset["expected_stems"]
        }
        missing = [name for name, path in stems.items() if not path.is_file()]
        empty = [
            name
            for name, path in stems.items()
            if path.is_file() and path.stat().st_size == 0
        ]
        if missing or empty:
            raise RuntimeError(
                f"Separator outputs incomplete; missing={missing}, empty={empty}"
            )

        audio_metrics = analyze_stem_set(audio, stems)
        atomic_write_json(metrics_dir / "audio_metrics.json", audio_metrics)
        manifest["metrics"] = {
            "audio": audio_metrics,
            "accuracy_claimed": False,
            "subjective_listening_complete": False,
        }
        manifest["status"] = "succeeded"
    except (AudioMetricError, OSError, RuntimeError, ValueError) as exc:
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
