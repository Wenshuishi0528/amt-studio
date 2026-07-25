#!/usr/bin/env python3
"""Validate human reference notes and write an immutable reference seal."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.benchmark import canonical_json_sha256
from amt_core.evaluation import (
    EvaluationError,
    read_reference_jsonl,
    summarize_correction_session,
)
from amt_core.utils import atomic_write_json, sha256_file


class ReferenceSealError(RuntimeError):
    """Raised when human annotations cannot be sealed."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReferenceSealError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReferenceSealError(f"{label} must be a JSON object")
    return value


def _relative_file(pack_dir: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ReferenceSealError(f"{label} is not a safe relative path")
    relative = Path(value)
    if ".." in relative.parts:
        raise ReferenceSealError(f"{label} is not a safe relative path")
    path = (pack_dir / relative).resolve(strict=True)
    try:
        path.relative_to(pack_dir.resolve(strict=True))
    except ValueError as exc:
        raise ReferenceSealError(f"{label} escapes the benchmark pack") from exc
    if not path.is_file() or path.is_symlink():
        raise ReferenceSealError(f"{label} must be a regular non-symlink file")
    return path


def _verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "amt-benchmark-pack/v1":
        raise ReferenceSealError("unsupported benchmark pack schema")
    payload = manifest.get("freeze_payload")
    if not isinstance(payload, dict):
        raise ReferenceSealError("benchmark freeze_payload is missing")
    actual = canonical_json_sha256(payload)
    if actual != manifest.get("benchmark_freeze_sha256"):
        raise ReferenceSealError("benchmark freeze SHA-256 does not match payload")
    return payload


def _verify_frozen_mix(
    pack_dir: Path,
    excerpt: dict[str, Any],
    *,
    excerpt_id: str,
) -> None:
    mix = excerpt.get("mix")
    if not isinstance(mix, dict):
        raise ReferenceSealError(f"{excerpt_id} has no frozen mix record")
    path = _relative_file(
        pack_dir,
        mix.get("path"),
        label=f"{excerpt_id} frozen mix",
    )
    expected_size = mix.get("size_bytes")
    expected_hash = mix.get("sha256")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or path.stat().st_size != expected_size
        or sha256_file(path) != expected_hash
    ):
        raise ReferenceSealError(f"frozen mix changed: {excerpt_id}")


def _verified_annotation_seed(
    pack_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    try:
        seed_path = _relative_file(
            pack_dir,
            "seed_manifest.json",
            label="candidate-corrected seed manifest",
        )
        review_path = _relative_file(
            pack_dir,
            "seed_review_manifest.json",
            label="candidate-corrected seed review manifest",
        )
    except (OSError, ValueError) as exc:
        raise ReferenceSealError(
            "candidate-corrected seed manifest or review manifest is missing"
        ) from exc
    seed = _load_object(seed_path, label="seed manifest")
    review = _load_object(review_path, label="seed review manifest")
    candidate_hash = seed.get("seed_candidate_events_sha256")
    candidate_note_fingerprint = seed.get(
        "seed_candidate_note_fingerprint_sha256"
    )
    candidate_note_fingerprint_scope = seed.get(
        "seed_candidate_note_fingerprint_scope"
    )
    candidate_run_id = seed.get("seed_candidate_run_id")
    candidate_manifest_hash = seed.get("seed_candidate_run_manifest_sha256")
    if (
        seed.get("schema") != "amt-seeded-reference/v1"
        or seed.get("benchmark_freeze_sha256")
        != manifest["benchmark_freeze_sha256"]
        or not isinstance(candidate_hash, str)
        or len(candidate_hash) != 64
        or any(character not in "0123456789abcdef" for character in candidate_hash)
        or not isinstance(candidate_run_id, str)
        or not candidate_run_id
        or not isinstance(candidate_note_fingerprint, str)
        or len(candidate_note_fingerprint) != 64
        or any(
            character not in "0123456789abcdef"
            for character in candidate_note_fingerprint
        )
        or candidate_note_fingerprint_scope
        != "frozen_evaluation_windows_onset_offset_pitch_instrument_v1"
        or not isinstance(candidate_manifest_hash, str)
        or len(candidate_manifest_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in candidate_manifest_hash
        )
    ):
        raise ReferenceSealError("candidate-corrected seed manifest is invalid")
    if (
        review.get("schema") != "amt-seed-review-result/v1"
        or review.get("status") != "human_review_applied_ready_to_seal"
        or review.get("benchmark_freeze_sha256")
        != manifest["benchmark_freeze_sha256"]
        or review.get("seed_candidate_events_sha256") != candidate_hash
    ):
        raise ReferenceSealError("candidate-corrected seed review manifest is invalid")
    seed_references = seed.get("references")
    review_references = review.get("references")
    if not isinstance(seed_references, list) or not isinstance(
        review_references, list
    ):
        raise ReferenceSealError(
            "candidate-corrected seed or review references are invalid"
        )
    seed_by_excerpt = {
        record.get("excerpt_id"): record
        for record in seed_references
        if isinstance(record, dict)
    }
    review_by_excerpt = {
        record.get("excerpt_id"): record
        for record in review_references
        if isinstance(record, dict)
    }
    expected_excerpts = {
        excerpt["excerpt_id"]: excerpt
        for excerpt in manifest["freeze_payload"]["excerpts"]
    }
    if (
        set(seed_by_excerpt) != set(expected_excerpts)
        or set(review_by_excerpt) != set(expected_excerpts)
        or len(seed_by_excerpt) != len(seed_references)
        or len(review_by_excerpt) != len(review_references)
    ):
        raise ReferenceSealError(
            "candidate-corrected seed review must cover every excerpt exactly once"
        )
    for excerpt_id, excerpt in expected_excerpts.items():
        seed_record = seed_by_excerpt[excerpt_id]
        review_record = review_by_excerpt[excerpt_id]
        if (
            seed_record.get("reference_notes_path")
            != excerpt.get("reference_notes_path")
        ):
            raise ReferenceSealError(
                f"{excerpt_id} seed reference path does not match benchmark"
            )
        reference_path = _relative_file(
            pack_dir,
            excerpt.get("reference_notes_path"),
            label=f"{excerpt_id} reviewed reference notes",
        )
        correction_path = _relative_file(
            pack_dir,
            review_record.get("correction_session_path"),
            label=f"{excerpt_id} reviewed correction session",
        )
        try:
            reference_count = len(read_reference_jsonl(reference_path))
        except (OSError, EvaluationError) as exc:
            raise ReferenceSealError(str(exc)) from exc
        if (
            sha256_file(reference_path)
            != review_record.get("reference_notes_sha256")
            or reference_count != review_record.get("reference_note_count")
            or sha256_file(correction_path)
            != review_record.get("correction_session_sha256")
        ):
            raise ReferenceSealError(
                f"{excerpt_id} changed after the recorded human seed review"
            )
    return {
        "seed_manifest_path": "seed_manifest.json",
        "seed_manifest_sha256": sha256_file(seed_path),
        "seed_review_manifest_path": "seed_review_manifest.json",
        "seed_review_manifest_sha256": sha256_file(review_path),
        "candidate_run_id": candidate_run_id,
        "candidate_worker": seed.get("seed_candidate_worker"),
        "candidate_events_sha256": candidate_hash,
        "candidate_note_fingerprint_sha256": candidate_note_fingerprint,
        "candidate_note_fingerprint_scope": candidate_note_fingerprint_scope,
        "candidate_run_manifest_sha256": candidate_manifest_hash,
    }


def seal_reference_pack(
    pack_dir: Path,
    *,
    annotator_id: str,
    creation_method: str,
    coverage_confirmed: bool,
    empty_excerpt_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not annotator_id.strip():
        raise ReferenceSealError("annotator_id is required")
    if creation_method not in {"from_scratch", "candidate_corrected"}:
        raise ReferenceSealError("creation_method must be from_scratch or candidate_corrected")
    if not coverage_confirmed:
        raise ReferenceSealError("human coverage confirmation is required")
    pack_dir = pack_dir.resolve(strict=True)
    seal_path = pack_dir / "reference_seal.json"
    if seal_path.exists():
        raise ReferenceSealError("reference seal already exists")
    manifest = _load_object(pack_dir / "benchmark_manifest.json", label="benchmark manifest")
    payload = _verify_manifest(manifest)
    seed_markers = (
        "reference_seed_policy.json",
        "seed_manifest.json",
        "seed_review_manifest.json",
    )
    if creation_method == "from_scratch" and any(
        (pack_dir / marker).exists() or (pack_dir / marker).is_symlink()
        for marker in seed_markers
    ):
        raise ReferenceSealError(
            "from_scratch sealing is forbidden when candidate seed artifacts "
            "or policy exist"
        )
    annotation_seed = (
        _verified_annotation_seed(pack_dir, manifest)
        if creation_method == "candidate_corrected"
        else None
    )
    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or not excerpts:
        raise ReferenceSealError("benchmark has no excerpts")
    empty_excerpt_ids = empty_excerpt_ids or set()
    known_excerpt_ids = {excerpt.get("excerpt_id") for excerpt in excerpts}
    unknown_empty = sorted(empty_excerpt_ids - known_excerpt_ids)
    if unknown_empty:
        raise ReferenceSealError(f"unknown empty excerpt IDs: {unknown_empty}")

    sealed_at = datetime.now(UTC).isoformat()
    references: list[dict[str, Any]] = []
    reference_note_ids: set[str] = set()
    for excerpt in excerpts:
        excerpt_id = excerpt.get("excerpt_id")
        if not isinstance(excerpt_id, str) or not excerpt_id:
            raise ReferenceSealError("benchmark excerpt_id is missing")
        _verify_frozen_mix(pack_dir, excerpt, excerpt_id=excerpt_id)
        reference_path = _relative_file(
            pack_dir,
            excerpt.get("reference_notes_path"),
            label=f"{excerpt_id} reference notes",
        )
        annotation_path = _relative_file(
            pack_dir,
            excerpt.get("annotation_plan_path"),
            label=f"{excerpt_id} annotation plan",
        )
        try:
            notes = read_reference_jsonl(reference_path)
        except (OSError, EvaluationError) as exc:
            raise ReferenceSealError(str(exc)) from exc
        included = [note for note in notes if note.evaluation_status == "include"]
        if not included and excerpt_id not in empty_excerpt_ids:
            raise ReferenceSealError(
                f"{excerpt_id} has no included reference notes; use --empty-excerpt only "
                "after confirming no target melody is present"
            )
        duplicate_ids = sorted(
            note.reference_note_id
            for note in notes
            if note.reference_note_id in reference_note_ids
        )
        if duplicate_ids:
            raise ReferenceSealError(
                f"reference note IDs must be unique across the pack: {duplicate_ids}"
            )
        reference_note_ids.update(note.reference_note_id for note in notes)
        start = excerpt.get("evaluation_start_sec")
        end = excerpt.get("evaluation_end_sec")
        audio_end = excerpt.get("audio_end_sec")
        for note in notes:
            if not start <= note.onset_sec < end:
                raise ReferenceSealError(
                    f"{excerpt_id} note {note.reference_note_id} onset is outside "
                    "the frozen evaluation window"
                )
            if note.offset_sec > audio_end + 1e-9:
                raise ReferenceSealError(
                    f"{excerpt_id} note {note.reference_note_id} offset exceeds "
                    "the frozen context audio"
                )
            if note.offset_censored and abs(note.offset_sec - audio_end) > (
                1 / 44_100 + 1e-9
            ):
                raise ReferenceSealError(
                    f"{excerpt_id} note {note.reference_note_id} is offset-censored "
                    "away from the frozen context boundary"
                )
        annotation = _load_object(annotation_path, label=f"{excerpt_id} annotation plan")
        if (
            annotation.get("schema") != "amt-annotation-plan/v1"
            or annotation.get("excerpt_id") != excerpt_id
        ):
            raise ReferenceSealError(f"{excerpt_id} annotation plan is invalid")
        correction_record = None
        if creation_method == "candidate_corrected":
            correction_path = pack_dir / "corrections" / f"{excerpt_id}.json"
            if not correction_path.is_file() or correction_path.is_symlink():
                raise ReferenceSealError(
                    f"{excerpt_id} requires corrections/{excerpt_id}.json for "
                    "candidate_corrected sealing"
                )
            correction = _load_object(
                correction_path,
                label=f"{excerpt_id} correction session",
            )
            try:
                correction_summary = summarize_correction_session(correction)
            except EvaluationError as exc:
                raise ReferenceSealError(f"{excerpt_id}: {exc}") from exc
            if (
                correction.get("benchmark_freeze_sha256")
                != manifest["benchmark_freeze_sha256"]
                or correction_summary["excerpt_id"] != excerpt_id
                or abs(
                    correction_summary["audio_duration_sec"]
                    - float(excerpt["duration_sec"])
                )
                > 1e-6
                or correction_summary["candidate_sha256"]
                != annotation_seed["candidate_events_sha256"]
            ):
                raise ReferenceSealError(
                    f"{excerpt_id} correction session does not match benchmark"
                )
            correction_record = {
                "path": f"corrections/{excerpt_id}.json",
                "sha256": sha256_file(correction_path),
                "summary": correction_summary,
            }
        references.append(
            {
                "excerpt_id": excerpt_id,
                "contains_target_melody": bool(included),
                "reference_notes_path": excerpt.get("reference_notes_path"),
                "reference_notes_sha256": sha256_file(reference_path),
                "reference_note_count": len(notes),
                "included_reference_note_count": len(included),
                "annotation_plan_path": excerpt.get("annotation_plan_path"),
                "annotation_plan_sha256": sha256_file(annotation_path),
                "correction_session": correction_record,
            }
        )

    seal_payload = {
        "schema": "amt-reference-seal/v1",
        "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
        "annotator_id": annotator_id,
        "creation_method": creation_method,
        "annotation_seed": annotation_seed,
        "coverage_targets_human_confirmed": True,
        "sealed_at": sealed_at,
        "references": references,
    }
    seal = {
        **seal_payload,
        "reference_seal_sha256": canonical_json_sha256(seal_payload),
        "claims": {
            "human_confirmed": True,
            "candidate_corrected": creation_method == "candidate_corrected",
            "correction_effort_required_for_candidate_comparison": (
                creation_method == "candidate_corrected"
            ),
        },
    }
    atomic_write_json(seal_path, seal)
    return seal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--annotator-id", required=True)
    parser.add_argument(
        "--creation-method",
        choices=("from_scratch", "candidate_corrected"),
        required=True,
    )
    parser.add_argument("--empty-excerpt", action="append", default=[])
    parser.add_argument(
        "--confirm-human-reviewed",
        action="store_true",
        help="Required acknowledgement that a human reviewed every reference.",
    )
    parser.add_argument(
        "--confirm-coverage",
        action="store_true",
        help="Required acknowledgement that the frozen excerpts cover their named targets.",
    )
    args = parser.parse_args()
    if not args.confirm_human_reviewed:
        parser.error("--confirm-human-reviewed is required")
    if not args.confirm_coverage:
        parser.error("--confirm-coverage is required")
    seal = seal_reference_pack(
        args.pack_dir,
        annotator_id=args.annotator_id,
        creation_method=args.creation_method,
        coverage_confirmed=args.confirm_coverage,
        empty_excerpt_ids=set(args.empty_excerpt),
    )
    print(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
