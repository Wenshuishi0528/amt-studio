from __future__ import annotations

import json
import stat
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import scripts.evaluate_benchmark as evaluate_benchmark_module
from scripts.create_reference_pack import ReferencePackError, create_reference_pack
from scripts.evaluate_benchmark import BenchmarkEvaluationError, evaluate_benchmark
from scripts.freeze_evaluation_candidates import freeze_candidate_set
from scripts.manage_seeded_reference import (
    SeededReferenceError,
    apply_human_review,
    seed_references,
)
from scripts.seal_reference_pack import ReferenceSealError, seal_reference_pack

from amt_core.benchmark import BenchmarkError, BenchmarkSpec, canonical_json_sha256
from amt_core.evaluation import ReferenceNote, read_reference_jsonl, write_reference_jsonl
from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import sha256_file


def _spec(*, split: str = "development", exposed: bool = True) -> dict[str, object]:
    return {
        "schema": "amt-benchmark-spec/v1",
        "benchmark_id": "fixture-task006",
        "project_id": "fixture-project",
        "split": split,
        "song_group_id": "fixture-song",
        "artist_group_id": "fixture-artist",
        "prior_system_exposure": exposed,
        "excerpts": [
            {
                "excerpt_id": "excerpt-01",
                "start_sec": 1.0,
                "duration_sec": 2.0,
                "coverage_targets": [
                    "lead_vocal",
                    "vibrato_or_glissando",
                    "weak_notes",
                ],
                "selection_basis": "fixture coverage",
            },
            {
                "excerpt_id": "excerpt-02",
                "start_sec": 4.0,
                "duration_sec": 2.0,
                "coverage_targets": [
                    "chorus_or_harmony",
                    "dense_accompaniment",
                    "instrumental_intro_or_interlude",
                ],
                "selection_basis": "fixture coverage",
            },
        ],
    }


def _write_wav(path: Path, duration_sec: float = 8.0) -> None:
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00\x00\x00" * round(duration_sec * 44100))


def _write_fake_ffmpeg(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
import sys
import wave

args = sys.argv[1:]
if "-version" in args:
    print("ffmpeg fixture 1.0")
    raise SystemExit(0)
duration = float(args[args.index("-t") + 1])
with wave.open(args[-1], "wb") as handle:
    handle.setnchannels(2)
    handle.setsampwidth(2)
    handle.setframerate(44100)
    handle.writeframes(b"\\x00\\x00\\x00\\x00" * round(duration * 44100))
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    project = root / "fixture-project"
    mix = project / "audio" / "canonical" / "mix.wav"
    _write_wav(mix)
    (project / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "fixture-project",
                "canonical_audio": {
                    "path": "audio/canonical/mix.wav",
                    "sha256": sha256_file(mix),
                    "metadata": {"duration_sec": 8.0},
                },
            }
        ),
        encoding="utf-8",
    )
    spec_path = root / "benchmark.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    ffmpeg = _write_fake_ffmpeg(root / "fake-ffmpeg")
    return project, spec_path, ffmpeg


def _write_worker_candidate(
    project: Path,
    *,
    canonical_sha256: str,
    events: list[NoteEvent],
    run_id: str = "fixture-run",
    project_id: str = "fixture-project",
) -> Path:
    run_dir = project / "runs" / run_id
    events_path = run_dir / "normalized" / "events.jsonl"
    write_jsonl(events_path, events)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "project_id": project_id,
                "worker": "game",
                "status": "succeeded",
                "input_lineage": {
                    "canonical_mix_sha256": canonical_sha256,
                },
                "outputs": [
                    {
                        "path": "normalized/events.jsonl",
                        "sha256": sha256_file(events_path),
                        "size_bytes": events_path.stat().st_size,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return events_path


class ReferenceBenchmarkTests(unittest.TestCase):
    def test_blind_split_rejects_prior_system_exposure(self) -> None:
        with self.assertRaisesRegex(BenchmarkError, "prior_system_exposure"):
            BenchmarkSpec.from_dict(_spec(split="blind_test", exposed=True))

    def test_spec_requires_every_task006_coverage_target(self) -> None:
        value = _spec()
        value["excerpts"] = [value["excerpts"][0]]
        with self.assertRaisesRegex(BenchmarkError, "missing required coverage"):
            BenchmarkSpec.from_dict(value)

    def test_pack_is_frozen_refuses_overwrite_and_evaluation_before_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            manifest = create_reference_pack(
                project,
                spec_path,
                pack,
                ffmpeg=str(ffmpeg),
            )
            self.assertEqual(manifest["status"], "awaiting_human_annotation")
            self.assertEqual(len(manifest["benchmark_freeze_sha256"]), 64)
            self.assertTrue((pack / "excerpts" / "excerpt-01" / "mix.wav").is_file())
            with self.assertRaisesRegex(ReferencePackError, "already exists"):
                create_reference_pack(
                    project,
                    spec_path,
                    pack,
                    ffmpeg=str(ffmpeg),
                )
            with self.assertRaisesRegex(BenchmarkEvaluationError, "reference seal"):
                evaluate_benchmark(pack, [("candidate", root / "missing.jsonl")], root / "report")

    def test_seal_rejects_modified_frozen_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            create_reference_pack(project, spec_path, pack, ffmpeg=str(ffmpeg))
            frozen_mix = pack / "excerpts" / "excerpt-01" / "mix.wav"
            frozen_mix.write_bytes(frozen_mix.read_bytes() + b"tampered")

            with self.assertRaisesRegex(ReferenceSealError, "frozen mix changed"):
                seal_reference_pack(
                    pack,
                    annotator_id="owner",
                    creation_method="from_scratch",
                    coverage_confirmed=True,
                    empty_excerpt_ids={"excerpt-01", "excerpt-02"},
                )

    def test_seal_rejects_offset_censoring_away_from_context_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            create_reference_pack(project, spec_path, pack, ffmpeg=str(ffmpeg))
            write_reference_jsonl(
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl",
                [
                    ReferenceNote(
                        reference_note_id="misused-censor",
                        onset_sec=1.5,
                        offset_sec=2.0,
                        pitch_midi=60,
                        instrument="voice",
                        annotator_confidence=1,
                        ambiguity_tags=("phrase_boundary",),
                        offset_censored=True,
                    )
                ],
            )
            with self.assertRaisesRegex(
                ReferenceSealError,
                "offset-censored away from the frozen context boundary",
            ):
                seal_reference_pack(
                    pack,
                    annotator_id="owner",
                    creation_method="from_scratch",
                    coverage_confirmed=True,
                    empty_excerpt_ids={"excerpt-02"},
                )

    def test_sealed_reference_can_evaluate_and_detect_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "标注 pack"
            create_reference_pack(
                project,
                spec_path,
                pack,
                ffmpeg=str(ffmpeg),
            )
            for excerpt_id, onset in (("excerpt-01", 1.5), ("excerpt-02", 4.5)):
                write_reference_jsonl(
                    pack / "excerpts" / excerpt_id / "reference_notes.jsonl",
                    [
                        ReferenceNote(
                            reference_note_id=f"{excerpt_id}-note",
                            onset_sec=onset,
                            offset_sec=onset + 0.5,
                            pitch_midi=60,
                            instrument="voice",
                            annotator_confidence=1.0,
                        )
                    ],
                )
            seal = seal_reference_pack(
                pack,
                annotator_id="owner",
                creation_method="from_scratch",
                coverage_confirmed=True,
            )
            self.assertTrue(seal["claims"]["human_confirmed"])

            canonical_sha256 = json.loads(
                (pack / "benchmark_manifest.json").read_text(encoding="utf-8")
            )["freeze_payload"]["canonical_audio_sha256"]
            candidate_path = _write_worker_candidate(
                project,
                canonical_sha256=canonical_sha256,
                events=[
                    NoteEvent(
                        event_id=f"candidate-{index}",
                        track_id="main-melody",
                        onset_sec=onset + 0.01,
                        offset_sec=onset + 0.51,
                        pitch_midi=60,
                        source_run_id="fixture-run",
                        source_model="fixture-model",
                        instrument="voice",
                        confidence=0.9,
                        is_main_melody_candidate=True,
                    )
                    for index, onset in enumerate((1.5, 4.5), start=1)
                ],
            )
            output = root / "report"
            report = evaluate_benchmark(
                pack,
                [("candidate", candidate_path)],
                output,
            )
            metric = report["measured_results"][0]["metrics"]["primary"]["onset_pitch"]
            self.assertEqual(metric["f1"], 1)
            self.assertTrue((output / "metrics_by_track.csv").is_file())
            self.assertTrue((output / "precision_coverage.csv").is_file())
            self.assertTrue((output / "error_taxonomy.csv").is_file())
            self.assertTrue((output / "correction_time.csv").is_file())
            self.assertTrue((output / "run_manifest.json").is_file())
            evaluation_manifest = json.loads(
                (output / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evaluation_manifest["status"], "succeeded")
            for artifact in evaluation_manifest["outputs"]:
                artifact_path = output / artifact["path"]
                self.assertEqual(artifact_path.stat().st_size, artifact["size_bytes"])
                self.assertEqual(sha256_file(artifact_path), artifact["sha256"])

            reference_during_evaluation = (
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            )
            original_reference = reference_during_evaluation.read_bytes()
            snapshot_race_output = root / "snapshot-race-report"
            original_verify_snapshots = (
                evaluate_benchmark_module._verify_input_snapshots
            )

            def change_reference_before_publish(snapshots: object) -> None:
                reference_during_evaluation.write_bytes(original_reference + b"\n")
                original_verify_snapshots(snapshots)

            with (
                patch.object(
                    evaluate_benchmark_module,
                    "_verify_input_snapshots",
                    side_effect=change_reference_before_publish,
                ),
                self.assertRaisesRegex(
                    BenchmarkEvaluationError,
                    "changed during benchmark evaluation",
                ),
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    snapshot_race_output,
                )
            self.assertFalse(snapshot_race_output.exists())
            self.assertFalse(
                list(root.glob(f".{snapshot_race_output.name}.*"))
            )
            reference_during_evaluation.write_bytes(original_reference)

            appeared_output = root / "appeared-report"
            appeared_marker = appeared_output / "keep.txt"

            def create_output_before_publish(snapshots: object) -> None:
                original_verify_snapshots(snapshots)
                appeared_output.mkdir()
                appeared_marker.write_text("keep", encoding="utf-8")

            with (
                patch.object(
                    evaluate_benchmark_module,
                    "_verify_input_snapshots",
                    side_effect=create_output_before_publish,
                ),
                self.assertRaisesRegex(
                    BenchmarkEvaluationError,
                    "output directory appeared during evaluation",
                ),
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    appeared_output,
                )
            self.assertEqual(appeared_marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse(list(root.glob(f".{appeared_output.name}.*")))

            wrong_duration_log = root / "wrong-duration-correction.json"
            wrong_duration_log.write_text(
                json.dumps(
                    {
                        "schema": "amt-correction-session/v1",
                        "session_id": "wrong-duration",
                        "benchmark_freeze_sha256": seal[
                            "benchmark_freeze_sha256"
                        ],
                        "excerpt_id": "excerpt-01",
                        "candidate_sha256": sha256_file(candidate_path),
                        "audio_duration_sec": 20,
                        "total_edit_time_sec": 1,
                        "review_granularity": "note_level_edit",
                        "operations": [
                            {
                                "operation_id": "op-1",
                                "action": "pitch",
                                "elapsed_edit_sec": 1,
                                "source_note_ids": ["candidate-1"],
                                "result_note_ids": ["reference-1"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "does not belong to this benchmark",
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    root / "wrong-duration-report",
                    correction_logs=[wrong_duration_log],
                )

            annotation_candidate = _write_worker_candidate(
                project,
                canonical_sha256=canonical_sha256,
                run_id="annotation-run",
                events=[
                    NoteEvent(
                        event_id="annotation-note",
                        track_id="main-melody",
                        onset_sec=1.5,
                        offset_sec=2.0,
                        pitch_midi=60,
                        source_run_id="annotation-run",
                        source_model="annotation-helper",
                        instrument="voice",
                        is_main_melody_candidate=True,
                        tags=["annotation-only", "not-evaluation-candidate"],
                    )
                ],
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "ineligible events",
            ):
                evaluate_benchmark(
                    pack,
                    [("annotation", annotation_candidate)],
                    root / "annotation-report",
                )

            multitrack_candidate = _write_worker_candidate(
                project,
                canonical_sha256=canonical_sha256,
                run_id="multitrack-run",
                events=[
                    NoteEvent(
                        event_id="voice-note",
                        track_id="voice",
                        onset_sec=1.5,
                        offset_sec=2.0,
                        pitch_midi=60,
                        source_run_id="multitrack-run",
                        source_model="fixture-model",
                        instrument="voice",
                    ),
                    NoteEvent(
                        event_id="drum-note",
                        track_id="drums",
                        onset_sec=1.5,
                        offset_sec=1.6,
                        pitch_midi=36,
                        source_run_id="multitrack-run",
                        source_model="fixture-model",
                        instrument="drums",
                    ),
                ],
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "requires one explicitly flagged melody track",
            ):
                evaluate_benchmark(
                    pack,
                    [("multitrack", multitrack_candidate)],
                    root / "multitrack-report",
                )

            frozen_mix = pack / "excerpts" / "excerpt-01" / "mix.wav"
            original_frozen_mix = frozen_mix.read_bytes()
            frozen_mix.write_bytes(original_frozen_mix + b"tampered")
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "frozen mix changed",
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    root / "tampered-mix-report",
                )
            frozen_mix.write_bytes(original_frozen_mix)

            reference = pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            reference.write_text(reference.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkEvaluationError, "sealed reference changed"):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    root / "tampered-report",
                )

    def test_candidate_corrected_seal_requires_correction_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            create_reference_pack(project, spec_path, pack, ffmpeg=str(ffmpeg))
            for excerpt_id, onset in (("excerpt-01", 1.5), ("excerpt-02", 4.5)):
                write_reference_jsonl(
                    pack / "excerpts" / excerpt_id / "reference_notes.jsonl",
                    [
                        ReferenceNote(
                            reference_note_id=f"{excerpt_id}-note",
                            onset_sec=onset,
                            offset_sec=onset + 0.5,
                            pitch_midi=60,
                            instrument="voice",
                            annotator_confidence=1.0,
                        )
                    ],
                )
            with self.assertRaisesRegex(
                ReferenceSealError,
                "candidate-corrected seed manifest",
            ):
                seal_reference_pack(
                    pack,
                    annotator_id="owner",
                    creation_method="candidate_corrected",
                    coverage_confirmed=True,
                )

    def test_blind_evaluation_requires_exact_preinspection_candidate_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            spec_path.write_text(
                json.dumps(_spec(split="blind_test", exposed=False)),
                encoding="utf-8",
            )
            pack = root / "blind-pack"
            manifest = create_reference_pack(
                project,
                spec_path,
                pack,
                ffmpeg=str(ffmpeg),
            )
            for excerpt_id, onset in (("excerpt-01", 1.5), ("excerpt-02", 4.5)):
                write_reference_jsonl(
                    pack / "excerpts" / excerpt_id / "reference_notes.jsonl",
                    [
                        ReferenceNote(
                            reference_note_id=f"{excerpt_id}-note",
                            onset_sec=onset,
                            offset_sec=onset + 0.5,
                            pitch_midi=60,
                            instrument="voice",
                            annotator_confidence=1,
                        )
                    ],
                )
            seal_reference_pack(
                pack,
                annotator_id="owner",
                creation_method="from_scratch",
                coverage_confirmed=True,
            )
            candidate_path = _write_worker_candidate(
                project,
                canonical_sha256=manifest["freeze_payload"][
                    "canonical_audio_sha256"
                ],
                run_id="blind-candidate",
                events=[
                    NoteEvent(
                        event_id=f"blind-{index}",
                        track_id="main-melody",
                        onset_sec=onset,
                        offset_sec=onset + 0.5,
                        pitch_midi=60,
                        source_run_id="blind-candidate",
                        source_model="fixture-model",
                        instrument="voice",
                        is_main_melody_candidate=True,
                    )
                    for index, onset in enumerate((1.5, 4.5), start=1)
                ],
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "sealed before output quality inspection",
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate", candidate_path)],
                    root / "unsealed-candidate-report",
                )
            candidate_set = freeze_candidate_set(
                pack,
                [("candidate", candidate_path)],
                output_quality_uninspected=True,
            )
            report = evaluate_benchmark(
                pack,
                [("candidate", candidate_path)],
                root / "sealed-candidate-report",
            )
            self.assertTrue(report["claims"]["blind_test_result"])
            self.assertEqual(
                report["benchmark"]["candidate_set_sha256"],
                candidate_set["candidate_set_sha256"],
            )

    def test_blind_candidate_corrected_evaluation_excludes_only_sealed_seed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            spec_path.write_text(
                json.dumps(_spec(split="blind_test", exposed=False)),
                encoding="utf-8",
            )
            pack = root / "blind-pack"
            manifest = create_reference_pack(
                project,
                spec_path,
                pack,
                ffmpeg=str(ffmpeg),
            )
            canonical_sha256 = manifest["freeze_payload"][
                "canonical_audio_sha256"
            ]

            def candidate(run_id: str, pitch: int) -> Path:
                return _write_worker_candidate(
                    project,
                    canonical_sha256=canonical_sha256,
                    run_id=run_id,
                    events=[
                        NoteEvent(
                            event_id=f"{run_id}-{index}",
                            track_id="voice",
                            onset_sec=onset,
                            offset_sec=onset + 0.5,
                            pitch_midi=pitch,
                            source_run_id=run_id,
                            source_model="fixture-model",
                            instrument="voice",
                        )
                        for index, onset in enumerate((1.5, 4.5), start=1)
                    ],
                )

            seed_path = candidate("blind-seed", 60)
            candidate_a_path = candidate("blind-candidate-a", 61)
            candidate_b_path = candidate("blind-candidate-b", 62)
            candidate_set = freeze_candidate_set(
                pack,
                [
                    ("seed", seed_path),
                    ("candidate-a", candidate_a_path),
                    ("candidate-b", candidate_b_path),
                ],
                output_quality_uninspected=True,
            )
            (pack / "reference_seed_policy.json").write_text(
                json.dumps(
                    {
                        "schema": "amt-reference-seed-policy/v1",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "seed_method": "candidate_corrected",
                        "seed_candidate_label": "seed",
                        "seed_candidate_run_id": "blind-seed",
                    }
                ),
                encoding="utf-8",
            )
            seed_references(pack, seed_path)
            review_path = root / "owner-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "schema": "amt-seed-review/v1",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "reviewer": "project_owner",
                        "excerpts": [
                            {
                                "excerpt_id": excerpt_id,
                                "decision": "accept_seed",
                                "full_playback_count": 1,
                                "additional_review_sec": 0,
                                "annotator_confidence": 1,
                                "ambiguity_tags": [],
                            }
                            for excerpt_id in ("excerpt-01", "excerpt-02")
                        ],
                    }
                ),
                encoding="utf-8",
            )
            apply_human_review(pack, review_path)
            seal_reference_pack(
                pack,
                annotator_id="owner",
                creation_method="candidate_corrected",
                coverage_confirmed=True,
            )

            output = root / "candidate-corrected-report"
            report = evaluate_benchmark(
                pack,
                [
                    ("candidate-a", candidate_a_path),
                    ("candidate-b", candidate_b_path),
                ],
                output,
            )
            self.assertEqual(
                {item["label"] for item in report["measured_results"]},
                {"candidate-a", "candidate-b"},
            )
            self.assertEqual(
                report["benchmark"]["excluded_sealed_annotation_seed"],
                {
                    "label": "seed",
                    "run_id": "blind-seed",
                    "worker": "game",
                    "events_sha256": sha256_file(seed_path),
                    "run_manifest_sha256": sha256_file(
                        seed_path.parent.parent / "run_manifest.json"
                    ),
                    "reason": "candidate_used_to_create_reference",
                },
            )
            self.assertEqual(
                report["benchmark"]["candidate_set_sha256"],
                candidate_set["candidate_set_sha256"],
            )
            persisted = json.loads(
                (output / "evaluation_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                persisted["benchmark"]["excluded_sealed_annotation_seed"],
                report["benchmark"]["excluded_sealed_annotation_seed"],
            )

            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "exactly match",
            ):
                evaluate_benchmark(
                    pack,
                    [("candidate-a", candidate_a_path)],
                    root / "missing-candidate-report",
                )

            rogue_path = candidate("blind-rogue", 63)
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "exactly match",
            ):
                evaluate_benchmark(
                    pack,
                    [
                        ("candidate-a", candidate_a_path),
                        ("candidate-b", candidate_b_path),
                        ("rogue", rogue_path),
                    ],
                    root / "added-candidate-report",
                )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "does not match the sealed blind set",
            ):
                evaluate_benchmark(
                    pack,
                    [
                        ("candidate-a", candidate_a_path),
                        ("candidate-b", rogue_path),
                    ],
                    root / "substituted-candidate-report",
                )

            candidate_seal_path = pack / "candidate_set_seal.json"
            candidate_seal = json.loads(
                candidate_seal_path.read_text(encoding="utf-8")
            )
            candidate_seal["freeze_payload"]["candidates"] = [
                record
                for record in candidate_seal["freeze_payload"]["candidates"]
                if record["label"] != "seed"
            ]
            candidate_seal["candidate_set_sha256"] = canonical_json_sha256(
                candidate_seal["freeze_payload"]
            )
            candidate_seal_path.write_text(
                json.dumps(candidate_seal),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "match exactly one sealed candidate",
            ):
                evaluate_benchmark(
                    pack,
                    [
                        ("candidate-a", candidate_a_path),
                        ("candidate-b", candidate_b_path),
                    ],
                    root / "unsealed-seed-report",
                )

    def test_candidate_seed_requires_owner_review_and_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            manifest = create_reference_pack(project, spec_path, pack, ffmpeg=str(ffmpeg))
            policy = {
                "schema": "amt-reference-seed-policy/v1",
                "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
                "seed_method": "candidate_corrected",
                "seed_candidate_label": "seed",
                "seed_candidate_run_id": "seed-run",
            }
            (pack / "reference_seed_policy.json").write_text(
                json.dumps(policy),
                encoding="utf-8",
            )
            fabricated_path = root / "fabricated-seed.jsonl"
            write_jsonl(
                fabricated_path,
                [
                    NoteEvent(
                        event_id="fabricated",
                        track_id="voice",
                        onset_sec=1.5,
                        offset_sec=2.0,
                        pitch_midi=60,
                        source_run_id="seed-run",
                        source_model="fabricated",
                        instrument="voice",
                    )
                ],
            )
            with self.assertRaisesRegex(
                SeededReferenceError,
                "worker run normalized/events.jsonl",
            ):
                seed_references(pack, fabricated_path)
            candidate_path = _write_worker_candidate(
                project,
                canonical_sha256=manifest["freeze_payload"][
                    "canonical_audio_sha256"
                ],
                run_id="seed-run",
                events=[
                    NoteEvent(
                        event_id=f"seed-{index}",
                        track_id="voice",
                        onset_sec=onset,
                        offset_sec=onset + 0.5,
                        pitch_midi=60,
                        source_run_id="seed-run",
                        source_model="seed-model",
                        instrument="voice",
                    )
                    for index, onset in enumerate((1.5, 4.5), start=1)
                ],
            )
            seed = seed_references(pack, candidate_path)
            self.assertFalse(seed["claims"]["human_confirmed"])
            with self.assertRaisesRegex(
                ReferenceSealError,
                "from_scratch sealing is forbidden",
            ):
                seal_reference_pack(
                    pack,
                    annotator_id="owner",
                    creation_method="from_scratch",
                    coverage_confirmed=True,
                )
            provisional = read_reference_jsonl(
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            )
            self.assertEqual(provisional[0].annotator_confidence, 0)
            self.assertEqual(provisional[0].ambiguity_tags, ("source_identity",))

            review_path = root / "owner-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "schema": "amt-seed-review/v1",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "reviewer": "project_owner",
                        "excerpts": [
                            {
                                "excerpt_id": excerpt_id,
                                "decision": "accept_seed",
                                "full_playback_count": 2,
                                "additional_review_sec": 3,
                                "annotator_confidence": 0.8,
                                "ambiguity_tags": [],
                            }
                            for excerpt_id in ("excerpt-01", "excerpt-02")
                        ],
                    }
                ),
                encoding="utf-8",
            )
            applied = apply_human_review(pack, review_path)
            self.assertEqual(applied["status"], "human_review_applied_ready_to_seal")
            confirmed = read_reference_jsonl(
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            )
            self.assertEqual(confirmed[0].annotator_confidence, 0.8)
            self.assertEqual(confirmed[0].ambiguity_tags, ())
            correction = json.loads(
                (pack / "corrections" / "excerpt-01.json").read_text(encoding="utf-8")
            )
            self.assertEqual(correction["review_granularity"], "whole_excerpt_aural_comparison")
            self.assertEqual(correction["total_edit_time_sec"], 7)
            reviewed_reference_path = (
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            )
            reviewed_reference_bytes = reviewed_reference_path.read_bytes()
            reviewed_note = read_reference_jsonl(reviewed_reference_path)[0]
            write_reference_jsonl(
                reviewed_reference_path,
                [
                    ReferenceNote(
                        reference_note_id=reviewed_note.reference_note_id,
                        onset_sec=reviewed_note.onset_sec,
                        offset_sec=reviewed_note.offset_sec,
                        pitch_midi=reviewed_note.pitch_midi + 12,
                        instrument=reviewed_note.instrument,
                        annotator_confidence=reviewed_note.annotator_confidence,
                    )
                ],
            )
            with self.assertRaisesRegex(
                ReferenceSealError,
                "changed after the recorded human seed review",
            ):
                seal_reference_pack(
                    pack,
                    annotator_id="owner",
                    creation_method="candidate_corrected",
                    coverage_confirmed=True,
                )
            reviewed_reference_path.write_bytes(reviewed_reference_bytes)
            seal = seal_reference_pack(
                pack,
                annotator_id="owner",
                creation_method="candidate_corrected",
                coverage_confirmed=True,
            )
            self.assertTrue(seal["claims"]["candidate_corrected"])
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "annotation seed is ineligible",
            ):
                evaluate_benchmark(
                    pack,
                    [("seed", candidate_path)],
                    root / "leaky-seed-report",
                )
            semantic_rerun = _write_worker_candidate(
                project,
                canonical_sha256=manifest["freeze_payload"][
                    "canonical_audio_sha256"
                ],
                run_id="seed-semantic-rerun",
                events=[
                    NoteEvent(
                        event_id=f"rerun-{index}",
                        track_id="voice",
                        onset_sec=onset,
                        offset_sec=onset + 0.5,
                        pitch_midi=60,
                        source_run_id="seed-semantic-rerun",
                        source_model="seed-model",
                        instrument="voice",
                        quantized_pitch_midi=72,
                    )
                    for index, onset in enumerate((1.5, 4.5), start=1)
                ]
                + [
                    NoteEvent(
                        event_id="rerun-outside-scored-windows",
                        track_id="voice",
                        onset_sec=7.0,
                        offset_sec=7.5,
                        pitch_midi=99,
                        source_run_id="seed-semantic-rerun",
                        source_model="seed-model",
                        instrument="voice",
                    )
                ],
            )
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "semantic copy of the annotation seed",
            ):
                evaluate_benchmark(
                    pack,
                    [("semantic-rerun", semantic_rerun)],
                    root / "semantic-seed-report",
                )
            (pack / "seed_manifest.json").unlink()
            with self.assertRaisesRegex(
                BenchmarkEvaluationError,
                "sealed annotation seed manifest is missing",
            ):
                evaluate_benchmark(
                    pack,
                    [("seed", candidate_path)],
                    root / "deleted-seed-manifest-report",
                )

    def test_candidate_seed_supports_audited_note_level_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, spec_path, ffmpeg = _fixture(root)
            pack = root / "pack"
            manifest = create_reference_pack(
                project,
                spec_path,
                pack,
                ffmpeg=str(ffmpeg),
            )
            (pack / "reference_seed_policy.json").write_text(
                json.dumps(
                    {
                        "schema": "amt-reference-seed-policy/v1",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "seed_method": "candidate_corrected",
                        "seed_candidate_label": "seed",
                        "seed_candidate_run_id": "seed-run",
                    }
                ),
                encoding="utf-8",
            )
            candidate_path = _write_worker_candidate(
                project,
                canonical_sha256=manifest["freeze_payload"][
                    "canonical_audio_sha256"
                ],
                run_id="seed-run",
                events=[
                    NoteEvent(
                        event_id=f"seed-{index}",
                        track_id="voice",
                        onset_sec=onset,
                        offset_sec=onset + 0.5,
                        pitch_midi=60,
                        source_run_id="seed-run",
                        source_model="seed-model",
                        instrument="voice",
                    )
                    for index, onset in enumerate((1.5, 4.5), start=1)
                ],
            )
            seed = seed_references(pack, candidate_path)
            corrected_path = root / "corrected-excerpt-01.jsonl"
            write_reference_jsonl(
                corrected_path,
                [
                    ReferenceNote(
                        reference_note_id="excerpt-01-corrected-0001",
                        onset_sec=1.5,
                        offset_sec=2.0,
                        pitch_midi=61,
                        instrument="voice",
                        annotator_confidence=0.9,
                    )
                ],
            )
            correction_path = root / "correction-excerpt-01.json"
            correction_path.write_text(
                json.dumps(
                    {
                        "schema": "amt-correction-session/v1",
                        "session_id": "excerpt-01-note-edit",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "excerpt_id": "excerpt-01",
                        "candidate_sha256": seed[
                            "seed_candidate_events_sha256"
                        ],
                        "audio_duration_sec": 2.0,
                        "total_edit_time_sec": 5.0,
                        "review_granularity": "note_level_edit",
                        "operations": [
                            {
                                "operation_id": "pitch-1",
                                "action": "pitch",
                                "elapsed_edit_sec": 5.0,
                                "source_note_ids": ["excerpt-01-seed-0001"],
                                "result_note_ids": [
                                    "excerpt-01-corrected-0001"
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            review_path = root / "owner-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "schema": "amt-seed-review/v1",
                        "benchmark_freeze_sha256": manifest[
                            "benchmark_freeze_sha256"
                        ],
                        "reviewer": "project_owner",
                        "excerpts": [
                            {
                                "excerpt_id": "excerpt-01",
                                "decision": "needs_note_correction",
                                "corrected_reference_path": str(corrected_path),
                                "correction_session_path": str(correction_path),
                            },
                            {
                                "excerpt_id": "excerpt-02",
                                "decision": "accept_seed",
                                "full_playback_count": 1,
                                "additional_review_sec": 0,
                                "annotator_confidence": 0.8,
                                "ambiguity_tags": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            applied = apply_human_review(pack, review_path)
            by_excerpt = {
                record["excerpt_id"]: record
                for record in applied["references"]
            }
            self.assertEqual(applied["review_granularity"], "mixed")
            self.assertEqual(
                by_excerpt["excerpt-01"]["decision"],
                "note_correction_applied",
            )
            self.assertEqual(
                by_excerpt["excerpt-01"]["review_granularity"],
                "note_level_edit",
            )
            corrected = read_reference_jsonl(
                pack / "excerpts" / "excerpt-01" / "reference_notes.jsonl"
            )
            self.assertEqual(corrected[0].pitch_midi, 61)
            persisted_correction = json.loads(
                (pack / "corrections" / "excerpt-01.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                persisted_correction["review_granularity"],
                "note_level_edit",
            )
            seal = seal_reference_pack(
                pack,
                annotator_id="owner",
                creation_method="candidate_corrected",
                coverage_confirmed=True,
            )
            self.assertTrue(seal["claims"]["candidate_corrected"])


if __name__ == "__main__":
    unittest.main()
