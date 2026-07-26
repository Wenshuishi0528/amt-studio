from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .utils import atomic_write_json, load_json, sha256_file

BATCH_SPEC_CONTRACT = "amt-batch-spec/v1"
BATCH_MANIFEST_CONTRACT = "amt-batch-manifest/v1"
BATCH_COMPLETE_CONTRACT = "amt-batch-complete/v1"
BATCH_INDEX_CONTRACT = "amt-batch-index/v1"
BATCH_SELECTION_CONTRACT = "amt-batch-selection/v1"
BATCH_EXECUTION_CONTRACT = "amt-batch-execution/v2"

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z", re.ASCII)
ENVIRONMENT_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MODEL_TOKEN_PATTERN = re.compile(r"\{model:([A-Za-z0-9][A-Za-z0-9._-]{0,159})\}")
TOKEN_PATTERN = re.compile(r"\{[A-Za-z0-9:._-]+\}")


class BatchValidationError(ValueError):
    """Raised when a batch specification, manifest, or cache is invalid."""


class BatchInterrupted(RuntimeError):
    """Raised when a stage is interrupted and can be resumed safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_PATTERN.fullmatch(value) is None or ".." in value:
        raise BatchValidationError(f"{label} is missing or unsafe")
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise BatchValidationError(f"{label} must be a lowercase SHA-256")
    return value


def _relative_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise BatchValidationError(f"{label} must be a safe POSIX relative path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise BatchValidationError(f"{label} contains an unsafe path component")
    return value


def _absolute_file(value: Any, *, label: str, base: Path | None = None) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchValidationError(f"{label} is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        if base is None:
            raise BatchValidationError(f"{label} must be absolute")
        path = base / path
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BatchValidationError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise BatchValidationError(f"{label} is not a file: {resolved}")
    return resolved


def _absolute_launcher(value: Any, *, label: str, base: Path | None = None) -> Path:
    """Return an absolute executable path without dereferencing its virtualenv symlink."""
    if not isinstance(value, (str, os.PathLike)) or not os.fspath(value):
        raise BatchValidationError(f"{label} is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        if base is None:
            raise BatchValidationError(f"{label} must be absolute")
        path = base / path
    path = Path(os.path.abspath(path))
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BatchValidationError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file() or not os.access(path, os.X_OK):
        raise BatchValidationError(f"{label} is not an executable file: {path}")
    return path


def _python_environment_sha256(python_path: Path) -> str:
    source = """
import hashlib
import importlib.metadata
import json
import sys

packages = sorted(
    (
        (distribution.metadata.get("Name") or "").lower(),
        distribution.version,
    )
    for distribution in importlib.metadata.distributions()
)
payload = json.dumps(
    {
        "base_prefix": sys.base_prefix,
        "packages": packages,
        "prefix": sys.prefix,
    },
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode()
print(hashlib.sha256(payload).hexdigest())
"""
    result = subprocess.run(
        [str(python_path), "-I", "-c", source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    digest = result.stdout.strip()
    if result.returncode != 0 or SHA256_PATTERN.fullmatch(digest) is None:
        raise BatchValidationError(
            f"cannot fingerprint Python environment {python_path}: {result.stderr.strip()}"
        )
    return digest


def _python_artifact(python_path: Path) -> dict[str, Any]:
    return {
        **_artifact(python_path),
        "resolved_path": str(python_path.resolve(strict=True)),
        "environment_sha256": _python_environment_sha256(python_path),
    }


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_artifact(
    value: Any,
    *,
    label: str,
    require_path: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchValidationError(f"{label} must be an object")
    raw_path = value.get("path")
    if require_path:
        path = _absolute_file(raw_path, label=f"{label}.path")
    else:
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or "\x00" in raw_path
            or not Path(raw_path).is_absolute()
        ):
            raise BatchValidationError(f"{label}.path must be an absolute path")
        path = Path(raw_path)
    digest = _sha256(value.get("sha256"), label=f"{label}.sha256")
    size = value.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise BatchValidationError(f"{label}.size_bytes must be a non-negative integer")
    return {"path": str(path), "sha256": digest, "size_bytes": size}


def _verify_artifact(value: dict[str, Any], *, label: str) -> Path:
    record = _validate_artifact(value, label=label)
    path = Path(record["path"])
    if path.stat().st_size != record["size_bytes"]:
        raise BatchValidationError(f"{label} size changed: {path}")
    if sha256_file(path) != record["sha256"]:
        raise BatchValidationError(f"{label} SHA-256 changed: {path}")
    return path


def _validate_retention(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise BatchValidationError("retention must be an object")
    allowed = {
        "max_cache_bytes",
        "max_failed_attempts_per_cache",
        "keep_recent_completed",
    }
    if set(value) != allowed:
        raise BatchValidationError(f"retention fields must be exactly {sorted(allowed)}")
    result: dict[str, int] = {}
    for key in sorted(allowed):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise BatchValidationError(f"retention.{key} must be a non-negative integer")
        result[key] = number
    if result["max_cache_bytes"] == 0:
        raise BatchValidationError("retention.max_cache_bytes must be positive")
    return result


def _validate_stage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchValidationError("stage must be an object")
    stage_id = _identifier(value.get("stage_id"), label="stage_id")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item or "\x00" in item for item in command)
    ):
        raise BatchValidationError(f"stage {stage_id!r} command must be a non-empty argv array")
    outputs = value.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise BatchValidationError(f"stage {stage_id!r} outputs must not be empty")
    normalized_outputs = [
        _relative_path(item, label=f"stage {stage_id!r} output") for item in outputs
    ]
    if len(set(normalized_outputs)) != len(normalized_outputs):
        raise BatchValidationError(f"stage {stage_id!r} has duplicate outputs")
    environment = value.get("environment", {})
    if not isinstance(environment, dict):
        raise BatchValidationError(f"stage {stage_id!r} environment must be an object")
    normalized_environment: dict[str, str] = {}
    for key, item in environment.items():
        if not isinstance(key, str) or ENVIRONMENT_KEY_PATTERN.fullmatch(key) is None:
            raise BatchValidationError(f"stage {stage_id!r} has an unsafe environment key")
        if not isinstance(item, str) or "\x00" in item:
            raise BatchValidationError(f"stage {stage_id!r} environment values must be strings")
        normalized_environment[key] = item
    return {
        "stage_id": stage_id,
        "command": command,
        "environment": normalized_environment,
        "outputs": normalized_outputs,
    }


def _cache_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "input_sha256": row["input"]["sha256"],
        "configuration_sha256": row["configuration"]["sha256"],
        "python_sha256": row["python"]["sha256"],
        "python_environment_sha256": row["python"]["environment_sha256"],
        "models": [
            {"name": model["name"], "sha256": model["artifact"]["sha256"]}
            for model in row["models"]
        ],
        "code": {
            "revision": row["code"]["revision"],
            "artifacts": [
                {"name": artifact["name"], "sha256": artifact["artifact"]["sha256"]}
                for artifact in row["code"]["artifacts"]
            ],
        },
        "stages": row["stages"],
    }
    execution_contract = row.get("execution_contract")
    if execution_contract is not None:
        payload["execution_contract"] = execution_contract
    return payload


def _absolute_directory(value: Any, *, label: str, base: Path | None = None) -> Path:
    if not isinstance(value, str) or not value:
        raise BatchValidationError(f"{label} is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        if base is None:
            raise BatchValidationError(f"{label} must be absolute")
        path = base / path
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BatchValidationError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise BatchValidationError(f"{label} is not a directory: {resolved}")
    return resolved


def _validate_repository_binding(
    *,
    repository_root: str,
    stages: list[dict[str, Any]],
    code_artifacts: list[dict[str, Any]],
    require_paths: bool,
    label: str,
) -> None:
    root = Path(repository_root)
    if not root.is_absolute():
        raise BatchValidationError(f"{label} repository_root must be absolute")
    artifact_paths = {Path(artifact["artifact"]["path"]) for artifact in code_artifacts}
    for stage in stages:
        if stage["command"][0] != "{python}":
            raise BatchValidationError(
                f"{label} stage {stage['stage_id']!r} must execute the frozen {{python}} runtime"
            )
        if len(stage["command"]) < 2 or not stage["command"][1].startswith("{repo_root}/"):
            raise BatchValidationError(
                f"{label} stage {stage['stage_id']!r} Python entry point must be a "
                "frozen {repo_root} code artifact"
            )
        values = [*stage["command"], *stage["environment"].values()]
        for value in values:
            if "{repo_root}" not in value:
                continue
            if not value.startswith("{repo_root}/") or value.count("{repo_root}") != 1:
                raise BatchValidationError(
                    f"{label} stage {stage['stage_id']!r} has an unsupported "
                    "{repo_root} reference"
                )
            relative = value.removeprefix("{repo_root}/")
            if TOKEN_PATTERN.search(relative) is not None:
                raise BatchValidationError(
                    f"{label} stage {stage['stage_id']!r} mixes tokens in a {{repo_root}} reference"
                )
            candidate = root.joinpath(*PurePosixPath(relative).parts)
            if require_paths:
                try:
                    candidate = candidate.resolve(strict=True)
                except (FileNotFoundError, OSError) as exc:
                    raise BatchValidationError(
                        f"{label} stage {stage['stage_id']!r} repository reference "
                        f"does not exist: {candidate}"
                    ) from exc
            else:
                candidate = Path(os.path.normpath(candidate))
            if candidate not in artifact_paths:
                raise BatchValidationError(
                    f"{label} stage {stage['stage_id']!r} repository reference "
                    f"is not a frozen code artifact: {candidate}"
                )


def freeze_batch_spec(spec_path: Path, output_path: Path) -> dict[str, Any]:
    spec_path = spec_path.expanduser().resolve(strict=True)
    spec = load_json(spec_path)
    if not isinstance(spec, dict):
        raise BatchValidationError("batch spec must be an object")
    if spec.get("schema_version") != 1 or spec.get("contract_version") != BATCH_SPEC_CONTRACT:
        raise BatchValidationError("unsupported batch spec contract")
    batch_id = _identifier(spec.get("batch_id"), label="batch_id")
    created_at = spec.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise BatchValidationError("created_at is required")
    retention = _validate_retention(spec.get("retention"))
    raw_rows = spec.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise BatchValidationError("rows must be a non-empty array")

    artifact_cache: dict[Path, dict[str, Any]] = {}
    runtime_cache: dict[Path, dict[str, Any]] = {}

    def cached_artifact(path: Path) -> dict[str, Any]:
        record = artifact_cache.get(path)
        if record is None:
            record = _artifact(path)
            artifact_cache[path] = record
        return dict(record)

    def cached_runtime(path: Path) -> dict[str, Any]:
        record = runtime_cache.get(path)
        if record is None:
            record = _python_artifact(path)
            runtime_cache[path] = record
        return dict(record)

    rows: list[dict[str, Any]] = []
    row_ids: set[str] = set()
    cache_keys: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise BatchValidationError("each row must be an object")
        row_id = _identifier(raw_row.get("row_id"), label="row_id")
        if row_id in row_ids:
            raise BatchValidationError(f"duplicate row_id: {row_id}")
        row_ids.add(row_id)
        authorization_id = _identifier(
            raw_row.get("authorization_id"),
            label=f"row {row_id!r} authorization_id",
        )
        repository_root = _absolute_directory(
            raw_row.get("repository_root_path"),
            label=f"row {row_id!r} repository_root_path",
            base=spec_path.parent,
        )
        python_path = _absolute_launcher(
            raw_row.get("python_path"),
            label=f"row {row_id!r} python_path",
            base=spec_path.parent,
        )
        input_path = _absolute_file(
            raw_row.get("input_path"),
            label=f"row {row_id!r} input_path",
            base=spec_path.parent,
        )
        configuration_path = _absolute_file(
            raw_row.get("configuration_path"),
            label=f"row {row_id!r} configuration_path",
            base=spec_path.parent,
        )
        raw_models = raw_row.get("models")
        if not isinstance(raw_models, list):
            raise BatchValidationError(f"row {row_id!r} models must be an array")
        models: list[dict[str, Any]] = []
        model_names: set[str] = set()
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                raise BatchValidationError(f"row {row_id!r} model must be an object")
            name = _identifier(raw_model.get("name"), label=f"row {row_id!r} model name")
            if name in model_names:
                raise BatchValidationError(f"row {row_id!r} has duplicate model {name!r}")
            model_names.add(name)
            model_path = _absolute_file(
                raw_model.get("path"),
                label=f"row {row_id!r} model {name!r} path",
                base=spec_path.parent,
            )
            models.append({"name": name, "artifact": cached_artifact(model_path)})
        models.sort(key=lambda item: item["name"])

        code_revision = raw_row.get("code_revision")
        if not isinstance(code_revision, str) or not code_revision or len(code_revision) > 200:
            raise BatchValidationError(f"row {row_id!r} code_revision is required")
        raw_code_paths = raw_row.get("code_paths")
        if not isinstance(raw_code_paths, list) or not raw_code_paths:
            raise BatchValidationError(f"row {row_id!r} code_paths must not be empty")
        code_artifacts: list[dict[str, Any]] = []
        code_names: set[str] = set()
        for raw_code in raw_code_paths:
            if not isinstance(raw_code, dict):
                raise BatchValidationError(f"row {row_id!r} code path must be an object")
            name = _identifier(
                raw_code.get("name"),
                label=f"row {row_id!r} code path name",
            )
            if name in code_names:
                raise BatchValidationError(f"row {row_id!r} has duplicate code path {name!r}")
            code_names.add(name)
            code_path = _absolute_file(
                raw_code.get("path"),
                label=f"row {row_id!r} code path {name!r}",
                base=spec_path.parent,
            )
            code_artifacts.append({"name": name, "artifact": cached_artifact(code_path)})
        code_artifacts.sort(key=lambda item: item["name"])

        raw_stages = raw_row.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise BatchValidationError(f"row {row_id!r} stages must be a non-empty array")
        stages = [_validate_stage(stage) for stage in raw_stages]
        stage_ids = [stage["stage_id"] for stage in stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise BatchValidationError(f"row {row_id!r} has duplicate stage IDs")
        _validate_repository_binding(
            repository_root=str(repository_root),
            stages=stages,
            code_artifacts=code_artifacts,
            require_paths=True,
            label=f"row {row_id!r}",
        )

        selected_outputs = raw_row.get("selected_outputs")
        if not isinstance(selected_outputs, list) or not selected_outputs:
            raise BatchValidationError(f"row {row_id!r} selected_outputs must not be empty")
        normalized_selected = [
            _relative_path(item, label=f"row {row_id!r} selected output")
            for item in selected_outputs
        ]
        available = {
            f"{stage['stage_id']}/{output}" for stage in stages for output in stage["outputs"]
        }
        if not set(normalized_selected).issubset(available):
            raise BatchValidationError(
                f"row {row_id!r} selected_outputs must reference declared stage outputs"
            )

        row = {
            "row_id": row_id,
            "authorization_id": authorization_id,
            "execution_contract": BATCH_EXECUTION_CONTRACT,
            "repository_root": str(repository_root),
            "python": cached_runtime(python_path),
            "input": cached_artifact(input_path),
            "configuration": cached_artifact(configuration_path),
            "models": models,
            "code": {
                "revision": code_revision,
                "artifacts": code_artifacts,
            },
            "stages": stages,
            "selected_outputs": normalized_selected,
        }
        cache_key = _canonical_sha256(_cache_payload(row))
        if cache_key in cache_keys:
            raise BatchValidationError(
                f"row {row_id!r} duplicates another row's content-addressed work"
            )
        cache_keys.add(cache_key)
        row["cache_key"] = cache_key
        rows.append(row)

    manifest = {
        "schema_version": 1,
        "contract_version": BATCH_MANIFEST_CONTRACT,
        "batch_id": batch_id,
        "created_at": created_at,
        "source_spec": _artifact(spec_path),
        "retention": retention,
        "rows": rows,
    }
    validate_batch_manifest(manifest)
    output_path = output_path.expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        if output_path.is_symlink() or not output_path.is_file():
            raise BatchValidationError(f"frozen manifest output is unsafe: {output_path}")
        if load_json(output_path) != manifest:
            raise BatchValidationError(
                f"frozen manifest already exists with different content: {output_path}"
            )
        return manifest
    atomic_write_json(output_path, manifest)
    return manifest


def validate_batch_manifest(
    value: Any,
    *,
    require_artifact_paths: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchValidationError("batch manifest must be an object")
    if value.get("schema_version") != 1 or value.get("contract_version") != BATCH_MANIFEST_CONTRACT:
        raise BatchValidationError("unsupported batch manifest contract")
    _identifier(value.get("batch_id"), label="batch_id")
    if not isinstance(value.get("created_at"), str) or not value["created_at"]:
        raise BatchValidationError("manifest created_at is required")
    _validate_artifact(
        value.get("source_spec"),
        label="source_spec",
        require_path=require_artifact_paths,
    )
    _validate_retention(value.get("retention"))
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise BatchValidationError("manifest rows must be a non-empty array")
    row_ids: set[str] = set()
    cache_keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise BatchValidationError("manifest row must be an object")
        row_id = _identifier(row.get("row_id"), label="row_id")
        if row_id in row_ids:
            raise BatchValidationError(f"duplicate row_id: {row_id}")
        row_ids.add(row_id)
        _identifier(row.get("authorization_id"), label=f"row {row_id!r} authorization_id")
        execution_contract = row.get("execution_contract")
        if execution_contract is not None and execution_contract != BATCH_EXECUTION_CONTRACT:
            raise BatchValidationError(
                f"row {row_id!r} has an unsupported execution_contract"
            )
        repository_root = row.get("repository_root")
        if (
            not isinstance(repository_root, str)
            or not repository_root
            or "\x00" in repository_root
            or not Path(repository_root).is_absolute()
        ):
            raise BatchValidationError(f"row {row_id!r} repository_root must be absolute")
        if require_artifact_paths:
            _absolute_directory(
                repository_root,
                label=f"row {row_id!r} repository_root",
            )
        python_record = _validate_artifact(
            row.get("python"),
            label=f"row {row_id!r} python",
            require_path=require_artifact_paths,
        )
        raw_python = row["python"]
        resolved_python_path = raw_python.get("resolved_path")
        if (
            not isinstance(resolved_python_path, str)
            or not resolved_python_path
            or "\x00" in resolved_python_path
            or not Path(resolved_python_path).is_absolute()
        ):
            raise BatchValidationError(
                f"row {row_id!r} python.resolved_path must be absolute"
            )
        _sha256(
            raw_python.get("environment_sha256"),
            label=f"row {row_id!r} python.environment_sha256",
        )
        if require_artifact_paths and Path(python_record["path"]) != Path(
            resolved_python_path
        ):
            raise BatchValidationError(
                f"row {row_id!r} Python launcher target does not match resolved_path"
            )
        _validate_artifact(
            row.get("input"),
            label=f"row {row_id!r} input",
            require_path=require_artifact_paths,
        )
        _validate_artifact(
            row.get("configuration"),
            label=f"row {row_id!r} configuration",
            require_path=require_artifact_paths,
        )
        models = row.get("models")
        if not isinstance(models, list):
            raise BatchValidationError(f"row {row_id!r} models must be an array")
        model_names: set[str] = set()
        for model in models:
            if not isinstance(model, dict):
                raise BatchValidationError(f"row {row_id!r} model must be an object")
            name = _identifier(model.get("name"), label=f"row {row_id!r} model name")
            if name in model_names:
                raise BatchValidationError(f"row {row_id!r} has duplicate model {name!r}")
            model_names.add(name)
            _validate_artifact(
                model.get("artifact"),
                label=f"row {row_id!r} model {name!r}",
                require_path=require_artifact_paths,
            )
        if models != sorted(models, key=lambda item: item["name"]):
            raise BatchValidationError(f"row {row_id!r} models must be sorted by name")
        code = row.get("code")
        if not isinstance(code, dict):
            raise BatchValidationError(f"row {row_id!r} code must be an object")
        revision = code.get("revision")
        if not isinstance(revision, str) or not revision or len(revision) > 200:
            raise BatchValidationError(f"row {row_id!r} code revision is required")
        code_artifacts = code.get("artifacts")
        if not isinstance(code_artifacts, list) or not code_artifacts:
            raise BatchValidationError(f"row {row_id!r} code artifacts must not be empty")
        code_names: set[str] = set()
        for code_artifact in code_artifacts:
            if not isinstance(code_artifact, dict):
                raise BatchValidationError(f"row {row_id!r} code artifact must be an object")
            name = _identifier(
                code_artifact.get("name"),
                label=f"row {row_id!r} code artifact name",
            )
            if name in code_names:
                raise BatchValidationError(f"row {row_id!r} has duplicate code artifact {name!r}")
            code_names.add(name)
            _validate_artifact(
                code_artifact.get("artifact"),
                label=f"row {row_id!r} code artifact {name!r}",
                require_path=require_artifact_paths,
            )
        if code_artifacts != sorted(code_artifacts, key=lambda item: item["name"]):
            raise BatchValidationError(f"row {row_id!r} code artifacts must be sorted by name")
        stages = row.get("stages")
        if not isinstance(stages, list) or not stages:
            raise BatchValidationError(f"row {row_id!r} stages must not be empty")
        normalized_stages = [_validate_stage(stage) for stage in stages]
        if normalized_stages != stages:
            raise BatchValidationError(f"row {row_id!r} stages are not normalized")
        stage_ids = [stage["stage_id"] for stage in stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise BatchValidationError(f"row {row_id!r} has duplicate stage IDs")
        _validate_repository_binding(
            repository_root=repository_root,
            stages=normalized_stages,
            code_artifacts=code_artifacts,
            require_paths=require_artifact_paths,
            label=f"row {row_id!r}",
        )
        selected = row.get("selected_outputs")
        if not isinstance(selected, list) or not selected:
            raise BatchValidationError(f"row {row_id!r} selected_outputs must not be empty")
        selected = [
            _relative_path(item, label=f"row {row_id!r} selected output") for item in selected
        ]
        available = {
            f"{stage['stage_id']}/{output}" for stage in stages for output in stage["outputs"]
        }
        if not set(selected).issubset(available):
            raise BatchValidationError(f"row {row_id!r} has an undeclared selected output")
        cache_key = _sha256(row.get("cache_key"), label=f"row {row_id!r} cache_key")
        if cache_key != _canonical_sha256(_cache_payload(row)):
            raise BatchValidationError(f"row {row_id!r} cache_key does not match its content")
        if cache_key in cache_keys:
            raise BatchValidationError("manifest contains duplicate content-addressed work")
        cache_keys.add(cache_key)
    return value


def load_batch_manifest(path: Path, *, verify_source: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve(strict=True)
    manifest = validate_batch_manifest(
        load_json(path),
        require_artifact_paths=verify_source,
    )
    if verify_source:
        _verify_artifact(manifest["source_spec"], label="source_spec")
    return manifest


def _expand(value: str, tokens: dict[str, str], models: dict[str, str]) -> str:
    def replace_model(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in models:
            raise BatchValidationError(f"command references unknown model {name!r}")
        return models[name]

    expanded = MODEL_TOKEN_PATTERN.sub(replace_model, value)
    for name, replacement in tokens.items():
        expanded = expanded.replace(f"{{{name}}}", replacement)
    unknown = TOKEN_PATTERN.search(expanded)
    if unknown is not None:
        raise BatchValidationError(f"unknown batch token: {unknown.group(0)}")
    return expanded


def _output_record(root: Path, relative: str) -> dict[str, Any]:
    _relative_path(relative, label="output")
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor /= part
        if cursor.is_symlink():
            raise BatchValidationError(f"stage output uses a symbolic link: {relative}")
    path = cursor
    root_resolved = root.resolve(strict=True)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise BatchValidationError(
            f"stage output is missing or escapes its stage: {relative}"
        ) from exc
    if not resolved.is_file():
        raise BatchValidationError(f"stage output is not a regular file: {relative}")
    return {
        "path": relative,
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _verify_output_records(root: Path, records: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise BatchValidationError(f"{label} outputs must be a non-empty array")
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, dict):
            raise BatchValidationError(f"{label} output must be an object")
        relative = _relative_path(raw.get("path"), label=f"{label} output path")
        if relative in seen:
            raise BatchValidationError(f"{label} contains duplicate output: {relative}")
        seen.add(relative)
        digest = _sha256(raw.get("sha256"), label=f"{label} output sha256")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BatchValidationError(f"{label} output size_bytes is invalid")
        observed = _output_record(root, relative)
        if observed["sha256"] != digest or observed["size_bytes"] != size:
            raise BatchValidationError(f"{label} output changed: {relative}")
        verified.append(observed)
    return verified


def _stage_complete(run_dir: Path, stage: dict[str, Any]) -> dict[str, Any] | None:
    stage_dir = run_dir / "stages" / stage["stage_id"]
    marker = stage_dir / "stage_complete.json"
    if not marker.exists():
        if stage_dir.exists():
            raise BatchValidationError(
                f"stage directory exists without completion marker: {stage['stage_id']}"
            )
        return None
    value = load_json(marker)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("stage_id") != stage["stage_id"]
        or value.get("declared_outputs") != stage["outputs"]
    ):
        raise BatchValidationError(f"stage completion marker is invalid: {stage['stage_id']}")
    _verify_output_records(stage_dir, value.get("outputs"), label=f"stage {stage['stage_id']}")
    return value


def _directory_size(path: Path) -> int:
    total = 0
    for candidate in path.rglob("*"):
        if candidate.is_file() and not candidate.is_symlink():
            total += candidate.stat().st_size
    return total


def _snapshot_layout(
    row: dict[str, Any],
    root: Path,
) -> tuple[Path, dict[str, Path], Path, Path, list[dict[str, Any]]]:
    repository_root = Path(row["repository_root"])
    input_path = root / "input"
    configuration_path = root / "configuration"
    model_paths = {
        model["name"]: root / "models" / model["name"] for model in row["models"]
    }
    frozen_repo = root / "repo"
    records = [
        {"destination": "input", "artifact": row["input"]},
        {"destination": "configuration", "artifact": row["configuration"]},
    ]
    records.extend(
        {
            "destination": f"models/{model['name']}",
            "artifact": model["artifact"],
        }
        for model in row["models"]
    )
    for code_artifact in row["code"]["artifacts"]:
        source = Path(code_artifact["artifact"]["path"])
        try:
            relative = source.relative_to(repository_root)
            destination = PurePosixPath("repo", *relative.parts)
        except ValueError:
            destination = PurePosixPath("external-code", code_artifact["name"])
        records.append(
            {
                "destination": str(destination),
                "artifact": code_artifact["artifact"],
            }
        )
    records.sort(key=lambda item: item["destination"])
    return input_path, model_paths, configuration_path, frozen_repo, records


def _verify_snapshot(root: Path, row: dict[str, Any]) -> tuple[Path, dict[str, str], Path, Path]:
    input_path, model_paths, configuration_path, frozen_repo, records = _snapshot_layout(
        row,
        root,
    )
    marker_path = root / "snapshot.json"
    expected_marker = {
        "schema_version": 1,
        "execution_contract": BATCH_EXECUTION_CONTRACT,
        "cache_key": row["cache_key"],
        "artifacts": [
            {
                "destination": record["destination"],
                "sha256": record["artifact"]["sha256"],
                "size_bytes": record["artifact"]["size_bytes"],
            }
            for record in records
        ],
    }
    if (
        root.is_symlink()
        or not root.is_dir()
        or not marker_path.is_file()
        or load_json(marker_path) != expected_marker
    ):
        raise BatchValidationError(f"immutable artifact snapshot is invalid: {root}")
    for record in records:
        destination = root.joinpath(*PurePosixPath(record["destination"]).parts)
        if destination.is_symlink() or not destination.is_file():
            raise BatchValidationError(
                f"immutable artifact snapshot is unsafe: {destination}"
            )
        observed = _artifact(destination)
        expected = record["artifact"]
        if (
            observed["sha256"] != expected["sha256"]
            or observed["size_bytes"] != expected["size_bytes"]
        ):
            raise BatchValidationError(
                f"immutable artifact snapshot changed: {destination}"
            )
    return (
        input_path,
        {name: str(path) for name, path in model_paths.items()},
        configuration_path,
        frozen_repo,
    )


def _stage_row_artifacts(
    *,
    row: dict[str, Any],
    run_dir: Path,
    attempt_id: str,
) -> tuple[Path, dict[str, str], Path, Path]:
    root = run_dir / "frozen"
    if root.exists() or root.is_symlink():
        return _verify_snapshot(root, row)

    temporary = run_dir / "tmp" / f"frozen-{attempt_id}"
    temporary.mkdir(parents=True)
    try:
        _input_path, _model_paths, _configuration_path, _frozen_repo, records = (
            _snapshot_layout(row, temporary)
        )
        for record in records:
            destination = temporary.joinpath(
                *PurePosixPath(record["destination"]).parts
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(record["artifact"]["path"], destination)
            observed = _artifact(destination)
            expected = record["artifact"]
            if (
                observed["sha256"] != expected["sha256"]
                or observed["size_bytes"] != expected["size_bytes"]
            ):
                raise BatchValidationError(
                    "source changed while staging immutable artifact: "
                    f"{record['artifact']['path']}"
                )
            destination.chmod(0o400)
        marker = {
            "schema_version": 1,
            "execution_contract": BATCH_EXECUTION_CONTRACT,
            "cache_key": row["cache_key"],
            "artifacts": [
                {
                    "destination": record["destination"],
                    "sha256": record["artifact"]["sha256"],
                    "size_bytes": record["artifact"]["size_bytes"],
                }
                for record in records
            ],
        }
        atomic_write_json(temporary / "snapshot.json", marker)
        os.replace(temporary, root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _verify_snapshot(root, row)


def _stage_environment(
    *,
    stage: dict[str, Any],
    stage_tokens: dict[str, str],
    model_paths: dict[str, str],
    run_dir: Path,
) -> dict[str, str]:
    environment = {
        "HOME": str(run_dir / "runtime-home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "OMP_NUM_THREADS": "1",
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(Path(stage_tokens["repo_root"]) / "src"),
    }
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_visible:
        environment["CUDA_VISIBLE_DEVICES"] = cuda_visible
    environment.update(
        {
            key: _expand(item, stage_tokens, model_paths)
            for key, item in stage["environment"].items()
        }
    )
    Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
    return environment


def _attempt_id() -> str:
    job = os.environ.get("SLURM_ARRAY_JOB_ID") or os.environ.get("SLURM_JOB_ID") or "local"
    task = os.environ.get("SLURM_ARRAY_TASK_ID", "0")
    restart = os.environ.get("SLURM_RESTART_COUNT", "0")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{job}-{task}-r{restart}-{stamp}-{os.getpid()}"


def _resource_environment() -> dict[str, Any]:
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    device: dict[str, Any] = {
        "kind": "gpu" if cuda_visible else "cpu",
        "cuda_visible_devices": cuda_visible,
    }
    if cuda_visible and shutil.which("nvidia-smi"):
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,memory.total",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        device["nvidia_smi_return_code"] = result.returncode
        device["nvidia_smi"] = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "hostname": socket.gethostname(),
        "device": device,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
        "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "slurm_restart_count": os.environ.get("SLURM_RESTART_COUNT"),
        "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
        "slurm_account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        "slurm_job_gpus": os.environ.get("SLURM_JOB_GPUS"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }


def _run_stage_command(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[int, bool]:
    interrupted = False
    child: subprocess.Popen[bytes] | None = None

    def handle_signal(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        if child is not None and child.poll() is None:
            child.terminate()

    previous_term = signal.signal(signal.SIGTERM, handle_signal)
    previous_int = signal.signal(signal.SIGINT, handle_signal)
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                shell=False,
            )
            return_code = child.wait()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
    return return_code, interrupted


@contextmanager
def _interruptible_attempt() -> Iterator[Callable[[], None]]:
    active = True

    def handle_signal(signum: int, _frame: Any) -> None:
        if active:
            raise BatchInterrupted(f"attempt interrupted by signal {signum}")

    def disarm() -> None:
        nonlocal active
        active = False

    previous_term = signal.signal(signal.SIGTERM, handle_signal)
    previous_int = signal.signal(signal.SIGINT, handle_signal)
    try:
        yield disarm
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def _write_row_record(
    *,
    index_root: Path,
    manifest: dict[str, Any],
    manifest_sha256: str,
    row: dict[str, Any],
    status: str,
    run_dir: Path,
    selected_dir: Path | None,
    attempt: dict[str, Any],
) -> None:
    batch_index_root = index_root / manifest["batch_id"]
    attempt_id = attempt["attempt_id"]
    attempt_dir = run_dir / "attempts" / attempt_id
    log_records = [
        _output_record(attempt_dir, path.name)
        for path in sorted(attempt_dir.glob("*.log"))
        if path.is_file() and not path.is_symlink()
    ]
    persistent_log_dir = batch_index_root / "attempt-logs" / row["row_id"] / attempt_id
    if persistent_log_dir.exists() or persistent_log_dir.is_symlink():
        if persistent_log_dir.is_symlink() or not persistent_log_dir.is_dir():
            raise BatchValidationError(
                f"persistent attempt log directory is unsafe: {persistent_log_dir}"
            )
        if log_records:
            _verify_output_records(
                persistent_log_dir,
                log_records,
                label="persistent attempt logs",
            )
        elif any(persistent_log_dir.iterdir()):
            raise BatchValidationError(
                f"persistent attempt log directory is not empty: {persistent_log_dir}"
            )
    else:
        persistent_log_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_logs = persistent_log_dir.parent / f".{attempt_id}.tmp-{os.getpid()}"
        temporary_logs.mkdir()
        try:
            for log_record in log_records:
                shutil.copy2(
                    attempt_dir / log_record["path"],
                    temporary_logs / log_record["path"],
                )
            if log_records:
                _verify_output_records(
                    temporary_logs,
                    log_records,
                    label="persistent attempt logs",
                )
            os.replace(temporary_logs, persistent_log_dir)
        except BaseException:
            shutil.rmtree(temporary_logs, ignore_errors=True)
            raise
    record = {
        "schema_version": 1,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "row_id": row["row_id"],
        "authorization_id": row["authorization_id"],
        "cache_key": row["cache_key"],
        "status": status,
        "run_dir": str(run_dir),
        "selected_dir": str(selected_dir) if selected_dir is not None else None,
        "attempt": attempt,
        "logs": log_records,
        "updated_at": _now(),
    }
    attempt_record_path = (
        batch_index_root / "attempts" / row["row_id"] / f"{attempt_id}.json"
    )
    if attempt_record_path.exists() or attempt_record_path.is_symlink():
        if (
            attempt_record_path.is_symlink()
            or not attempt_record_path.is_file()
            or load_json(attempt_record_path) != record
        ):
            raise BatchValidationError(
                f"persistent attempt record already exists with different content: "
                f"{attempt_record_path}"
            )
    else:
        atomic_write_json(attempt_record_path, record)
    atomic_write_json(batch_index_root / "rows" / f"{row['row_id']}.json", record)


def _verify_complete(
    run_dir: Path,
    *,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    path = run_dir / "complete.json"
    if not path.exists():
        return None
    value = load_json(path)
    expected = {
        "schema_version": 1,
        "contract_version": BATCH_COMPLETE_CONTRACT,
        "cache_key": row["cache_key"],
        "cache_payload": _cache_payload(row),
    }
    if not isinstance(value, dict) or any(value.get(key) != item for key, item in expected.items()):
        raise BatchValidationError(f"cache completion provenance is invalid: {run_dir}")
    outputs = _verify_output_records(run_dir, value.get("outputs"), label="complete cache")
    if {item["path"] for item in outputs} != {
        f"stages/{stage['stage_id']}/{output}"
        for stage in row["stages"]
        for output in stage["outputs"]
    }:
        raise BatchValidationError("cache completion outputs do not match the manifest row")
    return value


def _verify_complete_without_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "complete.json"
    if not path.exists():
        return None
    value = load_json(path)
    cache_key = _sha256(run_dir.name, label="cache directory name")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("contract_version") != BATCH_COMPLETE_CONTRACT
        or value.get("cache_key") != cache_key
        or not isinstance(value.get("cache_payload"), dict)
        or _canonical_sha256(value["cache_payload"]) != cache_key
    ):
        raise BatchValidationError(f"cache completion provenance is invalid: {run_dir}")
    _verify_output_records(run_dir, value.get("outputs"), label="complete cache")
    return value


def _verify_persistent_archive_without_manifest(
    destination: Path,
    *,
    run_dir: Path,
    complete: dict[str, Any],
) -> None:
    provenance_path = destination / "selection.json"
    if destination.is_symlink() or not destination.is_dir() or not provenance_path.is_file():
        raise BatchValidationError(f"persistent archive is unsafe: {destination}")
    observed = load_json(provenance_path)
    if (
        not isinstance(observed, dict)
        or observed.get("schema_version") != 1
        or observed.get("contract_version") != BATCH_SELECTION_CONTRACT
        or observed.get("cache_key") != complete["cache_key"]
        or observed.get("source_complete_sha256") != sha256_file(run_dir / "complete.json")
    ):
        raise BatchValidationError(f"persistent archive provenance is invalid: {destination}")
    records = _verify_output_records(
        destination,
        observed.get("outputs"),
        label="persistent archive",
    )
    if sorted(records, key=lambda item: item["path"]) != sorted(
        complete["outputs"],
        key=lambda item: item["path"],
    ):
        raise BatchValidationError(
            f"persistent archive outputs do not match the cache: {destination}"
        )
    selected_outputs = observed.get("selected_outputs")
    if (
        not isinstance(selected_outputs, list)
        or not selected_outputs
        or any(not isinstance(item, str) for item in selected_outputs)
        or not set(selected_outputs).issubset({record["path"] for record in records})
    ):
        raise BatchValidationError(
            f"persistent archive selected outputs are invalid: {destination}"
        )


def _has_verified_persistent_archive(
    *,
    selected_root: Path,
    run_dir: Path,
    complete: dict[str, Any],
) -> bool:
    cache_key = complete["cache_key"]
    for provenance_path in selected_root.glob(f"*/*/{cache_key}/selection.json"):
        try:
            _verify_persistent_archive_without_manifest(
                provenance_path.parent,
                run_dir=run_dir,
                complete=complete,
            )
        except (BatchValidationError, OSError, json.JSONDecodeError):
            continue
        return True
    return False


def _has_persistent_attempt(
    *,
    index_root: Path,
    cache_key: str,
    attempt: dict[str, Any],
) -> bool:
    attempt_id = attempt.get("attempt_id")
    if not isinstance(attempt_id, str):
        return False
    for record_path in index_root.glob(f"*/attempts/*/{attempt_id}.json"):
        try:
            record = load_json(record_path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(record, dict)
            and record.get("cache_key") == cache_key
            and record.get("attempt") == attempt
        ):
            logs = record.get("logs")
            if not isinstance(logs, list):
                continue
            if not logs:
                return True
            persistent_log_dir = (
                record_path.parents[2]
                / "attempt-logs"
                / record_path.parent.name
                / attempt_id
            )
            try:
                _verify_output_records(
                    persistent_log_dir,
                    logs,
                    label="persistent attempt logs",
                )
            except (BatchValidationError, OSError, json.JSONDecodeError):
                continue
            return True
    return False


def _sync_selected(
    *,
    selected_root: Path,
    manifest: dict[str, Any],
    manifest_sha256: str,
    row: dict[str, Any],
    run_dir: Path,
    complete: dict[str, Any],
) -> Path:
    destination = (
        selected_root / manifest["batch_id"] / row["row_id"] / row["cache_key"]
    ).resolve()
    provenance_path = destination / "selection.json"
    records = sorted(complete["outputs"], key=lambda record: record["path"])
    expected_provenance = {
        "schema_version": 1,
        "contract_version": BATCH_SELECTION_CONTRACT,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "row_id": row["row_id"],
        "authorization_id": row["authorization_id"],
        "cache_key": row["cache_key"],
        "source_complete_sha256": sha256_file(run_dir / "complete.json"),
        "selected_outputs": sorted(f"stages/{relative}" for relative in row["selected_outputs"]),
        "outputs": records,
    }
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir() or not provenance_path.is_file():
            raise BatchValidationError(f"selected destination is unsafe: {destination}")
        observed = load_json(provenance_path)
        if observed != expected_provenance:
            raise BatchValidationError(f"selected provenance does not match: {destination}")
        _verify_output_records(destination, records, label="selected result")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp-{os.getpid()}"
    if temporary.exists():
        raise BatchValidationError(f"temporary selected destination already exists: {temporary}")
    temporary.mkdir()
    try:
        for record in records:
            relative = record["path"]
            source = run_dir.joinpath(*PurePosixPath(relative).parts)
            target = temporary.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        atomic_write_json(temporary / "selection.json", expected_provenance)
        _verify_output_records(temporary, records, label="selected result")
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def _verify_selected_copy(
    destination: Path,
    *,
    manifest: dict[str, Any],
    manifest_sha256: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    provenance_path = destination / "selection.json"
    if destination.is_symlink() or not destination.is_dir() or not provenance_path.is_file():
        raise BatchValidationError(f"selected destination is unsafe: {destination}")
    observed = load_json(provenance_path)
    expected = {
        "schema_version": 1,
        "contract_version": BATCH_SELECTION_CONTRACT,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "row_id": row["row_id"],
        "authorization_id": row["authorization_id"],
        "cache_key": row["cache_key"],
        "selected_outputs": sorted(f"stages/{relative}" for relative in row["selected_outputs"]),
    }
    if not isinstance(observed, dict) or any(
        observed.get(key) != value for key, value in expected.items()
    ):
        raise BatchValidationError(f"selected provenance does not match: {destination}")
    _sha256(
        observed.get("source_complete_sha256"),
        label="selected source_complete_sha256",
    )
    records = _verify_output_records(
        destination,
        observed.get("outputs"),
        label="selected result",
    )
    if {record["path"] for record in records} != {
        f"stages/{stage['stage_id']}/{output}"
        for stage in row["stages"]
        for output in stage["outputs"]
    }:
        raise BatchValidationError("persisted outputs do not match the manifest row")
    return observed


def run_batch_row(
    *,
    manifest_path: Path,
    row_index: int,
    cache_root: Path,
    selected_root: Path,
    index_root: Path,
    repo_root: Path,
    python_path: Path,
    allow_local: bool = False,
) -> str:
    slurm_step_id = os.environ.get("SLURM_STEP_ID")
    if not allow_local and (
        not os.environ.get("SLURM_JOB_ID")
        or not slurm_step_id
        or slurm_step_id in {"batch", "extern"}
    ):
        raise BatchValidationError("run-row requires an active Slurm compute step")
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = load_batch_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    if isinstance(row_index, bool) or not isinstance(row_index, int):
        raise BatchValidationError("row_index must be an integer")
    if row_index < 0:
        raise BatchValidationError("row_index must be non-negative")
    try:
        row = manifest["rows"][row_index]
    except IndexError as exc:
        raise BatchValidationError(f"row_index is outside the manifest: {row_index}") from exc
    if row.get("execution_contract") != BATCH_EXECUTION_CONTRACT:
        raise BatchValidationError(
            "manifest uses the legacy mutable execution contract; freeze a new manifest"
        )

    input_path = _verify_artifact(row["input"], label=f"row {row['row_id']!r} input")
    configuration_path = _verify_artifact(
        row["configuration"],
        label=f"row {row['row_id']!r} configuration",
    )
    for model in row["models"]:
        _verify_artifact(
            model["artifact"],
            label=f"row {row['row_id']!r} model {model['name']!r}",
        )
    for code_artifact in row["code"]["artifacts"]:
        _verify_artifact(
            code_artifact["artifact"],
            label=f"row {row['row_id']!r} code artifact {code_artifact['name']!r}",
        )
    expected_python = _verify_artifact(
        row["python"],
        label=f"row {row['row_id']!r} Python runtime",
    )
    repo_root = repo_root.expanduser().resolve(strict=True)
    python_path = _absolute_launcher(python_path, label="python_path")
    if not repo_root.is_dir() or not python_path.is_file() or not os.access(python_path, os.X_OK):
        raise BatchValidationError("repo_root or python_path is unavailable")
    if repo_root != Path(row["repository_root"]):
        raise BatchValidationError("repo_root does not match the frozen manifest row")
    if (
        str(python_path) != row["python"]["path"]
        or python_path.resolve(strict=True) != expected_python
        or str(expected_python) != row["python"]["resolved_path"]
        or python_path.stat().st_size != row["python"]["size_bytes"]
        or sha256_file(python_path) != row["python"]["sha256"]
        or _python_environment_sha256(python_path)
        != row["python"]["environment_sha256"]
    ):
        raise BatchValidationError("python_path does not match the frozen manifest row")

    cache_root = cache_root.expanduser().resolve()
    selected_root = selected_root.expanduser().resolve()
    index_root = index_root.expanduser().resolve()
    for root in (cache_root, selected_root, index_root):
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise BatchValidationError(f"batch root must not be a symlink: {root}")
    run_dir = cache_root / row["cache_key"]
    retention_lock_path = cache_root / ".retention.lock"
    with retention_lock_path.open("a+", encoding="utf-8") as retention_lock:
        fcntl.flock(retention_lock.fileno(), fcntl.LOCK_EX)
        if (
            not run_dir.exists()
            and _directory_size(cache_root) >= manifest["retention"]["max_cache_bytes"]
        ):
            raise BatchValidationError(
                "cache is already at or above its retention budget; finalize retention "
                "before admitting new work"
            )
        run_dir.mkdir(parents=True, exist_ok=True)
        if run_dir.is_symlink():
            raise BatchValidationError(f"cache directory must not be a symlink: {run_dir}")
        cache_lock = (run_dir / ".lock").open("a+", encoding="utf-8")
        try:
            fcntl.flock(cache_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            cache_lock.close()
            raise BatchValidationError(
                f"cache key is already running: {row['cache_key']}"
            ) from exc

    attempt_id = _attempt_id()
    attempt_dir = run_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True)
    attempt: dict[str, Any] = {
        "schema_version": 1,
        "attempt_id": attempt_id,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "row_id": row["row_id"],
        "cache_key": row["cache_key"],
        "started_at": _now(),
        "status": "running",
        "resource_environment": _resource_environment(),
        "stages": [],
    }
    attempt_path = attempt_dir / "attempt.json"
    atomic_write_json(attempt_path, attempt)
    selected_dir: Path | None = None
    started = time.monotonic()
    with (
        _interruptible_attempt() as disarm_signals,
        cache_lock,
    ):
        try:
            complete = _verify_complete(
                run_dir,
                row=row,
            )
            if complete is not None:
                selected_dir = _sync_selected(
                    selected_root=selected_root,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    row=row,
                    run_dir=run_dir,
                    complete=complete,
                )
                attempt["status"] = "cached"
                return_status = "cached"
            else:
                (
                    input_path,
                    model_paths,
                    configuration_path,
                    frozen_repo,
                ) = _stage_row_artifacts(
                    row=row,
                    run_dir=run_dir,
                    attempt_id=attempt_id,
                )
                tokens = {
                    "input": str(input_path),
                    "configuration": str(configuration_path),
                    "run_dir": str(run_dir),
                    "cache_key": row["cache_key"],
                    "row_id": row["row_id"],
                    "repo_root": str(frozen_repo),
                    "python": str(python_path),
                }
                completed_outputs: list[dict[str, Any]] = []
                for stage in row["stages"]:
                    existing = _stage_complete(run_dir, stage)
                    if existing is not None:
                        attempt["stages"].append(
                            {"stage_id": stage["stage_id"], "status": "cached"}
                        )
                        for output in existing["outputs"]:
                            completed_outputs.append(
                                {
                                    **output,
                                    "path": f"stages/{stage['stage_id']}/{output['path']}",
                                }
                            )
                        continue

                    stage_started = time.monotonic()
                    temporary = run_dir / "tmp" / f"{stage['stage_id']}-{attempt_id}"
                    temporary.mkdir(parents=True)
                    try:
                        checkpoint_dir = run_dir / "checkpoints" / stage["stage_id"]
                        checkpoint_dir.mkdir(parents=True, exist_ok=True)
                        stage_tokens = {
                            **tokens,
                            "stage_dir": str(temporary),
                            "checkpoint_dir": str(checkpoint_dir),
                        }
                        command = [
                            _expand(item, stage_tokens, model_paths) for item in stage["command"]
                        ]
                        environment = _stage_environment(
                            stage=stage,
                            stage_tokens=stage_tokens,
                            model_paths=model_paths,
                            run_dir=run_dir,
                        )
                        stdout_path = attempt_dir / f"{stage['stage_id']}.stdout.log"
                        stderr_path = attempt_dir / f"{stage['stage_id']}.stderr.log"
                        return_code, interrupted = _run_stage_command(
                            command,
                            cwd=temporary,
                            environment=environment,
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                        )
                        stage_record = {
                            "stage_id": stage["stage_id"],
                            "command": command,
                            "wall_seconds": time.monotonic() - stage_started,
                            "return_code": return_code,
                            "max_rss_kb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                        }
                        if interrupted or return_code == 75:
                            stage_record["status"] = "interrupted"
                            attempt["stages"].append(stage_record)
                            raise BatchInterrupted(f"stage interrupted: {stage['stage_id']}")
                        if return_code != 0:
                            stage_record["status"] = "failed"
                            attempt["stages"].append(stage_record)
                            raise RuntimeError(
                                f"stage {stage['stage_id']!r} exited with {return_code}; "
                                f"see {stderr_path}"
                            )
                        _verify_snapshot(run_dir / "frozen", row)
                        output_records = [
                            _output_record(temporary, output) for output in stage["outputs"]
                        ]
                        stage_complete = {
                            "schema_version": 1,
                            "stage_id": stage["stage_id"],
                            "completed_at": _now(),
                            "declared_outputs": stage["outputs"],
                            "outputs": output_records,
                        }
                        atomic_write_json(temporary / "stage_complete.json", stage_complete)
                        final_stage_dir = run_dir / "stages" / stage["stage_id"]
                        final_stage_dir.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(temporary, final_stage_dir)
                    except BaseException:
                        shutil.rmtree(temporary, ignore_errors=True)
                        raise
                    stage_record["status"] = "completed"
                    stage_record["outputs"] = output_records
                    attempt["stages"].append(stage_record)
                    for output in output_records:
                        completed_outputs.append(
                            {
                                **output,
                                "path": f"stages/{stage['stage_id']}/{output['path']}",
                            }
                        )

                complete = {
                    "schema_version": 1,
                    "contract_version": BATCH_COMPLETE_CONTRACT,
                    "cache_key": row["cache_key"],
                    "cache_payload": _cache_payload(row),
                    "completed_at": _now(),
                    "outputs": completed_outputs,
                }
                atomic_write_json(run_dir / "complete.json", complete)
                complete = _verify_complete(
                    run_dir,
                    row=row,
                )
                if complete is None:
                    raise BatchValidationError("cache completion disappeared before publication")
                selected_dir = _sync_selected(
                    selected_root=selected_root,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    row=row,
                    run_dir=run_dir,
                    complete=complete,
                )
                attempt["status"] = "completed"
                return_status = "completed"
        except BatchInterrupted:
            attempt["status"] = "interrupted"
            raise
        except BaseException:
            if attempt["status"] == "running":
                attempt["status"] = "failed"
            raise
        finally:
            disarm_signals()
            attempt["ended_at"] = _now()
            attempt["wall_seconds"] = time.monotonic() - started
            atomic_write_json(attempt_path, attempt)
            _write_row_record(
                index_root=index_root,
                manifest=manifest,
                manifest_sha256=manifest_sha256,
                row=row,
                status=attempt["status"],
                run_dir=run_dir,
                selected_dir=selected_dir,
                attempt=attempt,
            )
    return return_status


def summarize_batch(
    *,
    manifest_path: Path,
    cache_root: Path,
    selected_root: Path,
    index_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = load_batch_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    cache_root = cache_root.expanduser().resolve()
    selected_root = selected_root.expanduser().resolve()
    index_root = index_root.expanduser().resolve()
    rows: list[dict[str, Any]] = []
    attempt_statuses: dict[str, int] = {}
    stage_wall_seconds = 0.0
    peak_max_rss_kb = 0
    cache_bytes = _directory_size(cache_root) if cache_root.is_dir() else 0
    for row in manifest["rows"]:
        run_dir = cache_root / row["cache_key"]
        selected_dir = selected_root / manifest["batch_id"] / row["row_id"] / row["cache_key"]
        complete = None
        status = "missing"
        error = None
        if run_dir.is_dir() and not run_dir.is_symlink():
            try:
                complete = _verify_complete(
                    run_dir,
                    row=row,
                )
                status = "completed" if complete is not None else "incomplete"
            except BatchValidationError as exc:
                status = "corrupt"
                error = str(exc)
        if status == "completed":
            if not (selected_dir / "selection.json").is_file():
                status = "completed_unarchived"
            else:
                try:
                    _verify_selected_copy(
                        selected_dir,
                        manifest=manifest,
                        manifest_sha256=manifest_sha256,
                        row=row,
                    )
                except BatchValidationError as exc:
                    status = "corrupt_selected"
                    error = str(exc)
        if status == "missing" and (selected_dir / "selection.json").is_file():
            try:
                _verify_selected_copy(
                    selected_dir,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    row=row,
                )
                status = "pruned_selected"
            except BatchValidationError as exc:
                status = "corrupt_selected"
                error = str(exc)
        attempts_by_id: dict[str, dict[str, Any]] = {}
        persistent_attempts_root = index_root / manifest["batch_id"] / "attempts" / row["row_id"]
        if persistent_attempts_root.is_dir():
            for record_path in sorted(persistent_attempts_root.glob("*.json")):
                try:
                    record = load_json(record_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    not isinstance(record, dict)
                    or record.get("batch_id") != manifest["batch_id"]
                    or record.get("manifest_sha256") != manifest_sha256
                    or record.get("row_id") != row["row_id"]
                    or record.get("cache_key") != row["cache_key"]
                ):
                    continue
                attempt = record.get("attempt")
                attempt_id = attempt.get("attempt_id") if isinstance(attempt, dict) else None
                if isinstance(attempt_id, str):
                    attempts_by_id[attempt_id] = attempt
        attempts_root = run_dir / "attempts"
        if attempts_root.is_dir():
            for attempt_path in sorted(attempts_root.glob("*/attempt.json")):
                try:
                    attempt = load_json(attempt_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(attempt, dict):
                    continue
                if (
                    attempt.get("batch_id") != manifest["batch_id"]
                    or attempt.get("manifest_sha256") != manifest_sha256
                    or attempt.get("row_id") != row["row_id"]
                    or attempt.get("cache_key") != row["cache_key"]
                ):
                    continue
                attempt_id = attempt.get("attempt_id")
                if not isinstance(attempt_id, str):
                    continue
                attempts_by_id.setdefault(attempt_id, attempt)
        attempts = list(attempts_by_id.values())
        for attempt in attempts:
            attempt_status = str(attempt.get("status", "unknown"))
            attempt_statuses[attempt_status] = attempt_statuses.get(attempt_status, 0) + 1
            for stage in attempt.get("stages", []):
                if isinstance(stage, dict):
                    wall = stage.get("wall_seconds")
                    rss = stage.get("max_rss_kb")
                    if isinstance(wall, int | float) and not isinstance(wall, bool):
                        stage_wall_seconds += float(wall)
                    if isinstance(rss, int) and not isinstance(rss, bool):
                        peak_max_rss_kb = max(peak_max_rss_kb, rss)
        rows.append(
            {
                "row_id": row["row_id"],
                "authorization_id": row["authorization_id"],
                "cache_key": row["cache_key"],
                "status": status,
                "error": error,
                "attempt_count": len(attempts),
                "selected_dir": str(selected_dir) if selected_dir.is_dir() else None,
            }
        )

    terminal_attempts = sum(
        count
        for status, count in attempt_statuses.items()
        if status in {"completed", "failed", "interrupted"}
    )
    unsuccessful = sum(attempt_statuses.get(status, 0) for status in ("failed", "interrupted"))
    cache_hits = attempt_statuses.get("cached", 0)
    all_attempts = sum(attempt_statuses.values())
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    index = {
        "schema_version": 1,
        "contract_version": BATCH_INDEX_CONTRACT,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "generated_at": _now(),
        "rows": rows,
        "status_counts": status_counts,
    }
    resources = {
        "schema_version": 1,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest_sha256,
        "generated_at": _now(),
        "attempt_status_counts": attempt_statuses,
        "failure_rate": unsuccessful / terminal_attempts if terminal_attempts else None,
        "failure_rate_numerator": unsuccessful,
        "failure_rate_denominator": terminal_attempts,
        "cache_hit_rate": cache_hits / all_attempts if all_attempts else None,
        "cache_hit_numerator": cache_hits,
        "cache_hit_denominator": all_attempts,
        "stage_wall_seconds_total": stage_wall_seconds,
        "peak_max_rss_kb": peak_max_rss_kb,
        "cache_bytes": cache_bytes,
        "retention_max_cache_bytes": manifest["retention"]["max_cache_bytes"],
    }
    output_dir = index_root / manifest["batch_id"]
    atomic_write_json(output_dir / "experiment_index.json", index)
    atomic_write_json(output_dir / "resource_failure_summary.json", resources)
    return index, resources


def prune_batch_cache(
    *,
    manifest_path: Path,
    cache_root: Path,
    selected_root: Path,
    index_root: Path,
    apply: bool,
) -> dict[str, Any]:
    cache_root = cache_root.expanduser().resolve()
    if not apply:
        return _prune_batch_cache_locked(
            manifest_path=manifest_path,
            cache_root=cache_root,
            selected_root=selected_root,
            index_root=index_root,
            apply=False,
        )
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / ".retention.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _prune_batch_cache_locked(
            manifest_path=manifest_path,
            cache_root=cache_root,
            selected_root=selected_root,
            index_root=index_root,
            apply=True,
        )


def _prune_batch_cache_locked(
    *,
    manifest_path: Path,
    cache_root: Path,
    selected_root: Path,
    index_root: Path,
    apply: bool,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = load_batch_manifest(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    cache_root = cache_root.expanduser().resolve()
    selected_root = selected_root.expanduser().resolve()
    index_root = index_root.expanduser().resolve()
    retention = manifest["retention"]
    rows_by_cache_key = {row["cache_key"]: row for row in manifest["rows"]}
    entries: list[dict[str, Any]] = []
    if not cache_root.is_dir():
        cache_directories: list[Path] = []
    else:
        cache_directories = sorted(
            path for path in cache_root.iterdir() if path.is_dir() and not path.is_symlink()
        )
    for run_dir in cache_directories:
        cache_key = run_dir.name
        row = rows_by_cache_key.get(cache_key)
        complete_path = run_dir / "complete.json"
        completed = False
        selected_verified = False
        active = False
        if apply:
            cache_lock = (run_dir / ".lock").open("a+", encoding="utf-8")
            try:
                fcntl.flock(cache_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                active = True
            finally:
                cache_lock.close()
        try:
            if row is not None:
                verified_complete = _verify_complete(run_dir, row=row)
            else:
                verified_complete = _verify_complete_without_manifest(run_dir)
            completed = verified_complete is not None
            if completed and row is not None:
                current_archive = (
                    selected_root / manifest["batch_id"] / row["row_id"] / row["cache_key"]
                )
                if apply or (current_archive / "selection.json").is_file():
                    _sync_selected(
                        selected_root=selected_root,
                        manifest=manifest,
                        manifest_sha256=manifest_sha256,
                        row=row,
                        run_dir=run_dir,
                        complete=verified_complete,
                    )
            if completed:
                selected_verified = _has_verified_persistent_archive(
                    selected_root=selected_root,
                    run_dir=run_dir,
                    complete=verified_complete,
                )
        except (BatchValidationError, OSError, json.JSONDecodeError) as exc:
            if row is not None:
                raise BatchValidationError(
                    f"current manifest cache cannot be safely finalized: {cache_key}"
                ) from exc
            completed = False
            selected_verified = False
        if row is None and SHA256_PATTERN.fullmatch(cache_key) is None:
            completed = False
            selected_verified = False
        entries.append(
            {
                "row_id": row["row_id"] if row is not None else None,
                "cache_key": cache_key,
                "path": run_dir,
                "size_bytes": _directory_size(run_dir),
                "completed": completed,
                "selected": selected_verified,
                "active": active,
                "incomplete_removable": False,
                "mtime": (
                    complete_path.stat().st_mtime
                    if complete_path.is_file()
                    else run_dir.stat().st_mtime
                ),
            }
        )

    removed_attempts: list[str] = []
    removed_attempt_bytes = 0
    max_failed = retention["max_failed_attempts_per_cache"]
    for entry in entries:
        if entry["active"]:
            continue
        attempt_paths: list[tuple[float, Path]] = []
        attempts_root = entry["path"] / "attempts"
        if not attempts_root.is_dir():
            continue
        attempt_directories = sorted(path for path in attempts_root.iterdir() if path.is_dir())
        all_terminal_and_persistent = bool(attempt_directories)
        for attempt_dir in attempt_directories:
            attempt_path = attempt_dir / "attempt.json"
            try:
                attempt = load_json(attempt_path)
            except (OSError, json.JSONDecodeError):
                all_terminal_and_persistent = False
                continue
            terminal_and_persistent = (
                isinstance(attempt, dict)
                and attempt.get("status") in {"failed", "interrupted"}
                and _has_persistent_attempt(
                    index_root=index_root,
                    cache_key=entry["cache_key"],
                    attempt=attempt,
                )
            )
            if terminal_and_persistent:
                attempt_paths.append((attempt_path.stat().st_mtime, attempt_dir))
            else:
                all_terminal_and_persistent = False
        entry["incomplete_removable"] = (
            not entry["completed"]
            and SHA256_PATTERN.fullmatch(entry["cache_key"]) is not None
            and all_terminal_and_persistent
        )
        attempt_paths.sort(reverse=True)
        for _mtime, attempt_dir in attempt_paths[max_failed:]:
            removed_attempts.append(str(attempt_dir))
            size_bytes = _directory_size(attempt_dir)
            removed_attempt_bytes += size_bytes
            entry["removed_attempt_bytes"] = entry.get("removed_attempt_bytes", 0) + size_bytes

    current_bytes = sum(entry["size_bytes"] for entry in entries)
    completed_removable = sorted(
        (
            entry
            for entry in entries
            if entry["completed"] and entry["selected"] and not entry["active"]
        ),
        key=lambda item: item["mtime"],
    )
    protected = retention["keep_recent_completed"]
    if protected:
        completed_removable = (
            completed_removable[:-protected] if len(completed_removable) > protected else []
        )
    incomplete_removable = [
        entry
        for entry in entries
        if entry["incomplete_removable"] and not entry["active"]
    ]
    removable = sorted(
        [*completed_removable, *incomplete_removable],
        key=lambda item: item["mtime"],
    )
    removed_caches: list[str] = []
    projected_bytes = current_bytes - removed_attempt_bytes
    for entry in removable:
        if projected_bytes <= retention["max_cache_bytes"]:
            break
        removed_caches.append(str(entry["path"]))
        projected_bytes -= entry["size_bytes"] - entry.get("removed_attempt_bytes", 0)
    report = {
        "schema_version": 1,
        "batch_id": manifest["batch_id"],
        "apply": apply,
        "cache_bytes_before": current_bytes,
        "cache_bytes_after": projected_bytes,
        "max_cache_bytes": retention["max_cache_bytes"],
        "removed_attempts": removed_attempts,
        "removed_caches": removed_caches,
        "protected_active_caches": [
            str(entry["path"]) for entry in entries if entry["active"]
        ],
        "within_budget": projected_bytes <= retention["max_cache_bytes"],
    }
    if apply and not report["within_budget"]:
        raise BatchValidationError(
            "cache exceeds its budget, but no safely selected completed cache can be removed"
        )
    if apply:
        removed_cache_paths = {Path(path) for path in removed_caches}
        for attempt_path in (Path(path) for path in removed_attempts):
            if not any(
                attempt_path == cache_path or attempt_path.is_relative_to(cache_path)
                for cache_path in removed_cache_paths
            ):
                shutil.rmtree(attempt_path)
        for cache_path in removed_cache_paths:
            shutil.rmtree(cache_path)
    return report
