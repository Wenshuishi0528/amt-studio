#!/usr/bin/env python3
"""Freeze an audio-only benchmark pack before reference or candidate inspection."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.benchmark import BenchmarkError, BenchmarkSpec, canonical_json_sha256
from amt_core.utils import atomic_write_json, sha256_file


class ReferencePackError(RuntimeError):
    """Raised when a benchmark pack cannot be frozen safely."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReferencePackError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReferencePackError(f"{label} must be a JSON object")
    return value


def _canonical_audio(project_dir: Path, project_id: str) -> tuple[Path, dict[str, Any]]:
    manifest_path = project_dir / "manifest.json"
    manifest = _load_object(manifest_path, label="project manifest")
    if manifest.get("schema_version") != 1 or manifest.get("project_id") != project_id:
        raise ReferencePackError("project manifest identity does not match benchmark spec")
    record = manifest.get("canonical_audio")
    if not isinstance(record, dict):
        raise ReferencePackError("project manifest has no canonical_audio record")
    relative_path = record.get("path")
    expected_hash = record.get("sha256")
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or relative_path.startswith("/")
        or ".." in Path(relative_path).parts
    ):
        raise ReferencePackError("canonical audio path is unsafe")
    unresolved_audio_path = project_dir / relative_path
    cursor = project_dir
    for part in Path(relative_path).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ReferencePackError("canonical audio path contains a symbolic link")
    audio_path = unresolved_audio_path.resolve(strict=True)
    try:
        audio_path.relative_to(project_dir.resolve(strict=True))
    except ValueError as exc:
        raise ReferencePackError("canonical audio escapes the project directory") from exc
    if not audio_path.is_file():
        raise ReferencePackError("canonical audio must be a regular non-symlink file")
    actual_hash = sha256_file(audio_path)
    if actual_hash != expected_hash:
        raise ReferencePackError("canonical audio SHA-256 does not match project manifest")
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise ReferencePackError("canonical audio metadata is missing")
    duration = metadata.get("duration_sec")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        raise ReferencePackError("canonical audio duration is invalid")
    return audio_path, {"sha256": actual_hash, "duration_sec": float(duration)}


def _tool_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReferencePackError(f"Cannot run {executable}: {exc}") from exc
    return result.stdout.splitlines()[0].strip()


def _render_excerpt(
    ffmpeg: str,
    source: Path,
    destination: Path,
    *,
    start_sec: float,
    duration_sec: float,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-ss",
        f"{start_sec:.9f}",
        "-t",
        f"{duration_sec:.9f}",
        "-map",
        "0:a:0",
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else ""
        raise ReferencePackError(f"ffmpeg excerpt render failed: {stderr or exc}") from exc
    return command


def _validate_wav(path: Path, expected_duration: float) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
    except (OSError, wave.Error) as exc:
        raise ReferencePackError(f"Cannot validate excerpt WAV {path}: {exc}") from exc
    expected_frames = round(expected_duration * 44100)
    if (
        channels != 2
        or sample_width != 2
        or sample_rate != 44100
        or abs(frame_count - expected_frames) > 1
    ):
        raise ReferencePackError(
            "excerpt WAV is not exact 44.1 kHz stereo PCM or has unexpected duration"
        )
    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frame_count": frame_count,
        "expected_frame_count": expected_frames,
        "frame_error": frame_count - expected_frames,
    }


def _readme(benchmark_id: str, split: str) -> str:
    return f"""# Reference annotation pack: {benchmark_id}

Split: `{split}`

This directory was frozen from the canonical mix before Task 006 reference
annotation. `benchmark_manifest.json` is the source of truth.

For each excerpt:

1. Listen only to `mix.wav` while creating the first reference.
2. Store notes in `reference_notes.jsonl` using canonical-mix seconds, not
   excerpt-local seconds. The manifest records `audio_start_sec`.
3. Include notes whose onset is inside `evaluation_start_sec <= onset <
   evaluation_end_sec`; the extra audio on both sides is context only.
4. Record `annotator_confidence` and every applicable `ambiguity_tags` value.
5. Do not mark an excerpt human-confirmed by editing `annotation.json`.
   Run `scripts/seal_reference_pack.py` after actual human review.

Candidate renders must not be placed in this audio-only directory before the
initial reference is sealed.
"""


def create_reference_pack(
    project_dir: Path,
    spec_path: Path,
    output_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
    context_sec: float = 1.0,
) -> dict[str, Any]:
    if context_sec < 0:
        raise ReferencePackError("context_sec must be non-negative")
    try:
        spec = BenchmarkSpec.from_dict(_load_object(spec_path, label="benchmark spec"))
    except BenchmarkError as exc:
        raise ReferencePackError(str(exc)) from exc
    project_dir = project_dir.resolve(strict=True)
    source, audio = _canonical_audio(project_dir, spec.project_id)
    for excerpt in spec.excerpts:
        if excerpt.start_sec + excerpt.duration_sec > audio["duration_sec"] + 1e-6:
            raise ReferencePackError(f"excerpt exceeds canonical audio: {excerpt.excerpt_id}")
    if output_dir.exists():
        raise ReferencePackError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_version = _tool_version(ffmpeg)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    commands: list[list[str]] = []
    try:
        frozen_excerpts: list[dict[str, Any]] = []
        for excerpt in spec.excerpts:
            evaluation_end = excerpt.start_sec + excerpt.duration_sec
            audio_start = max(0.0, excerpt.start_sec - context_sec)
            audio_end = min(audio["duration_sec"], evaluation_end + context_sec)
            audio_duration = audio_end - audio_start
            excerpt_dir = temporary / "excerpts" / excerpt.excerpt_id
            excerpt_dir.mkdir(parents=True)
            mix_path = excerpt_dir / "mix.wav"
            command = _render_excerpt(
                ffmpeg,
                source,
                mix_path,
                start_sec=audio_start,
                duration_sec=audio_duration,
            )
            commands.append(
                [
                    *command[:-1],
                    str(output_dir / "excerpts" / excerpt.excerpt_id / "mix.wav"),
                ]
            )
            validation = _validate_wav(mix_path, audio_duration)
            reference_path = excerpt_dir / "reference_notes.jsonl"
            reference_path.write_text("", encoding="utf-8")
            annotation_path = excerpt_dir / "annotation.json"
            atomic_write_json(
                annotation_path,
                {
                    "schema": "amt-annotation-plan/v1",
                    "excerpt_id": excerpt.excerpt_id,
                    "status_at_pack_creation": "unsealed",
                    "coordinate_system": "canonical_mix_seconds",
                    "reference_notes_path": "reference_notes.jsonl",
                    "notes": (
                        "Human confirmation is recorded only in reference_seal.json."
                    ),
                },
            )
            frozen_excerpts.append(
                {
                    **excerpt.freeze_dict(),
                    "evaluation_start_sec": excerpt.start_sec,
                    "evaluation_end_sec": evaluation_end,
                    "audio_start_sec": audio_start,
                    "audio_end_sec": audio_end,
                    "audio_context_sec_requested": context_sec,
                    "mix": {
                        "path": f"excerpts/{excerpt.excerpt_id}/mix.wav",
                        "sha256": sha256_file(mix_path),
                        "size_bytes": mix_path.stat().st_size,
                        "pcm_validation": validation,
                    },
                    "reference_notes_path": (
                        f"excerpts/{excerpt.excerpt_id}/reference_notes.jsonl"
                    ),
                    "annotation_plan_path": (
                        f"excerpts/{excerpt.excerpt_id}/annotation.json"
                    ),
                }
            )

        base_freeze = spec.freeze_dict(canonical_audio_sha256=audio["sha256"])
        freeze_payload = {
            **base_freeze,
            "canonical_audio_duration_sec": audio["duration_sec"],
            "coordinate_system": "canonical_mix_seconds",
            "boundary_policy": (
                "include reference and estimate notes with onset in "
                "[evaluation_start_sec, evaluation_end_sec)"
            ),
            "excerpts": frozen_excerpts,
        }
        manifest = {
            "schema": "amt-benchmark-pack/v1",
            "status": "awaiting_human_annotation",
            "created_at": datetime.now(UTC).isoformat(),
            "benchmark_freeze_sha256": canonical_json_sha256(freeze_payload),
            "freeze_payload": freeze_payload,
            "spec": {
                "sha256": sha256_file(spec_path),
                "canonical_json_sha256": canonical_json_sha256(
                    _load_object(spec_path, label="benchmark spec")
                ),
            },
            "tool": {
                "script": "scripts/create_reference_pack.py",
                "ffmpeg_version": ffmpeg_version,
            },
            "commands": commands,
            "claims": {
                "human_reference_available": False,
                "baseline_metrics_available": False,
                "blind_test": spec.split == "blind_test",
                "accuracy_claimed": False,
            },
        }
        atomic_write_json(temporary / "benchmark_manifest.json", manifest)
        (temporary / "README.md").write_text(
            _readme(spec.benchmark_id, spec.split),
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--context-sec", type=float, default=1.0)
    args = parser.parse_args()
    manifest = create_reference_pack(
        args.project_dir,
        args.spec,
        args.output_dir,
        ffmpeg=args.ffmpeg,
        context_sec=args.context_sec,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
