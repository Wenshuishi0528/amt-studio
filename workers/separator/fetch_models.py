from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKER_DIR = Path(__file__).resolve().parent
DEFAULT_PINS = WORKER_DIR / "pins.json"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError(f"Unsupported JSON object in {path}")
    return value


def file_records(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def bundle_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def install_pinned_registry(model_dir: Path, registry: dict[str, Any]) -> dict[str, Any]:
    destination = model_dir / registry["path"]
    if destination.exists():
        actual_hash = sha256_file(destination)
        if actual_hash != registry["sha256"]:
            raise RuntimeError(
                "Existing separator model registry has the wrong hash; "
                f"refusing to overwrite {destination}"
            )
    else:
        temporary = destination.with_suffix(destination.suffix + ".download")
        temporary.unlink(missing_ok=True)
        try:
            with (
                urllib.request.urlopen(registry["url"]) as response,  # noqa: S310
                temporary.open("wb") as handle,
            ):
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
            actual_hash = sha256_file(temporary)
            if actual_hash != registry["sha256"]:
                raise RuntimeError(
                    "Downloaded separator model registry hash mismatch: "
                    f"{actual_hash} != {registry['sha256']}"
                )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(destination.relative_to(model_dir)),
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "source": registry["url"],
        "revision": registry["revision"],
    }


def validate_expected_path(model_dir: Path, expected: dict[str, Any]) -> Path:
    relative_path = Path(expected["path"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"Unsafe model path in pins.json: {relative_path}")
    destination = model_dir / relative_path
    if destination.parent != model_dir:
        raise ValueError("Task003 model bundles must use flat files in the pinned model directory")
    return destination


def validate_expected_file(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected downloaded model file is missing: {path}")
    size_bytes = path.stat().st_size
    if size_bytes != expected["size_bytes"]:
        raise RuntimeError(
            f"Unexpected size for {path.name}: {size_bytes} != {expected['size_bytes']}"
        )
    actual_hash = sha256_file(path)
    pinned_hash = expected.get("sha256")
    if pinned_hash is not None and actual_hash != pinned_hash:
        raise RuntimeError(f"Pinned hash mismatch for {path.name}: {actual_hash} != {pinned_hash}")
    return {
        "path": expected["path"],
        "sha256": actual_hash,
        "size_bytes": size_bytes,
        "source": expected["source"],
        "hash_was_pre_pinned": pinned_hash is not None,
    }


def download_expected_file_atomic(
    model_dir: Path,
    expected: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    destination = validate_expected_path(model_dir, expected)
    replacing_invalid_cache = False
    if destination.exists():
        try:
            record = validate_expected_file(destination, expected)
        except (FileNotFoundError, RuntimeError):
            replacing_invalid_cache = True
        else:
            return record, {
                "path": expected["path"],
                "source": expected["source"],
                "status": "verified_cached",
                "size_bytes": record["size_bytes"],
                "sha256": record["sha256"],
            }

    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        expected["source"],
        headers={"User-Agent": "AMT-Studio/0.1 pinned-model-fetch"},
    )
    bytes_written = 0
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,  # noqa: S310
            temporary.open("wb") as handle,
        ):
            while chunk := response.read(8 * 1024 * 1024):
                handle.write(chunk)
                bytes_written += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        record = validate_expected_file(temporary, expected)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return record, {
        "path": expected["path"],
        "source": expected["source"],
        "status": (
            "replaced_invalid_cache" if replacing_invalid_cache else "downloaded_atomically"
        ),
        "bytes_written": bytes_written,
        "size_bytes": record["size_bytes"],
        "sha256": record["sha256"],
    }


def validate_preset_files(
    model_dir: Path,
    preset: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for expected in preset["expected_files"]:
        path = validate_expected_path(model_dir, expected)
        records.append(validate_expected_file(path, expected))
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download pinned separator models and record every cache file hash."
    )
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker_env = args.worker_env.expanduser().resolve()
    model_dir = args.model_dir.expanduser().resolve()
    output = args.output.expanduser().resolve()
    pins = load_json(args.pins.expanduser().resolve())
    executable = worker_env / "bin" / "audio-separator"
    if not executable.is_file():
        raise FileNotFoundError(f"audio-separator executable not found: {executable}")
    model_dir.mkdir(parents=True, exist_ok=True)
    registry_record = install_pinned_registry(model_dir, pins["model_registry"])

    version_command = [str(executable), "--version"]
    command_environment = os.environ.copy()
    command_environment.pop("AUDIO_SEPARATOR_MODEL_DIR", None)
    version_result = subprocess.run(
        version_command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=command_environment,
    )
    version_probe = {
        "argv": version_command,
        "exit_code": version_result.returncode,
        "stdout": version_result.stdout,
        "stderr": version_result.stderr,
    }
    if version_result.returncode != 0:
        atomic_write_json(
            output,
            {
                "schema_version": 1,
                "status": "failed",
                "generated_at": datetime.now(UTC).isoformat(),
                "package": pins["package"],
                "model_registry": registry_record,
                "version_probe": version_probe,
                "download_actions": [],
                "files": file_records(model_dir),
            },
        )
        return version_result.returncode

    unique_expected: dict[str, dict[str, Any]] = {}
    for preset in pins["presets"].values():
        for expected in preset["expected_files"]:
            previous = unique_expected.get(expected["path"])
            if previous is not None and previous != expected:
                raise ValueError(f"Conflicting pinned records for model file {expected['path']}")
            unique_expected[expected["path"]] = expected

    download_actions: list[dict[str, Any]] = []
    preset_bundles: dict[str, Any] = {}
    try:
        for expected in unique_expected.values():
            if expected["path"] == pins["model_registry"]["path"]:
                continue
            _, action = download_expected_file_atomic(model_dir, expected)
            download_actions.append(action)

        for preset_name, preset in pins["presets"].items():
            records = validate_preset_files(model_dir, preset)
            preset_bundles[preset_name] = {
                "model_filename": preset["model_filename"],
                "files": records,
                "bundle_sha256": bundle_sha256(records),
            }
    except (FileNotFoundError, OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
        atomic_write_json(
            output,
            {
                "schema_version": 1,
                "status": "failed",
                "generated_at": datetime.now(UTC).isoformat(),
                "package": pins["package"],
                "model_registry": registry_record,
                "version_probe": version_probe,
                "download_actions": download_actions,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "files": file_records(model_dir),
            },
        )
        return 1

    atomic_write_json(
        output,
        {
            "schema_version": 1,
            "status": "succeeded",
            "generated_at": datetime.now(UTC).isoformat(),
            "package": pins["package"],
            "model_registry": registry_record,
            "version_probe": version_probe,
            "download_actions": download_actions,
            "preset_bundles": preset_bundles,
            "files": file_records(model_dir),
        },
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
