from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .events import NoteEvent, read_jsonl
from .utils import atomic_write_json, sha256_file

REQUEST_CONTRACT = "amt-worker-request/v1"
RESULT_CONTRACT = "amt-worker-result/v1"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z", re.ASCII)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
NOTE_WORKERS = frozenset({"muscriptor", "game", "basic_pitch"})


class ContractValidationError(ValueError):
    """Raised when a worker request or result violates the shared contract."""


def _validate_identifier(value: str, *, label: str) -> str:
    if not isinstance(value, str) or RUN_ID_PATTERN.fullmatch(value) is None or ".." in value:
        raise ContractValidationError(f"{label} is missing or unsafe")
    return value


def _validate_project_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ContractValidationError("project_id is missing or unsafe")
    return value


def _validate_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(f"{label} must be a lowercase SHA-256")
    return value


def _safe_relative_path(value: str, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ContractValidationError(f"{label} must be a safe POSIX relative path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ContractValidationError(f"{label} contains an unsafe path component")
    return path


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    path: str
    sha256: str
    size_bytes: int

    def validate(self, *, relative: bool) -> None:
        if relative:
            _safe_relative_path(self.path, label="artifact path")
        elif not isinstance(self.path, str) or not self.path:
            raise ContractValidationError("artifact path must not be empty")
        _validate_sha256(self.sha256, label="artifact sha256")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ContractValidationError("artifact size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ContractValidationError("artifact size_bytes must be non-negative")

    @classmethod
    def from_dict(cls, value: Any, *, relative: bool) -> ArtifactRecord:
        if not isinstance(value, dict):
            raise ContractValidationError("artifact record must be an object")
        try:
            record = cls(
                path=value["path"],
                sha256=value["sha256"],
                size_bytes=value["size_bytes"],
            )
        except KeyError as exc:
            raise ContractValidationError(f"artifact record is missing {exc.args[0]}") from exc
        record.validate(relative=relative)
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class WorkerRequestV1:
    request_id: str
    run_id: str
    project_id: str
    worker: str
    created_at: str
    input: ArtifactRecord
    configuration: dict[str, Any]
    requested_outputs: tuple[str, ...]
    schema_version: int = 1
    contract_version: str = REQUEST_CONTRACT

    def validate(self) -> None:
        if self.schema_version != 1 or self.contract_version != REQUEST_CONTRACT:
            raise ContractValidationError("unsupported worker request contract")
        _validate_identifier(self.request_id, label="request_id")
        _validate_identifier(self.run_id, label="run_id")
        _validate_project_id(self.project_id)
        _validate_identifier(self.worker, label="worker")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ContractValidationError("created_at is required")
        self.input.validate(relative=False)
        if not isinstance(self.configuration, dict):
            raise ContractValidationError("configuration must be an object")
        if not self.requested_outputs:
            raise ContractValidationError("requested_outputs must not be empty")
        if len(set(self.requested_outputs)) != len(self.requested_outputs):
            raise ContractValidationError("requested_outputs contains duplicates")
        for output in self.requested_outputs:
            _safe_relative_path(output, label="requested output")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "worker": self.worker,
            "created_at": self.created_at,
            "input": self.input.to_dict(),
            "configuration": self.configuration,
            "requested_outputs": list(self.requested_outputs),
        }

    def write(self, path: Path) -> None:
        atomic_write_json(path, self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> WorkerRequestV1:
        if not isinstance(value, dict):
            raise ContractValidationError("worker request must be an object")
        try:
            requested_outputs = value["requested_outputs"]
            if not isinstance(requested_outputs, list):
                raise ContractValidationError("requested_outputs must be an array")
            request = cls(
                schema_version=value["schema_version"],
                contract_version=value["contract_version"],
                request_id=value["request_id"],
                run_id=value["run_id"],
                project_id=value["project_id"],
                worker=value["worker"],
                created_at=value["created_at"],
                input=ArtifactRecord.from_dict(value["input"], relative=False),
                configuration=value["configuration"],
                requested_outputs=tuple(requested_outputs),
            )
        except ContractValidationError:
            raise
        except (KeyError, TypeError) as exc:
            raise ContractValidationError(f"malformed worker request: {exc}") from exc
        request.validate()
        return request


@dataclass(slots=True)
class WorkerResultV1:
    run_dir: Path
    manifest: dict[str, Any]
    outputs: dict[str, ArtifactRecord] = field(init=False)

    def __post_init__(self) -> None:
        self.run_dir = self.run_dir.expanduser().resolve()
        if not self.run_dir.is_dir() or self.run_dir.is_symlink():
            raise ContractValidationError(f"run directory is missing or unsafe: {self.run_dir}")
        if not isinstance(self.manifest, dict):
            raise ContractValidationError("run manifest must be an object")
        if self.manifest.get("schema_version") != 1:
            raise ContractValidationError("unsupported result schema_version")
        contract = self.manifest.get("contract_version", RESULT_CONTRACT)
        if contract != RESULT_CONTRACT:
            raise ContractValidationError(f"unsupported result contract: {contract!r}")
        run_id = _validate_identifier(self.manifest.get("run_id"), label="run_id")
        if run_id != self.run_dir.name:
            raise ContractValidationError("manifest run_id does not match its directory")
        _validate_project_id(self.manifest.get("project_id"))
        _validate_identifier(self.manifest.get("worker"), label="worker")
        if self.manifest.get("status") != "succeeded":
            raise ContractValidationError("worker result is not succeeded")
        raw_outputs = self.manifest.get("outputs")
        if not isinstance(raw_outputs, list) or not raw_outputs:
            raise ContractValidationError("worker result outputs must not be empty")
        outputs: dict[str, ArtifactRecord] = {}
        for raw_output in raw_outputs:
            output = ArtifactRecord.from_dict(raw_output, relative=True)
            if output.path in outputs:
                raise ContractValidationError(f"duplicate output record: {output.path}")
            outputs[output.path] = output
        self.outputs = outputs

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]

    @property
    def project_id(self) -> str:
        return self.manifest["project_id"]

    @property
    def worker(self) -> str:
        return self.manifest["worker"]

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "run_manifest.json"

    def verify_outputs(self) -> None:
        run_root = self.run_dir.resolve(strict=True)
        for relative, record in self.outputs.items():
            parts = _safe_relative_path(relative, label="output path").parts
            cursor = self.run_dir
            for part in parts:
                cursor /= part
                if cursor.is_symlink():
                    raise ContractValidationError(f"output uses a symbolic link: {relative}")
            try:
                path = cursor.resolve(strict=True)
                path.relative_to(run_root)
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ContractValidationError(
                    f"output is missing or escapes run: {relative}"
                ) from exc
            if not path.is_file():
                raise ContractValidationError(f"output is not a file: {relative}")
            if path.stat().st_size != record.size_bytes:
                raise ContractValidationError(f"output size mismatch: {relative}")
            if sha256_file(path) != record.sha256:
                raise ContractValidationError(f"output SHA-256 mismatch: {relative}")

    def output_path(self, relative: str) -> Path:
        if relative not in self.outputs:
            raise ContractValidationError(f"result does not record output: {relative}")
        return self.run_dir.joinpath(*_safe_relative_path(relative, label="output path").parts)

    def read_note_events(self) -> list[NoteEvent]:
        if self.worker not in NOTE_WORKERS:
            raise ContractValidationError(f"worker {self.worker!r} does not emit note events")
        return read_jsonl(self.output_path("normalized/events.jsonl"))

    def read_rhythm_map(self) -> dict[str, Any]:
        if self.worker != "beat_this":
            raise ContractValidationError(f"worker {self.worker!r} does not emit a rhythm map")
        path = self.output_path("normalized/rhythm.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractValidationError(f"cannot read rhythm map: {exc}") from exc
        if not isinstance(value, dict):
            raise ContractValidationError("rhythm map must be an object")
        return value


def load_worker_request(path: Path) -> WorkerRequestV1:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"cannot read worker request: {exc}") from exc
    return WorkerRequestV1.from_dict(value)


def load_worker_result(run_dir: Path, *, verify_outputs: bool = True) -> WorkerResultV1:
    manifest_path = run_dir.expanduser() / "run_manifest.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"cannot read worker result: {exc}") from exc
    result = WorkerResultV1(run_dir=run_dir, manifest=value)
    if verify_outputs:
        result.verify_outputs()
    return result
