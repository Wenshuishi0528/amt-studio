from __future__ import annotations

import argparse
import csv
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
    from .normalize import GameNativeError, normalize_native_csv
except ImportError:
    from normalize import GameNativeError, normalize_native_csv


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
        env=env,
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


def upstream_git_state(source_dir: Path) -> dict[str, Any]:
    commit = run_capture(["git", "rev-parse", "HEAD"], cwd=source_dir)
    status = run_capture(["git", "status", "--porcelain"], cwd=source_dir)
    if commit.returncode != 0 or status.returncode != 0:
        raise RuntimeError("Unable to inspect the pinned GAME source checkout")
    return {
        "commit": commit.stdout.strip(),
        "dirty": bool(status.stdout.strip()),
    }


def worker_diagnostics(worker_python: Path) -> dict[str, Any]:
    source = """
import importlib.metadata
import json
import platform
import torch

available = bool(torch.cuda.is_available())
print(json.dumps({
    "python": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "torch": torch.__version__,
    "lightning": importlib.metadata.version("lightning"),
    "librosa": importlib.metadata.version("librosa"),
    "numpy": importlib.metadata.version("numpy"),
    "colorednoise": importlib.metadata.version("colorednoise"),
    "h5py": importlib.metadata.version("h5py"),
    "matplotlib": importlib.metadata.version("matplotlib"),
    "mido": importlib.metadata.version("mido"),
    "cuda_available": available,
    "cuda_version": torch.version.cuda,
    "cuda_device_count": torch.cuda.device_count(),
    "cuda_device_name": torch.cuda.get_device_name(0) if available else None,
    "cuda_device_capability": list(torch.cuda.get_device_capability(0)) if available else None,
}))
"""
    result = run_capture([str(worker_python), "-c", source])
    if result.returncode != 0:
        raise RuntimeError(f"GAME worker diagnostics failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def verify_worker_environment(
    diagnostics: dict[str, Any],
    pins: dict[str, Any],
    *,
    require_cuda: bool,
) -> None:
    runtime = pins["runtime"]
    if diagnostics.get("python", "").split(".")[:2] != runtime["python"].split(".")[:2]:
        raise RuntimeError(f"GAME worker Python does not match pins: {diagnostics.get('python')!r}")
    expected_versions = {
        "torch": runtime["torch_distribution"],
        "lightning": runtime["lightning"],
        "numpy": runtime["numpy"],
        "librosa": runtime["librosa"],
        "colorednoise": runtime["colorednoise"],
        "h5py": runtime["h5py"],
        "matplotlib": runtime["matplotlib"],
        "mido": runtime["mido"],
    }
    for field, expected in expected_versions.items():
        if diagnostics.get(field) != expected:
            raise RuntimeError(
                f"GAME worker {field} does not match pins: "
                f"{diagnostics.get(field)!r} != {expected!r}"
            )
    if diagnostics.get("cuda_version") != runtime["cuda_runtime"]:
        raise RuntimeError(
            "GAME worker CUDA runtime does not match pins: "
            f"{diagnostics.get('cuda_version')!r} != {runtime['cuda_runtime']!r}"
        )
    if require_cuda and (
        diagnostics.get("cuda_available") is not True or diagnostics.get("cuda_device_count", 0) < 1
    ):
        raise RuntimeError("CUDA is required for the GAME Slurm baseline")


def maximum_child_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def run_logged(
    argv: list[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    started_at = utc_now()
    start = time.perf_counter()
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
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


def write_text_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.write_text(
        f"exit_code={result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )


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


def source_records(
    pins_path: Path,
    provenance_path: Path,
) -> list[dict[str, str]]:
    paths = (
        pins_path,
        provenance_path,
        WORKER_DIR / "pyproject.toml",
        WORKER_DIR / "uv.lock",
        WORKER_DIR / "normalize.py",
        WORKER_DIR / "prepare_assets.py",
        WORKER_DIR / "seeded_infer.py",
        Path(__file__).resolve(),
        REPO_ROOT / "src" / "amt_core" / "events.py",
        REPO_ROOT / "src" / "amt_core" / "utils.py",
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "24_game_baseline.slurm",
    )
    records: list[dict[str, str]] = []
    for path in paths:
        try:
            display_path = str(path.relative_to(REPO_ROOT))
        except ValueError:
            display_path = str(path)
        records.append({"path": display_path, "sha256": sha256_file(path)})
    return records


def input_lineage(
    project_dir: Path,
    audio: Path,
    *,
    audio_sha256: str,
) -> dict[str, Any]:
    runs_dir = (project_dir / "runs").resolve()
    try:
        relative_to_runs = audio.relative_to(runs_dir)
    except ValueError as exc:
        raise ValueError(
            "GAME Task004 input must be the selected separator vocal stem "
            "under runs/<run-id>/raw/stems/vocals.*"
        ) from exc

    parts = relative_to_runs.parts
    if len(parts) != 4 or parts[1:3] != ("raw", "stems") or Path(parts[3]).stem != "vocals":
        raise ValueError(
            "GAME Task004 input must be the selected separator vocal stem "
            "under runs/<run-id>/raw/stems/vocals.*"
        )

    parent_run_id = parts[0]
    parent_run_dir = runs_dir / parent_run_id
    parent_manifest_path = parent_run_dir / "run_manifest.json"
    parent_manifest = load_json(parent_manifest_path)
    if parent_manifest.get("worker") != "separator" or parent_manifest.get("status") != "succeeded":
        raise RuntimeError(
            f"Parent stem run is not a succeeded separator run: {parent_manifest_path}"
        )
    relative_to_parent = str(audio.relative_to(parent_run_dir))
    matching_outputs = [
        record
        for record in parent_manifest.get("outputs", [])
        if isinstance(record, dict) and record.get("path") == relative_to_parent
    ]
    if len(matching_outputs) != 1:
        raise RuntimeError(
            "Parent separator manifest must contain exactly one matching vocal-stem output"
        )
    if matching_outputs[0].get("sha256") != audio_sha256:
        raise RuntimeError("Vocal stem input does not match its parent separator output record")

    canonical_mix = (project_dir / "audio" / "canonical" / "mix.flac").resolve()
    if not canonical_mix.is_file():
        raise FileNotFoundError(f"Canonical mix not found: {canonical_mix}")
    canonical_mix_sha256 = sha256_file(canonical_mix)
    parent_inputs = parent_manifest.get("inputs")
    if not isinstance(parent_inputs, list) or len(parent_inputs) != 1:
        raise RuntimeError("Parent separator manifest must record exactly one mix input")
    parent_mix = parent_inputs[0]
    if (
        not isinstance(parent_mix, dict)
        or parent_mix.get("path") != str(canonical_mix)
        or parent_mix.get("sha256") != canonical_mix_sha256
    ):
        raise RuntimeError("Parent separator manifest is not bound to the current canonical mix")
    audio_metrics = parent_manifest.get("metrics", {}).get("audio", {})
    mix_metrics = audio_metrics.get("mix", {}) if isinstance(audio_metrics, dict) else {}
    stem_metrics = (
        audio_metrics.get("stems", {}).get("vocals", {}) if isinstance(audio_metrics, dict) else {}
    )
    return {
        "kind": "separator_vocal_stem",
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_mix_path": str(canonical_mix),
        "canonical_mix_sha256": canonical_mix_sha256,
        "parent_separator_run_id": parent_manifest.get("run_id", parent_run_id),
        "parent_separator_preset": parent_manifest.get("preset"),
        "parent_manifest_path": str(parent_manifest_path),
        "parent_manifest_sha256": sha256_file(parent_manifest_path),
        "parent_output_path": relative_to_parent,
        "parent_stem_name": "vocals",
        "parent_stem_sha256": audio_sha256,
        "timeline": {
            "mix_duration_sec": mix_metrics.get("duration_sec"),
            "stem_duration_sec": stem_metrics.get("duration_sec"),
            "stem_duration_drift_sec": stem_metrics.get("duration_drift_sec"),
        },
    }


def verify_model_assets(
    pins: dict[str, Any],
    provenance: dict[str, Any],
    *,
    pins_path: Path,
    provenance_path: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    package = pins["package"]
    model_pin = pins["model"]
    source = provenance.get("source")
    model = provenance.get("model")
    archive = provenance.get("archive")
    provenance_pins = provenance.get("pins")
    if not all(isinstance(value, dict) for value in (source, model, archive, provenance_pins)):
        raise RuntimeError("GAME model provenance is incomplete")
    if provenance_pins.get("sha256") != sha256_file(pins_path):
        raise RuntimeError("GAME model provenance was not generated from the current pins")
    if source.get("commit") != package["upstream_git_commit"]:
        raise RuntimeError("GAME source commit does not match pins")
    if archive.get("sha256") != model_pin["archive_sha256"]:
        raise RuntimeError("GAME model archive hash does not match pins")
    if archive.get("size_bytes") != model_pin["archive_size_bytes"]:
        raise RuntimeError("GAME model archive size does not match pins")
    expected_files = model_pin.get("expected_files")
    if not isinstance(expected_files, list) or not expected_files:
        raise RuntimeError(
            "GAME model expected_files are not pinned; run setup, record hashes, and rerun setup"
        )
    if model.get("files") != expected_files:
        raise RuntimeError("GAME extracted model provenance does not match pinned files")

    raw_model_dir = Path(model["directory"]).expanduser()
    if raw_model_dir.is_symlink() or not raw_model_dir.is_dir():
        raise RuntimeError("Pinned GAME model directory is missing or uses a symbolic link")
    model_dir = raw_model_dir.resolve(strict=True)
    records_by_path: dict[str, dict[str, Any]] = {}
    for record in expected_files:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or not record["path"]
            or record["path"] in records_by_path
        ):
            raise RuntimeError("Pinned GAME expected_files contain an invalid path record")
        relative_path = Path(record["path"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"Unsafe pinned GAME model file path: {record['path']!r}")
        cursor = model_dir
        for part in relative_path.parts:
            cursor /= part
            if cursor.is_symlink():
                raise RuntimeError(f"Pinned GAME model file path uses a symbolic link: {cursor}")
        path = (model_dir / relative_path).resolve(strict=True)
        try:
            path.relative_to(model_dir)
        except ValueError as exc:
            raise RuntimeError(f"Pinned GAME model file escapes model directory: {path}") from exc
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Pinned GAME model file is missing or unsafe: {path}")
        if path.stat().st_size != record["size_bytes"] or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Pinned GAME model file hash/size mismatch: {path}")
        records_by_path[record["path"]] = record

    source_dir = Path(source["path"]).expanduser().resolve(strict=True)
    state = upstream_git_state(source_dir)
    if state["commit"] != package["upstream_git_commit"] or state["dirty"]:
        raise RuntimeError("Pinned GAME source checkout has changed")
    infer_script = Path(source["infer_script"]).expanduser().resolve(strict=True)
    if (
        infer_script.parent != source_dir
        or sha256_file(infer_script) != source["infer_script_sha256"]
    ):
        raise RuntimeError("Pinned GAME infer.py does not match provenance")
    resolved_assets: dict[str, Path] = {}
    for label, relative_field, absolute_field in (
        ("model", "model_relative_path", "model_path"),
        ("config", "config_relative_path", "config_path"),
        ("language map", "lang_map_relative_path", "lang_map_path"),
    ):
        relative_value = model.get(relative_field)
        absolute_value = model.get(absolute_field)
        if (
            not isinstance(relative_value, str)
            or not relative_value
            or relative_value not in records_by_path
            or not isinstance(absolute_value, str)
        ):
            raise RuntimeError(f"GAME {label} path is absent from pinned model files")
        relative_path = Path(relative_value)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"Unsafe GAME {label} relative path: {relative_value!r}")
        pinned_path = (model_dir / relative_path).resolve(strict=True)
        recorded_path = Path(absolute_value).expanduser().resolve(strict=True)
        if recorded_path != pinned_path:
            raise RuntimeError(
                f"GAME {label} absolute path does not match its pinned relative path"
            )
        resolved_assets[label] = pinned_path
    model_path = resolved_assets["model"]
    config_path = resolved_assets["config"]
    lang_map_path = resolved_assets["language map"]
    if (
        model_path.suffix != ".pt"
        or config_path.name != "config.yaml"
        or lang_map_path.name != "lang_map.json"
        or not (model_path.parent == config_path.parent == lang_map_path.parent)
    ):
        raise RuntimeError("GAME model, config.yaml, and lang_map.json are no longer siblings")
    return (
        infer_script,
        model_path,
        {
            "provenance_path": str(provenance_path),
            "provenance_sha256": sha256_file(provenance_path),
            "source": source,
            "archive": archive,
            "model": model,
            "code_license": package["license"],
            "model_license": model_pin["license"],
            "commercial_use": False,
        },
    )


def probe_audio(ffprobe: str, audio: Path) -> dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels:format=duration",
        "-of",
        "json",
        str(audio),
    ]
    result = run_capture(command)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    value = json.loads(result.stdout)
    streams = value.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise RuntimeError("Expected exactly one audio stream")
    duration = float(value["format"]["duration"])
    return {
        "command": command,
        "duration_sec": duration,
        "sample_rate": int(streams[0]["sample_rate"]),
        "channels": int(streams[0]["channels"]),
    }


def verify_native_text(csv_path: Path, text_path: Path) -> dict[str, Any]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = [(row["onset"], row["offset"], row["pitch"]) for row in csv.DictReader(handle)]
    text_rows: list[tuple[str, str, str]] = []
    with text_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            fields = tuple(line.rstrip("\n").split("\t"))
            if len(fields) != 3:
                raise GameNativeError(
                    f"{text_path}:{line_number}: expected three tab-separated fields"
                )
            text_rows.append(fields)
    if csv_rows != text_rows:
        raise GameNativeError("GAME native TXT rows do not match native CSV rows")
    return {"row_count": len(csv_rows), "matches_csv_exactly": True}


def probe_midi(worker_python: Path, midi_path: Path) -> dict[str, Any]:
    source = """
import json
import mido
import sys

midi = mido.MidiFile(sys.argv[1])
note_on = sum(
    1
    for track in midi.tracks
    for message in track
    if message.type == "note_on" and message.velocity > 0
)
print(json.dumps({
    "type": midi.type,
    "ticks_per_beat": midi.ticks_per_beat,
    "track_count": len(midi.tracks),
    "note_on_count": note_on,
    "length_sec": midi.length,
}))
"""
    result = run_capture([str(worker_python), "-c", source, str(midi_path)])
    if result.returncode != 0:
        raise RuntimeError(f"Unable to parse GAME native MIDI: {result.stderr.strip()}")
    return json.loads(result.stdout)


def verify_native_event_count(midi_probe: dict[str, Any], decoded_event_count: int) -> None:
    midi_note_count = midi_probe.get("note_on_count")
    if (
        isinstance(midi_note_count, bool)
        or not isinstance(midi_note_count, int)
        or midi_note_count < 0
    ):
        raise RuntimeError("GAME MIDI probe returned an invalid note-on count")
    if midi_note_count != decoded_event_count:
        raise RuntimeError(
            "GAME native MIDI note count does not match decoded CSV events: "
            f"{midi_note_count} != {decoded_event_count}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one immutable GAME vocal-melody baseline.")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--model-provenance", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id)
    if args.seed < 0:
        raise ValueError("--seed must be non-negative")
    project_dir = args.project.expanduser().resolve()
    audio = args.audio.expanduser().resolve()
    worker_env = args.worker_env.expanduser().resolve()
    provenance_path = args.model_provenance.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve()
    pins = load_json(pins_path)
    provenance = load_json(provenance_path)
    worker_python = worker_env / "bin" / "python"
    seeded_infer = WORKER_DIR / "seeded_infer.py"
    if not audio.is_file():
        raise FileNotFoundError(f"GAME input audio not found: {audio}")
    if not worker_python.is_file():
        raise FileNotFoundError(f"GAME worker environment is incomplete: {worker_env}")
    infer_script, model_path, model_provenance = verify_model_assets(
        pins,
        provenance,
        pins_path=pins_path,
        provenance_path=provenance_path,
    )

    run_dir = project_dir / "runs" / run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise RuntimeError(f"Refusing to reuse immutable run directory: {run_dir}")
    raw_dir = run_dir / "raw" / "native"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for path in (raw_dir, normalized_dir, logs_dir):
        path.mkdir(parents=True)

    audio_sha256 = sha256_file(audio)
    lineage = input_lineage(project_dir, audio, audio_sha256=audio_sha256)
    audio_probe = probe_audio(args.ffprobe, audio)
    decoding = pins["decoding"]
    output_stem = audio.stem
    native_csv = raw_dir / f"{output_stem}.csv"
    native_txt = raw_dir / f"{output_stem}.txt"
    native_midi = raw_dir / f"{output_stem}.mid"
    source_model = (
        f"{pins['package']['name']}@{pins['package']['upstream_git_commit']}:"
        f"{pins['model']['name']}@{pins['model']['release']}"
    )
    command = [
        str(worker_python),
        str(seeded_infer),
        "--seed",
        str(args.seed),
        "--infer-script",
        str(infer_script),
        "--",
        "extract",
        str(audio),
        "--model",
        str(model_path),
        "--language",
        decoding["language"],
        "--batch-size",
        str(decoding["batch_size"]),
        "--num-workers",
        str(decoding["num_workers"]),
        "--seg-threshold",
        str(decoding["seg_threshold"]),
        "--seg-radius",
        str(decoding["seg_radius"]),
        "--t0",
        str(decoding["t0"]),
        "--nsteps",
        str(decoding["nsteps"]),
        "--est-threshold",
        str(decoding["est_threshold"]),
        "--output-formats",
        ",".join(decoding["output_formats"]),
        "--tempo",
        str(decoding["tempo_bpm"]),
        "--pitch-format",
        decoding["pitch_format"],
        "--output-dir",
        str(raw_dir),
    ]
    run_env = os.environ.copy()
    run_env["PYTHONHASHSEED"] = str(args.seed)
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "game",
        "input": {"path": str(audio), "sha256": audio_sha256},
        "input_lineage": lineage,
        "model": pins["model"]["name"],
        "seed": args.seed,
        "require_cuda": args.require_cuda,
        "decoding": decoding,
        "command": command,
    }
    atomic_write_json(run_dir / "request.json", request)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "game",
        "model": pins["model"]["name"],
        "started_at": utc_now(),
        "ended_at": None,
        "status": "running",
        "command": command,
        "inputs": [request["input"]],
        "input_lineage": lineage,
        "outputs": [],
        "environment": None,
        "code": {
            **git_state(REPO_ROOT),
            "pins_sha256": sha256_file(pins_path),
            "upstream_commit": pins["package"]["upstream_git_commit"],
            "source_files": source_records(pins_path, provenance_path),
        },
        "model_provenance": model_provenance,
        "decoding": {
            **decoding,
            "seed": args.seed,
            "device_selection": "lightning_auto_with_slurm_cuda_visibility",
        },
        "reproducibility": {
            "random_seed": args.seed,
            "pythonhashseed": str(args.seed),
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "torch_deterministic_algorithms_requested": False,
            "repeatability_assessed_separately": False,
        },
        "timings": {},
        "metrics": {"audio": audio_probe},
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)

    try:
        diagnostics = worker_diagnostics(worker_python)
        diagnostics["hostname"] = platform.node()
        diagnostics["os"] = platform.platform()
        verify_worker_environment(
            diagnostics,
            pins,
            require_cuda=args.require_cuda,
        )
        manifest["environment"] = diagnostics
        atomic_write_json(logs_dir / "device.json", diagnostics)
        write_text_log(
            logs_dir / "extract-help.txt",
            run_capture(
                [str(worker_python), str(infer_script), "extract", "--help"],
                cwd=infer_script.parent,
            ),
        )
        atomic_write_json(run_dir / "run_manifest.json", manifest)

        inference = run_logged(
            command,
            stdout_path=logs_dir / "infer.stdout",
            stderr_path=logs_dir / "infer.stderr",
            cwd=infer_script.parent,
            env=run_env,
        )
        manifest["timings"]["inference"] = inference
        if inference["exit_code"] != 0:
            raise RuntimeError("GAME upstream inference command failed")
        for path in (native_csv, native_txt, native_midi):
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"GAME reported success without native output: {path}")

        summary = normalize_native_csv(
            native_csv,
            normalized_dir / "events.jsonl",
            normalized_dir / "summary.json",
            run_id=run_id,
            source_model=source_model,
        )
        text_probe = verify_native_text(native_csv, native_txt)
        midi_probe = probe_midi(worker_python, native_midi)
        verify_native_event_count(midi_probe, summary["event_count"])
        last_offset = summary["timeline_sec"]["last_offset"]
        if last_offset is not None and last_offset > audio_probe["duration_sec"] + 0.05:
            raise RuntimeError(
                "GAME native event timeline exceeds input duration by more than 50 ms"
            )
        manifest["metrics"].update(
            {
                "descriptive_event_summary": summary,
                "native_txt": text_probe,
                "native_midi": midi_probe,
                "accuracy_claimed": False,
            }
        )
        manifest["status"] = "succeeded"
    except (GameNativeError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        manifest["ended_at"] = utc_now()
        manifest["outputs"] = artifact_records(run_dir)
        atomic_write_json(run_dir / "run_manifest.json", manifest)

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
