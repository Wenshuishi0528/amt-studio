from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
import resource
import struct
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file

try:
    from .normalize import NativeEventError, normalize_note_events
except ImportError:
    from normalize import NativeEventError, normalize_note_events


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

import onnxruntime as ort
from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
from basic_pitch.inference import Model

model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
model = Model(model_path)
print(json.dumps({
    "python": platform.python_version(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "basic_pitch": importlib.metadata.version("basic-pitch"),
    "numpy": importlib.metadata.version("numpy"),
    "onnxruntime": importlib.metadata.version("onnxruntime"),
    "setuptools": importlib.metadata.version("setuptools"),
    "onnxruntime_available_providers": ort.get_available_providers(),
    "model_type": model.model_type.name,
    "model_path": str(model_path),
    "model_session_providers": model.model.get_providers(),
}))
"""
    result = run_capture([str(worker_python), "-c", source])
    if result.returncode != 0:
        raise RuntimeError(f"Worker diagnostics failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Worker diagnostics returned invalid JSON: {result.stdout!r}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Worker diagnostics did not return a JSON object")
    return value


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
        WORKER_DIR / "normalize.py",
        Path(__file__).resolve(),
        REPO_ROOT / "src" / "amt_core" / "events.py",
        REPO_ROOT / "src" / "amt_core" / "utils.py",
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "22_basic_pitch_baseline.slurm",
    )
    records: list[dict[str, str]] = []
    for path in paths:
        try:
            display_path = str(path.relative_to(REPO_ROOT))
        except ValueError:
            display_path = str(path)
        records.append({"path": display_path, "sha256": sha256_file(path)})
    return records


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


def input_lineage(
    project_dir: Path,
    audio: Path,
    *,
    audio_sha256: str,
) -> dict[str, Any]:
    canonical_mix = (project_dir / "audio" / "canonical" / "mix.flac").resolve()
    if audio == canonical_mix:
        if not canonical_mix.is_file():
            raise FileNotFoundError(f"Canonical mix not found: {canonical_mix}")
        canonical_mix_sha256 = sha256_file(canonical_mix)
        if canonical_mix_sha256 != audio_sha256:
            raise RuntimeError("Canonical mix input hash changed during lineage validation")
        return {
            "kind": "direct_canonical_mix",
            "timeline_basis": "canonical_mix_seconds",
            "canonical_mix_path": str(canonical_mix),
            "canonical_mix_sha256": canonical_mix_sha256,
            "instrument_assignment": "unknown_other",
        }

    runs_dir = (project_dir / "runs").resolve()
    try:
        relative_to_runs = audio.relative_to(runs_dir)
    except ValueError as exc:
        raise ValueError(
            "Basic Pitch Task004 input must be a project separator vocal stem "
            "under runs/<run-id>/raw/stems/vocals.*"
        ) from exc

    parts = relative_to_runs.parts
    if len(parts) != 4 or parts[1:3] != ("raw", "stems") or Path(parts[3]).stem != "vocals":
        raise ValueError(
            "Basic Pitch Task004 input must be a project separator vocal stem "
            "under runs/<run-id>/raw/stems/vocals.*"
        )

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


def verify_midi(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size < 14:
        raise RuntimeError(f"Basic Pitch MIDI output is missing or too short: {path}")
    payload = path.read_bytes()
    if payload[:4] != b"MThd":
        raise RuntimeError(f"Basic Pitch MIDI output has no MThd header: {path}")
    header_size, midi_format, track_count, division = struct.unpack(">IHHH", payload[4:14])
    if header_size != 6 or midi_format not in (0, 1, 2) or track_count < 1 or division == 0:
        raise RuntimeError(f"Basic Pitch MIDI output has an invalid header: {path}")
    cursor = 8 + header_size
    track_sizes: list[int] = []
    for track_index in range(track_count):
        if payload[cursor : cursor + 4] != b"MTrk" or cursor + 8 > len(payload):
            raise RuntimeError(f"Basic Pitch MIDI output has no valid track {track_index}: {path}")
        track_size = struct.unpack(">I", payload[cursor + 4 : cursor + 8])[0]
        cursor += 8
        if cursor + track_size > len(payload):
            raise RuntimeError(f"Basic Pitch MIDI track {track_index} is truncated: {path}")
        track_sizes.append(track_size)
        cursor += track_size
    if cursor != len(payload):
        raise RuntimeError(f"Basic Pitch MIDI output has trailing bytes: {path}")
    return {
        "format": midi_format,
        "track_count": track_count,
        "division": division,
        "track_sizes": track_sizes,
    }


def probe_midi(worker_python: Path, path: Path) -> dict[str, Any]:
    structure = verify_midi(path)
    source = """
import json
import mido
import sys

midi = mido.MidiFile(sys.argv[1])
note_on_count = sum(
    1
    for track in midi.tracks
    for message in track
    if message.type == "note_on" and message.velocity > 0
)
print(json.dumps({"note_on_count": note_on_count, "length_sec": midi.length}))
"""
    result = run_capture([str(worker_python), "-c", source, str(path)])
    if result.returncode != 0:
        raise RuntimeError(f"Unable to parse Basic Pitch native MIDI: {result.stderr.strip()}")
    try:
        semantic = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Basic Pitch MIDI probe returned invalid JSON") from exc
    if not isinstance(semantic, dict):
        raise RuntimeError("Basic Pitch MIDI probe did not return a JSON object")
    return {**structure, **semantic}


def verify_native_event_count(midi_probe: dict[str, Any], decoded_event_count: int) -> None:
    midi_note_count = midi_probe.get("note_on_count")
    if (
        isinstance(midi_note_count, bool)
        or not isinstance(midi_note_count, int)
        or midi_note_count < 0
    ):
        raise RuntimeError("Basic Pitch MIDI probe returned an invalid note-on count")
    if midi_note_count != decoded_event_count:
        raise RuntimeError(
            "Basic Pitch native MIDI note count does not match decoded CSV events: "
            f"{midi_note_count} != {decoded_event_count}"
        )


def _verify_npy_header(payload: bytes, *, member: str, path: Path) -> dict[str, Any]:
    if len(payload) < 10 or payload[:6] != b"\x93NUMPY":
        raise RuntimeError(f"Basic Pitch NPZ member is not an NPY file: {member} in {path}")
    version = (payload[6], payload[7])
    if version == (1, 0):
        header_size_bytes = 2
        header_size = struct.unpack("<H", payload[8:10])[0]
    elif version in {(2, 0), (3, 0)}:
        if len(payload) < 12:
            raise RuntimeError(f"Basic Pitch NPY member has a truncated header: {member}")
        header_size_bytes = 4
        header_size = struct.unpack("<I", payload[8:12])[0]
    else:
        raise RuntimeError(f"Basic Pitch NPY member has unsupported version {version}: {member}")
    header_start = 8 + header_size_bytes
    header_end = header_start + header_size
    if header_end > len(payload):
        raise RuntimeError(f"Basic Pitch NPY member has a truncated header: {member}")
    encoding = "latin1" if version in {(1, 0), (2, 0)} else "utf-8"
    try:
        header = ast.literal_eval(payload[header_start:header_end].decode(encoding).strip())
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Basic Pitch NPY member has an invalid metadata header: {member}"
        ) from exc
    if (
        not isinstance(header, dict)
        or set(header) != {"descr", "fortran_order", "shape"}
        or not isinstance(header["descr"], str)
        or not isinstance(header["fortran_order"], bool)
        or not isinstance(header["shape"], tuple)
    ):
        raise RuntimeError(f"Basic Pitch NPY member has an unsupported metadata header: {member}")
    return {
        "version": list(version),
        "descr": header["descr"],
        "fortran_order": header["fortran_order"],
        "shape": list(header["shape"]),
    }


def verify_npz(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Basic Pitch NPZ output is missing or empty: {path}")
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"Basic Pitch NPZ output is not a ZIP archive: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            members = sorted(archive.namelist())
            member_payload = (
                archive.read("basic_pitch_model_output.npy")
                if "basic_pitch_model_output.npy" in members
                else None
            )
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Cannot parse Basic Pitch NPZ output {path}: {exc}") from exc
    if bad_member is not None:
        raise RuntimeError(f"Basic Pitch NPZ output has a corrupt member {bad_member!r}: {path}")
    if "basic_pitch_model_output.npy" not in members:
        raise RuntimeError("Basic Pitch NPZ output does not contain basic_pitch_model_output.npy")
    assert member_payload is not None
    model_output_header = _verify_npy_header(
        member_payload,
        member="basic_pitch_model_output.npy",
        path=path,
    )
    return {
        "members": members,
        "basic_pitch_model_output": model_output_header,
    }


def verify_worker_environment(
    worker_env: Path,
    diagnostics: dict[str, Any],
    pins: dict[str, Any],
) -> dict[str, Any]:
    if diagnostics.get("python", "").split(".")[:2] != ["3", "10"]:
        raise RuntimeError(
            f"Basic Pitch worker must use Python 3.10; got {diagnostics.get('python')!r}"
        )
    if diagnostics.get("basic_pitch") != pins["package"]["version"]:
        raise RuntimeError(
            "Basic Pitch version does not match pins.json: "
            f"{diagnostics.get('basic_pitch')!r} != {pins['package']['version']!r}"
        )
    if diagnostics.get("numpy") != pins["runtime"]["numpy"]:
        raise RuntimeError(
            "NumPy version does not match pins.json: "
            f"{diagnostics.get('numpy')!r} != {pins['runtime']['numpy']!r}"
        )
    if diagnostics.get("onnxruntime") != pins["runtime"]["onnxruntime"]:
        raise RuntimeError(
            "ONNX Runtime version does not match pins.json: "
            f"{diagnostics.get('onnxruntime')!r} != "
            f"{pins['runtime']['onnxruntime']!r}"
        )
    if diagnostics.get("setuptools") != pins["runtime"]["setuptools"]:
        raise RuntimeError(
            "setuptools version does not match pins.json: "
            f"{diagnostics.get('setuptools')!r} != "
            f"{pins['runtime']['setuptools']!r}"
        )
    expected_provider = pins["runtime"]["onnxruntime_provider"]
    if expected_provider not in diagnostics.get("onnxruntime_available_providers", []):
        raise RuntimeError(f"Pinned ONNX Runtime provider is unavailable: {expected_provider}")
    if diagnostics.get("model_type") != "ONNX":
        raise RuntimeError(
            f"Basic Pitch did not load the ONNX serialization: {diagnostics.get('model_type')!r}"
        )
    if diagnostics.get("model_session_providers") != [expected_provider]:
        raise RuntimeError(
            "Basic Pitch ONNX session is not CPU-only: "
            f"{diagnostics.get('model_session_providers')!r}"
        )

    raw_model_path = diagnostics.get("model_path")
    if not isinstance(raw_model_path, str):
        raise RuntimeError("Basic Pitch diagnostics did not report a model path")
    model_path = Path(raw_model_path).expanduser().resolve()
    try:
        model_path.relative_to(worker_env)
    except ValueError as exc:
        raise RuntimeError(
            f"Bundled Basic Pitch model is outside the isolated worker env: {model_path}"
        ) from exc
    if not model_path.is_file():
        raise FileNotFoundError(f"Bundled Basic Pitch ONNX model not found: {model_path}")
    if model_path.name != pins["model"]["bundled_filename"]:
        raise RuntimeError(
            f"Bundled Basic Pitch model filename does not match pins.json: {model_path.name}"
        )
    actual_size = model_path.stat().st_size
    actual_hash = sha256_file(model_path)
    if actual_size != pins["model"]["size_bytes"]:
        raise RuntimeError(
            "Bundled Basic Pitch model size does not match pins.json: "
            f"{actual_size} != {pins['model']['size_bytes']}"
        )
    if actual_hash != pins["model"]["sha256"]:
        raise RuntimeError(
            "Bundled Basic Pitch model SHA-256 does not match pins.json: "
            f"{actual_hash} != {pins['model']['sha256']}"
        )
    return {
        "path": str(model_path),
        "filename": model_path.name,
        "sha256": actual_hash,
        "size_bytes": actual_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one immutable Basic Pitch 0.4.0 ONNX CPU vocal-stem baseline "
            "and normalize its native CSV."
        )
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id)
    project_dir = args.project.expanduser().resolve()
    audio = args.audio.expanduser().resolve()
    worker_env = args.worker_env.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve()
    pins = load_json(pins_path)
    worker_python = worker_env / "bin" / "python"
    basic_pitch_cli = worker_env / "bin" / "basic-pitch"
    run_dir = project_dir / "runs" / run_id

    if run_dir.exists():
        raise RuntimeError(f"Refusing to reuse immutable run directory: {run_dir}")
    if not audio.is_file():
        raise FileNotFoundError(f"Basic Pitch input audio not found: {audio}")
    if not worker_python.is_file() or not basic_pitch_cli.is_file():
        raise FileNotFoundError(f"Basic Pitch worker environment is incomplete: {worker_env}")

    audio_sha256 = sha256_file(audio)
    lineage = input_lineage(project_dir, audio, audio_sha256=audio_sha256)
    raw_dir = run_dir / "raw" / "native"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for path in (raw_dir, normalized_dir, logs_dir):
        path.mkdir(parents=True)

    native_prefix = f"{audio.stem}_basic_pitch"
    native_midi = raw_dir / f"{native_prefix}.mid"
    native_npz = raw_dir / f"{native_prefix}.npz"
    native_csv = raw_dir / f"{native_prefix}.csv"
    decoding = dict(pins["decoding"])
    command = [
        str(basic_pitch_cli),
        str(raw_dir),
        str(audio),
        "--model-serialization",
        "onnx",
        "--save-midi",
        "--save-model-outputs",
        "--save-note-events",
        "--onset-threshold",
        str(decoding["onset_threshold"]),
        "--frame-threshold",
        str(decoding["frame_threshold"]),
        "--minimum-note-length",
        str(decoding["minimum_note_length_ms"]),
        "--midi-tempo",
        str(decoding["midi_tempo_bpm"]),
    ]
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "basic_pitch",
        "model": pins["model"]["name"],
        "input": {"path": str(audio), "sha256": audio_sha256},
        "input_lineage": lineage,
        "command": command,
        "decoding": decoding,
        "native_outputs": {
            "midi": str(native_midi.relative_to(run_dir)),
            "model_outputs_npz": str(native_npz.relative_to(run_dir)),
            "note_events_csv": str(native_csv.relative_to(run_dir)),
        },
    }
    atomic_write_json(run_dir / "request.json", request)

    source_model = (
        f"{pins['package']['upstream_repository']}@"
        f"{pins['package']['upstream_git_commit']}:"
        f"{pins['model']['name']}"
    )
    started_at = utc_now()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "project_id": project_dir.name,
        "worker": "basic_pitch",
        "model": pins["model"]["name"],
        "started_at": started_at,
        "ended_at": None,
        "status": "running",
        "command": command,
        "inputs": [request["input"]],
        "input_lineage": lineage,
        "outputs": [],
        "native_outputs": request["native_outputs"],
        "environment": None,
        "code": {
            **git_state(REPO_ROOT),
            "pins_sha256": sha256_file(pins_path),
            "source_files": source_records(pins_path),
        },
        "model_provenance": {
            "package": pins["package"],
            "model": pins["model"],
            "serialization": pins["runtime"]["serialization"],
            "onnxruntime_provider": pins["runtime"]["onnxruntime_provider"],
            "license": pins["license"],
        },
        "decoding": decoding,
        "reproducibility": {
            "random_seed": None,
            "random_seed_reason": (
                "Basic Pitch 0.4.0 inference exposes no stochastic sampling or "
                "seed option; repeatability still requires separate measurement."
            ),
            "song_specific_tuning": False,
            "repeatability_assessed_separately": False,
        },
        "scheduler": slurm_context(),
        "timings": {},
        "metrics": {},
        "validation": {},
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)

    try:
        diagnostics = worker_diagnostics(worker_python)
        verified_model = verify_worker_environment(worker_env, diagnostics, pins)
        diagnostics["hostname"] = platform.node()
        diagnostics["os"] = platform.platform()
        diagnostics["verified_model"] = verified_model
        manifest["environment"] = diagnostics
        atomic_write_json(logs_dir / "device.json", diagnostics)
        atomic_write_json(run_dir / "run_manifest.json", manifest)

        write_text_log(
            logs_dir / "help.txt",
            run_capture([str(basic_pitch_cli), "--help"]),
        )
        command_environment = os.environ.copy()
        command_environment["CUDA_VISIBLE_DEVICES"] = ""
        command_environment.setdefault("PYTHONHASHSEED", "0")
        result = run_logged(
            command,
            stdout_path=logs_dir / "basic-pitch.stdout",
            stderr_path=logs_dir / "basic-pitch.stderr",
            env=command_environment,
        )
        manifest["timings"]["inference_and_decode"] = result
        if result["exit_code"] != 0:
            raise RuntimeError("Basic Pitch command failed")

        midi_validation = probe_midi(worker_python, native_midi)
        npz_validation = verify_npz(native_npz)
        summary = normalize_note_events(
            native_csv,
            normalized_dir / "events.jsonl",
            normalized_dir / "summary.json",
            run_id=run_id,
            source_model=source_model,
            instrument=(
                "voice"
                if lineage["kind"] == "separator_vocal_stem"
                else "other"
            ),
        )
        verify_native_event_count(midi_validation, summary["event_count"])
        manifest["validation"] = {
            "midi": midi_validation,
            "model_outputs_npz": npz_validation,
            "note_events_csv": {
                "parsed": True,
                "event_count": summary["event_count"],
            },
        }
        manifest["metrics"] = {
            "descriptive_event_summary": summary,
            "accuracy_claimed": False,
            "human_listening_complete": False,
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
