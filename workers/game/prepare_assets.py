from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"Unsupported JSON object in {path}")
    return value


def run_git(source_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_dir), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_source(source_dir: Path, package: dict[str, Any]) -> dict[str, Any]:
    expected_commit = package["upstream_git_commit"]
    actual_commit = run_git(source_dir, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"GAME source commit mismatch: expected {expected_commit}, got {actual_commit}"
        )
    status = run_git(source_dir, "status", "--porcelain")
    if status:
        raise RuntimeError("GAME source checkout must be clean")
    infer_script = source_dir / "infer.py"
    if not infer_script.is_file():
        raise FileNotFoundError(f"GAME infer.py is missing: {infer_script}")
    return {
        "repository": package["repository"],
        "version": package["version"],
        "commit": actual_commit,
        "path": str(source_dir),
        "infer_script": str(infer_script),
        "infer_script_sha256": sha256_file(infer_script),
        "license": package["license"],
        "dirty": False,
    }


def download_archive(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=destination.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AMT-Studio/Task004 GAME asset fetcher"},
        )
        with urllib.request.urlopen(request) as response, temporary_path.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def verify_archive(path: Path, model: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"GAME model archive is missing or unsafe: {path}")
    actual_size = path.stat().st_size
    actual_hash = sha256_file(path)
    if actual_size != model["archive_size_bytes"]:
        raise RuntimeError(
            f"GAME archive size mismatch: {actual_size} != {model['archive_size_bytes']}"
        )
    if actual_hash != model["archive_sha256"]:
        raise RuntimeError(
            f"GAME archive SHA-256 mismatch: {actual_hash} != {model['archive_sha256']}"
        )
    return {
        "url": model["archive_url"],
        "filename": model["archive_filename"],
        "path": str(path),
        "sha256": actual_hash,
        "size_bytes": actual_size,
    }


def _safe_zip_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in info.filename
    ):
        raise RuntimeError(f"Unsafe path in GAME archive: {info.filename!r}")
    unix_mode = info.external_attr >> 16
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise RuntimeError(f"Symbolic link is forbidden in GAME archive: {info.filename!r}")
    return path


def extract_archive(archive: Path, model_dir: Path) -> None:
    if model_dir.exists() or model_dir.is_symlink():
        return
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{model_dir.name}.", dir=model_dir.parent))
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [(info, _safe_zip_member(info)) for info in bundle.infolist()]
            if not members:
                raise RuntimeError("GAME model archive is empty")
            for info, relative_path in members:
                destination = temporary_dir.joinpath(*relative_path.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        os.replace(temporary_dir, model_dir)
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def file_records(model_dir: Path) -> list[dict[str, Any]]:
    records = [
        {
            "path": path.relative_to(model_dir).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(model_dir.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]
    if not records:
        raise RuntimeError(f"GAME model directory contains no regular files: {model_dir}")
    return records


def _single_file(model_dir: Path, pattern: str, *, label: str) -> Path:
    matches = [path for path in model_dir.rglob(pattern) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one GAME {label} matching {pattern!r}, found {len(matches)}"
        )
    return matches[0].resolve()


def verify_model_layout(
    model_dir: Path,
    model: dict[str, Any],
) -> tuple[list[dict[str, Any]], Path, Path, Path]:
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise RuntimeError(f"GAME model directory is missing or unsafe: {model_dir}")
    records = file_records(model_dir)
    expected = model.get("expected_files")
    if not isinstance(expected, list):
        raise RuntimeError("GAME pins model.expected_files must be a list")
    if expected and records != expected:
        raise RuntimeError("Extracted GAME model files do not match pinned expected_files")

    model_path = _single_file(model_dir, "*.pt", label="PyTorch model")
    config_path = _single_file(model_dir, "config.yaml", label="config")
    lang_map_path = _single_file(model_dir, "lang_map.json", label="language map")
    if not (model_path.parent == config_path.parent and model_path.parent == lang_map_path.parent):
        raise RuntimeError("GAME model, config.yaml, and lang_map.json must be siblings")
    return records, model_path, config_path, lang_map_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download, extract, and hash-pin the official GAME model archive."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dir = args.source_dir.expanduser().resolve(strict=True)
    asset_root = args.asset_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    pins_path = args.pins.expanduser().resolve(strict=True)
    pins = load_json(pins_path)
    model = pins["model"]

    asset_root.mkdir(parents=True, exist_ok=True)
    if asset_root.is_symlink():
        raise RuntimeError(f"GAME asset root cannot be a symbolic link: {asset_root}")
    archive = asset_root / model["archive_filename"]
    if not archive.exists():
        download_archive(model["archive_url"], archive)
    archive_record = verify_archive(archive, model)

    model_dir = asset_root / model["directory_name"]
    extract_archive(archive, model_dir)
    records, model_path, config_path, lang_map_path = verify_model_layout(model_dir, model)
    source_record = verify_source(source_dir, pins["package"])
    provenance = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source_record,
        "archive": archive_record,
        "model": {
            "name": model["name"],
            "release": model["release"],
            "license": model["license"],
            "license_scope": model["license_scope"],
            "directory": str(model_dir),
            "files": records,
            "model_path": str(model_path),
            "model_relative_path": model_path.relative_to(model_dir).as_posix(),
            "config_path": str(config_path),
            "config_relative_path": config_path.relative_to(model_dir).as_posix(),
            "lang_map_path": str(lang_map_path),
            "lang_map_relative_path": lang_map_path.relative_to(model_dir).as_posix(),
        },
        "pins": {
            "path": str(pins_path),
            "sha256": sha256_file(pins_path),
            "expected_files_were_pinned": bool(model["expected_files"]),
        },
    }
    atomic_write_json(output, provenance)
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
