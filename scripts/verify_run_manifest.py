#!/usr/bin/env python3
"""Lightweight integrity check for an immutable worker run directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,198}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class ManifestValidationError(ValueError):
    """Raised when a run manifest or one of its recorded outputs is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(f"cannot read {label} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{label} root must be a JSON object")
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    return _load_json_object(path, label="manifest")


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _model_bundle_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["size_bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _safe_relative_output_path(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise ManifestValidationError("output path must be a non-empty string")
    if value.startswith("/") or "\\" in value:
        raise ManifestValidationError(f"output path is not a safe POSIX relative path: {value!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ManifestValidationError(f"output path contains a control character: {value!r}")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise ManifestValidationError(f"output path contains an unsafe component: {value!r}")
    if parts == ("run_manifest.json",):
        raise ManifestValidationError("run_manifest.json cannot record itself as an output")
    return parts


def _verify_output(
    run_dir: Path,
    run_root: Path,
    record: Any,
) -> tuple[str, int]:
    if not isinstance(record, dict):
        raise ManifestValidationError("each output record must be a JSON object")

    parts = _safe_relative_output_path(record.get("path"))
    relative_path = "/".join(parts)
    output_path = run_dir.joinpath(*parts)
    cursor = run_dir
    for part in parts:
        cursor /= part
        if cursor.is_symlink():
            raise ManifestValidationError(f"output path uses a symbolic link: {relative_path}")

    try:
        resolved_output = output_path.resolve(strict=True)
        resolved_output.relative_to(run_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ManifestValidationError(
            f"output is missing or escapes the run directory: {relative_path}"
        ) from exc
    if not resolved_output.is_file():
        raise ManifestValidationError(f"output is not a regular file: {relative_path}")

    expected_size = record.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise ManifestValidationError(f"output size_bytes must be an integer: {relative_path}")
    if expected_size < 0:
        raise ManifestValidationError(f"output size_bytes cannot be negative: {relative_path}")
    actual_size = resolved_output.stat().st_size
    if actual_size != expected_size:
        raise ManifestValidationError(
            f"output size mismatch for {relative_path}: {actual_size} != {expected_size}"
        )

    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
        raise ManifestValidationError(f"output has an invalid SHA-256: {relative_path}")
    actual_hash = sha256_file(resolved_output)
    if actual_hash != expected_hash.lower():
        raise ManifestValidationError(
            f"output SHA-256 mismatch for {relative_path}: {actual_hash} != {expected_hash.lower()}"
        )
    return relative_path, actual_size


def _verify_expected_input(
    manifest: dict[str, Any],
    expected_input: Path,
    *,
    allow_relocated: bool = False,
) -> None:
    try:
        resolved_input = expected_input.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ManifestValidationError(
            f"expected input is missing or unreadable: {expected_input}"
        ) from exc
    if not resolved_input.is_file():
        raise ManifestValidationError(f"expected input is not a regular file: {expected_input}")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise ManifestValidationError(
            "request-bound validation requires exactly one manifest input"
        )
    record = inputs[0]
    if not isinstance(record, dict):
        raise ManifestValidationError("manifest input record must be a JSON object")
    if not allow_relocated and record.get("path") != str(resolved_input):
        raise ManifestValidationError(
            f"manifest input path does not match the current request: "
            f"{record.get('path')!r} != {str(resolved_input)!r}"
        )
    actual_hash = sha256_file(resolved_input)
    if record.get("sha256") != actual_hash:
        raise ManifestValidationError(
            "manifest input SHA-256 does not match the current request: "
            f"{record.get('sha256')!r} != {actual_hash!r}"
        )
    recorded_size = record.get("size_bytes")
    if recorded_size is not None and recorded_size != resolved_input.stat().st_size:
        raise ManifestValidationError(
            "manifest input size does not match the current request: "
            f"{recorded_size!r} != {resolved_input.stat().st_size!r}"
        )


def _source_display_path(source: Path, repo_root: Path) -> str:
    resolved_source = source.expanduser().resolve(strict=True)
    try:
        return str(resolved_source.relative_to(repo_root))
    except ValueError:
        return str(resolved_source)


def _verify_expected_sources(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
    expected_sources: tuple[Path, ...],
) -> None:
    code = manifest.get("code")
    if not isinstance(code, dict):
        raise ManifestValidationError("manifest code provenance must be a JSON object")
    records = code.get("source_files")
    if not isinstance(records, list):
        raise ManifestValidationError("manifest code.source_files must be a list")

    by_path: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ManifestValidationError("manifest source record is malformed")
        by_path.setdefault(record["path"], []).append(record)

    for source in expected_sources:
        try:
            display_path = _source_display_path(source, repo_root)
            resolved_source = source.expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ManifestValidationError(
                f"expected source is missing or unreadable: {source}"
            ) from exc
        if not resolved_source.is_file():
            raise ManifestValidationError(
                f"expected source is not a regular file: {resolved_source}"
            )
        matches = by_path.get(display_path, [])
        if len(matches) != 1:
            raise ManifestValidationError(
                f"manifest must contain exactly one current source record for {display_path!r}"
            )
        actual_hash = sha256_file(resolved_source)
        if matches[0].get("sha256") != actual_hash:
            raise ManifestValidationError(
                f"manifest source SHA-256 is stale for {display_path}: "
                f"{matches[0].get('sha256')!r} != {actual_hash!r}"
            )


def _expected_separator_provenance(
    pins: dict[str, Any],
    preset_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    presets = pins.get("presets")
    package = pins.get("package")
    if not isinstance(presets, dict) or not isinstance(package, dict):
        raise ManifestValidationError("separator pins lack presets or package metadata")
    preset = presets.get(preset_name)
    if not isinstance(preset, dict):
        raise ManifestValidationError(f"separator pins do not define preset {preset_name!r}")
    expected_files = preset.get("expected_files")
    parameters = preset.get("parameters")
    if (
        not isinstance(expected_files, list)
        or not expected_files
        or not all(isinstance(record, dict) for record in expected_files)
        or not isinstance(parameters, dict)
    ):
        raise ManifestValidationError(f"separator pins contain an invalid preset: {preset_name!r}")
    expected_package = {
        "name": package.get("name"),
        "version": package.get("version"),
        "pypi_wheel_sha256": package.get("pypi_wheel_sha256"),
        "pypi_sdist_sha256": package.get("pypi_sdist_sha256"),
        "upstream_git_commit": package.get("upstream_git_commit"),
    }
    expected_provenance = {
        "preset": preset_name,
        "model_filename": preset.get("model_filename"),
        "friendly_name": preset.get("friendly_name"),
        "architecture": preset.get("architecture"),
        "preset_sha256": _canonical_json_sha256(preset),
        "bundle_sha256": _model_bundle_sha256(expected_files),
        "files": expected_files,
        "package": expected_package,
        "license": preset.get("license"),
    }
    return parameters, expected_provenance


def _verify_expected_pins(
    manifest: dict[str, Any],
    *,
    expected_worker: str,
    expected_preset: str | None,
    pins_path: Path,
) -> None:
    pins = _load_json_object(pins_path, label="pins")
    if pins.get("schema_version") != 1:
        raise ManifestValidationError("pins schema_version must be 1")

    if expected_worker == "separator":
        if expected_preset is None:
            raise ManifestValidationError("separator pins validation requires a preset")
        parameters, expected_provenance = _expected_separator_provenance(
            pins,
            expected_preset,
        )
        if manifest.get("configuration") != parameters:
            raise ManifestValidationError(
                "separator configuration does not match the current pinned preset"
            )
        if manifest.get("model_provenance") != expected_provenance:
            raise ManifestValidationError(
                "separator model provenance does not match the current pins"
            )
        return

    if expected_worker == "muscriptor":
        model = pins.get("model")
        package = pins.get("package")
        provenance = manifest.get("model_provenance")
        if (
            not isinstance(model, dict)
            or not isinstance(package, dict)
            or not isinstance(provenance, dict)
        ):
            raise ManifestValidationError("MuScriptor pins or provenance are malformed")
        expected_package = {
            "name": package.get("name"),
            "version": package.get("version"),
            "pypi_wheel_sha256": package.get("pypi_wheel_sha256"),
            "upstream_git_commit": package.get("upstream_git_commit"),
        }
        if manifest.get("model") != model.get("name"):
            raise ManifestValidationError("MuScriptor model does not match the current pins")
        for field in ("repository", "revision", "license"):
            if provenance.get(field) != model.get(field):
                raise ManifestValidationError(f"MuScriptor {field} does not match the current pins")
        if provenance.get("package") != expected_package:
            raise ManifestValidationError(
                "MuScriptor package provenance does not match the current pins"
            )
        return

    if expected_worker == "beat_this":
        package = pins.get("package")
        model = pins.get("model")
        decoding = pins.get("decoding")
        provenance = manifest.get("model_provenance")
        if not all(isinstance(value, dict) for value in (package, model, decoding, provenance)):
            raise ManifestValidationError("Beat This pins or provenance are malformed")
        if manifest.get("model") != model.get("name"):
            raise ManifestValidationError("Beat This model does not match the current pins")
        if manifest.get("configuration") != {
            "checkpoint": model.get("name"),
            "dbn": decoding.get("dbn"),
            "float16": decoding.get("float16"),
            "gpu_index": decoding.get("gpu_index"),
            "activations": decoding.get("activations"),
            "postprocessor": decoding.get("postprocessor"),
            "frame_rate_hz": decoding.get("frame_rate_hz"),
        }:
            raise ManifestValidationError("Beat This configuration does not match the current pins")
        if provenance.get("package") != package:
            raise ManifestValidationError(
                "Beat This package provenance does not match the current pins"
            )
        checkpoint = provenance.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise ManifestValidationError("Beat This checkpoint provenance is malformed")
        for field, expected_value in model.items():
            if checkpoint.get(field) != expected_value:
                raise ManifestValidationError(
                    f"Beat This checkpoint field {field!r} does not match the current pins"
                )
        return

    raise ManifestValidationError(
        f"request-bound pins validation is unsupported for worker {expected_worker!r}"
    )


def _verify_expected_model_provenance(
    manifest: dict[str, Any],
    provenance_path: Path,
) -> None:
    expected = _load_json_object(provenance_path, label="model provenance")
    if expected.get("schema_version") != 1:
        raise ManifestValidationError("model provenance schema_version must be 1")
    weight = expected.get("weight")
    config = expected.get("config")
    actual = manifest.get("model_provenance")
    if not isinstance(weight, dict) or not isinstance(config, dict) or not isinstance(actual, dict):
        raise ManifestValidationError("model provenance records are malformed")
    expected_fields = {
        "repository": expected.get("repository"),
        "revision": expected.get("revision"),
        "license": expected.get("license"),
        "weight_filename": weight.get("filename"),
        "weight_sha256": weight.get("sha256"),
        "weight_size_bytes": weight.get("size_bytes"),
        "config_sha256": config.get("sha256"),
    }
    for field, expected_value in expected_fields.items():
        if actual.get(field) != expected_value:
            raise ManifestValidationError(
                f"manifest model provenance field {field!r} does not match the current request"
            )


def _manifest_field(manifest: dict[str, Any], dotted_path: str) -> Any:
    if not dotted_path or any(not part for part in dotted_path.split(".")):
        raise ManifestValidationError(f"expected manifest field path is invalid: {dotted_path!r}")
    value: Any = manifest
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ManifestValidationError(f"expected manifest field is missing: {dotted_path}")
        value = value[part]
    return value


def validate_run_manifest(
    run_dir: Path,
    *,
    expected_worker: str,
    expected_preset: str | None = None,
    required_outputs: tuple[str, ...] = (),
    expected_input: Path | None = None,
    expected_pins: Path | None = None,
    expected_model_provenance: Path | None = None,
    repo_root: Path | None = None,
    expected_sources: tuple[Path, ...] = (),
    expected_fields: tuple[tuple[str, Any], ...] = (),
    allow_relocated_input: bool = False,
) -> dict[str, Any]:
    """Validate a succeeded run and return a small integrity summary."""

    if not expected_worker:
        raise ManifestValidationError("expected worker must not be empty")
    if expected_worker == "separator" and expected_preset is None:
        raise ManifestValidationError("separator validation requires an expected preset")
    if expected_sources and repo_root is None:
        raise ManifestValidationError("request-bound source validation requires a repository root")
    if allow_relocated_input and expected_input is None:
        raise ManifestValidationError("relocated input validation requires an expected input")

    expanded_run_dir = run_dir.expanduser()
    if not expanded_run_dir.is_dir() or expanded_run_dir.is_symlink():
        raise ManifestValidationError(f"run directory is missing or unsafe: {expanded_run_dir}")
    run_root = expanded_run_dir.resolve(strict=True)
    manifest_path = expanded_run_dir / "run_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ManifestValidationError(f"run manifest is missing or unsafe: {manifest_path}")
    manifest = _load_manifest(manifest_path)

    if manifest.get("schema_version") != 1:
        raise ManifestValidationError("manifest schema_version must be 1")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None or ".." in run_id:
        raise ManifestValidationError("manifest run_id is missing or unsafe")
    if run_id != expanded_run_dir.name:
        raise ManifestValidationError(f"manifest run_id does not match directory name: {run_id!r}")
    if manifest.get("status") != "succeeded":
        raise ManifestValidationError("manifest status is not succeeded")
    if manifest.get("worker") != expected_worker:
        raise ManifestValidationError(
            f"manifest worker does not match: {manifest.get('worker')!r} != {expected_worker!r}"
        )
    if expected_preset is not None and manifest.get("preset") != expected_preset:
        raise ManifestValidationError(
            f"manifest preset does not match: {manifest.get('preset')!r} != {expected_preset!r}"
        )

    if expected_input is not None:
        _verify_expected_input(
            manifest,
            expected_input,
            allow_relocated=allow_relocated_input,
        )
    if expected_pins is not None:
        _verify_expected_pins(
            manifest,
            expected_worker=expected_worker,
            expected_preset=expected_preset,
            pins_path=expected_pins,
        )
    if expected_model_provenance is not None:
        _verify_expected_model_provenance(manifest, expected_model_provenance)
    if expected_sources:
        assert repo_root is not None
        try:
            resolved_repo_root = repo_root.expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ManifestValidationError(
                f"repository root is missing or unreadable: {repo_root}"
            ) from exc
        _verify_expected_sources(
            manifest,
            repo_root=resolved_repo_root,
            expected_sources=expected_sources,
        )
    for field_path, expected_value in expected_fields:
        actual_value = _manifest_field(manifest, field_path)
        if actual_value != expected_value:
            raise ManifestValidationError(
                f"manifest field {field_path!r} does not match the current request: "
                f"{actual_value!r} != {expected_value!r}"
            )

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ManifestValidationError("manifest outputs must be a non-empty list")
    verified_outputs: dict[str, int] = {}
    for record in outputs:
        relative_path, size_bytes = _verify_output(expanded_run_dir, run_root, record)
        if relative_path in verified_outputs:
            raise ManifestValidationError(f"duplicate output record: {relative_path}")
        verified_outputs[relative_path] = size_bytes

    for required_output in required_outputs:
        parts = _safe_relative_output_path(required_output)
        relative_path = "/".join(parts)
        size_bytes = verified_outputs.get(relative_path)
        if size_bytes is None:
            raise ManifestValidationError(
                f"required output is absent from the manifest: {relative_path}"
            )
    return {
        "run_id": run_id,
        "worker": expected_worker,
        "preset": expected_preset,
        "output_count": len(verified_outputs),
        "request_bound": any(
            (
                expected_input is not None,
                expected_pins is not None,
                expected_model_provenance is not None,
                bool(expected_sources),
                bool(expected_fields),
            )
        ),
        "input_path_strict": expected_input is not None and not allow_relocated_input,
    }


def _parse_expected_field(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--expect-field must use DOTTED.PATH=JSON")
    path, raw_value = value.split("=", 1)
    try:
        expected = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"--expect-field value is not valid JSON: {exc}") from exc
    return path, expected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Validate a succeeded worker run without importing any model environment.")
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--preset")
    parser.add_argument(
        "--input",
        type=Path,
        help="Bind reuse to the current single input path and SHA-256.",
    )
    parser.add_argument(
        "--allow-relocated-input",
        action="store_true",
        help=(
            "Allow --input to have a different absolute path while still requiring "
            "its exact recorded SHA-256 and size; intended for cross-machine verification."
        ),
    )
    parser.add_argument(
        "--pins",
        type=Path,
        help="Bind model/configuration reuse to the current worker pins.",
    )
    parser.add_argument(
        "--model-provenance",
        type=Path,
        help="Bind MuScriptor reuse to the current weight provenance JSON.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root used to normalize --source records.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        default=[],
        help="Bind reuse to a current source file; may be repeated.",
    )
    parser.add_argument(
        "--expect-field",
        type=_parse_expected_field,
        action="append",
        default=[],
        metavar="DOTTED.PATH=JSON",
        help="Require an exact manifest field value; may be repeated.",
    )
    parser.add_argument(
        "--require-output",
        action="append",
        default=[],
        help="Require a non-empty recorded output path; may be repeated.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = validate_run_manifest(
            args.run_dir,
            expected_worker=args.worker,
            expected_preset=args.preset,
            required_outputs=tuple(args.require_output),
            expected_input=args.input,
            expected_pins=args.pins,
            expected_model_provenance=args.model_provenance,
            repo_root=args.repo_root,
            expected_sources=tuple(args.source),
            expected_fields=tuple(args.expect_field),
            allow_relocated_input=args.allow_relocated_input,
        )
    except ManifestValidationError as exc:
        print(f"invalid run: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
