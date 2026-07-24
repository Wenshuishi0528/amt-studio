from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audio import canonicalize_audio, probe_audio
from .utils import atomic_write_json, sha256_file, slugify


class ProjectError(RuntimeError):
    """Raised for invalid project operations."""


def initialize_project(
    source_audio: Path,
    output_dir: Path,
    *,
    title: str | None = None,
    copy_original: bool = True,
) -> dict[str, Any]:
    source_audio = source_audio.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source_audio.is_file():
        raise ProjectError(f"Audio file does not exist: {source_audio}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ProjectError(f"Output directory is not empty: {output_dir}")

    project_id = slugify(output_dir.name or source_audio.stem)
    display_title = title or source_audio.stem
    original_dir = output_dir / "audio" / "original"
    canonical_dir = output_dir / "audio" / "canonical"
    for relative in [
        original_dir,
        canonical_dir,
        output_dir / "audio" / "stems",
        output_dir / "annotations" / "references",
        output_dir / "annotations" / "corrections",
        output_dir / "runs",
        output_dir / "fusion",
        output_dir / "exports",
        output_dir / "reports",
    ]:
        relative.mkdir(parents=True, exist_ok=True)

    original_target = original_dir / source_audio.name
    if copy_original:
        shutil.copy2(source_audio, original_target)
        imported_path = original_target
        import_mode = "copied"
    else:
        imported_path = source_audio
        import_mode = "external_reference"

    source_hash = sha256_file(source_audio)
    source_probe = probe_audio(source_audio)
    canonical_path = canonical_dir / "mix.flac"
    canonical_command = canonicalize_audio(source_audio, canonical_path)
    canonical_hash = sha256_file(canonical_path)
    canonical_probe = probe_audio(canonical_path)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "project_id": project_id,
        "title": display_title,
        "created_at": datetime.now(UTC).isoformat(),
        "private": True,
        "source": {
            "original_filename": source_audio.name,
            "import_mode": import_mode,
            "stored_path": str(imported_path.relative_to(output_dir))
            if imported_path.is_relative_to(output_dir)
            else None,
            "external_path_recorded": None,
            "sha256": source_hash,
            "metadata": source_probe,
        },
        "canonical_audio": {
            "path": str(canonical_path.relative_to(output_dir)),
            "sha256": canonical_hash,
            "metadata": canonical_probe,
            "command": canonical_command,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "hostname": platform.node(),
            "git": _git_state(output_dir.parent),
        },
        "status": {
            "ingested": True,
            "baselines_completed": [],
            "reference_annotations": False,
            "fusion_completed": False,
        },
    }
    atomic_write_json(output_dir / "manifest.json", manifest)
    return manifest


def load_project(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir.expanduser().resolve() / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectError(f"Project manifest not found: {manifest_path}")
    import json

    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _git_state(start: Path) -> dict[str, Any]:
    try:
        root = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", root, "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"root": root, "commit": commit, "dirty": dirty}
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {"root": None, "commit": None, "dirty": None}
