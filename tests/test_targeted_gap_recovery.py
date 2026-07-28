from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.product_postprocess import automatic_voice_candidate_admission
from amt_core.utils import atomic_write_json, sha256_file
from workers.muscriptor.gap_probe import ProbeWindow, TargetInterval
from workers.muscriptor.gap_probe import _directed_child_arguments, spec_as_dict
from workers.muscriptor.targeted_gap_recovery import (
    TargetedGapRecoveryError,
    build_recovery_bundle,
    build_recovery_stage_comparison_bundle,
    plan_selected_gaps,
    reconstruct_recovery_stages,
    shift_target_candidates,
)


def _event(
    event_id: str,
    *,
    instrument: str,
    onset: float,
    offset: float,
    pitch: float = 60,
) -> NoteEvent:
    return NoteEvent(
        event_id=event_id,
        track_id=f"native:{instrument}",
        instrument=instrument,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        quantized_pitch_midi=round(pitch),
        velocity=80,
        confidence=0.8,
        is_main_melody_candidate=instrument == "voice",
        source_run_id="source-run",
        source_model="MuScriptor/muscriptor-large@fixture",
        source_event_ids=[f"native:{event_id}"],
        tags=["fixture"],
        extra={},
    )


def _fixture_project(root: Path) -> tuple[Path, dict]:
    project = root / "song"
    source_bundle = project / "exports/source-bundle"
    tracks = source_bundle / "tracks"
    tracks.mkdir(parents=True)
    audio = project / "audio/canonical.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"canonical-audio-fixture")
    canonical_audio = {
        "path": "audio/canonical.wav",
        "sha256": sha256_file(audio),
        "metadata": {
            "duration_sec": 120,
            "sample_rate": 44100,
            "channels": 2,
        },
    }
    atomic_write_json(
        project / "manifest.json",
        {
            "schema_version": 1,
            "project_id": "song",
            "canonical_audio": canonical_audio,
        },
    )
    voice = [
        _event("voice-before", instrument="voice", onset=5, offset=6),
        _event("voice-after", instrument="voice", onset=90, offset=91),
    ]
    guitar = [
        _event(
            "guitar-before",
            instrument="clean_electric_guitar",
            onset=2,
            offset=3,
            pitch=52,
        )
    ]
    voice_path = tracks / "voice.jsonl"
    guitar_path = tracks / "clean_electric_guitar.jsonl"
    write_jsonl(voice_path, voice)
    write_jsonl(guitar_path, guitar)
    canonical = {
        "schema_version": 1,
        "artifact_type": "amt-canonical-project",
        "project_id": "song",
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_audio": canonical_audio,
        "worker_results": [],
        "tracks": [
            {
                "track_id": "voice",
                "label": "voice",
                "role": "candidate",
                "instrument": "voice",
                "event_count": len(voice),
                "source_events_path": (
                    "exports/source-bundle/tracks/voice.jsonl"
                ),
                "provenance": {
                    "source_run_id": "source-run",
                    "source_model": "MuScriptor/muscriptor-large@fixture",
                    "run_manifest_sha256": "a" * 64,
                    "normalized_artifact_sha256": sha256_file(voice_path),
                },
            },
            {
                "track_id": "clean_electric_guitar",
                "label": "clean electric guitar",
                "role": "candidate",
                "instrument": "clean_electric_guitar",
                "event_count": len(guitar),
                "source_events_path": (
                    "exports/source-bundle/tracks/clean_electric_guitar.jsonl"
                ),
                "provenance": {
                    "source_run_id": "source-run",
                    "source_model": "MuScriptor/muscriptor-large@fixture",
                    "run_manifest_sha256": "a" * 64,
                    "normalized_artifact_sha256": sha256_file(guitar_path),
                },
            },
        ],
        "main_melody_track_id": "voice",
        "rhythm": {
            "tempo_map": [{"time_sec": 0, "bpm": 120}],
            "meter_map": [
                {
                    "time_sec": 0,
                    "numerator": 4,
                    "denominator": 4,
                }
            ],
        },
        "exports": {},
        "claims": {"accuracy_claimed": False},
    }
    atomic_write_json(source_bundle / "canonical_project.json", canonical)
    return project, canonical


class TargetedGapRecoveryTests(unittest.TestCase):
    def test_selected_track_decode_uses_its_instrument_allowlist(self) -> None:
        arguments = _directed_child_arguments(
            project_dir=Path("/project"),
            clip_path=Path("/project/clip.flac"),
            worker_env=Path("/worker"),
            weight_provenance=Path("/weights.json"),
            child_run_id="gap-child",
            device="cuda",
            instrument="clean_electric_guitar",
        )
        index = arguments.index("--instruments")
        self.assertEqual(
            arguments[index + 1],
            "clean_electric_guitar",
        )
        self.assertIn("--allow-empty-jsonl", arguments)

    def test_selected_gaps_are_one_request_with_bounded_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _canonical = _fixture_project(Path(temporary))
            spec = plan_selected_gaps(
                project,
                probe_id="targeted-recovery-v1",
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(10, 30), (40, 60)],
            )
            self.assertEqual(len(spec.windows), 2)
            self.assertEqual(spec.windows[0].clip_start_sec, 6.001)
            self.assertEqual(spec.windows[1].clip_end_sec, 63.999)
            self.assertEqual(
                {
                    target.target_id
                    for window in spec.windows
                    for target in window.targets
                },
                {"gap-01", "gap-02"},
            )

    def test_gap_may_end_at_audio_boundary_but_not_beyond_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _canonical = _fixture_project(Path(temporary))
            spec = plan_selected_gaps(
                project,
                probe_id="targeted-recovery-at-end",
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(100, 120)],
            )
            self.assertEqual(spec.windows[0].clip_end_sec, 120)
            with self.assertRaisesRegex(
                TargetedGapRecoveryError,
                "outside the song timeline",
            ):
                plan_selected_gaps(
                    project,
                    probe_id="targeted-recovery-past-end",
                    source_bundle_id="source-bundle",
                    source_track_id="voice",
                    intervals=[(100, 120.03)],
                )

    def test_nonempty_or_overlapping_selection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _canonical = _fixture_project(Path(temporary))
            with self.assertRaisesRegex(Exception, "not empty"):
                plan_selected_gaps(
                    project,
                    probe_id="targeted-recovery-v1",
                    source_bundle_id="source-bundle",
                    source_track_id="voice",
                    intervals=[(5.2, 5.8)],
                )
            with self.assertRaisesRegex(
                TargetedGapRecoveryError,
                "must not overlap",
            ):
                plan_selected_gaps(
                    project,
                    probe_id="targeted-recovery-v2",
                    source_bundle_id="source-bundle",
                    source_track_id="voice",
                    intervals=[(10, 30), (20, 40)],
                )

    def test_candidate_filter_follows_selected_accompaniment_instrument(self) -> None:
        target = TargetInterval("gap-01", 10, 20, "selected")
        window = ProbeWindow("window-01", 6, 24, (target,))
        candidates = shift_target_candidates(
            [
                _event(
                    "guitar",
                    instrument="clean_electric_guitar",
                    onset=6,
                    offset=7,
                    pitch=55,
                ),
                _event("voice", instrument="voice", onset=8, offset=9),
            ],
            probe_id="targeted-recovery-v1",
            window=window,
            source_track_id="clean_electric_guitar",
            instrument="clean_electric_guitar",
            main_melody=False,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].onset_sec, 12)
        self.assertEqual(
            candidates[0].track_id,
            "targeted-gap:clean_electric_guitar",
        )
        self.assertFalse(candidates[0].is_main_melody_candidate)

    def test_new_bundle_augments_only_target_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical = _fixture_project(Path(temporary))
            spec = plan_selected_gaps(
                project,
                probe_id="targeted-recovery-v1",
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(10, 30)],
            )
            source_path = (
                project / "exports/source-bundle/tracks/voice.jsonl"
            )
            source_hash = sha256_file(source_path)
            candidate = _event(
                "candidate",
                instrument="voice",
                onset=15,
                offset=16,
                pitch=67,
            )
            run_manifest = (
                project / "runs/targeted-recovery-v1/run_manifest.json"
            )
            run_manifest.parent.mkdir(parents=True)
            atomic_write_json(
                run_manifest,
                {"schema_version": 1, "status": "succeeded"},
            )
            output = project / "exports/targeted-recovery-v1-multitrack"
            manifest = build_recovery_bundle(
                project,
                spec=spec,
                source_canonical=canonical,
                source_events=read_jsonl(source_path),
                candidates=[candidate],
                run_manifest_path=run_manifest,
                output_dir=output,
            )
            self.assertEqual(sha256_file(source_path), source_hash)
            output_canonical = json.loads(
                (output / "canonical_project.json").read_text(
                    encoding="utf-8"
                )
            )
            counts = {
                track["track_id"]: track["event_count"]
                for track in output_canonical["tracks"]
            }
            self.assertEqual(counts["voice"], 3)
            self.assertEqual(counts["clean_electric_guitar"], 1)
            self.assertFalse(
                output_canonical["claims"]["source_bundle_overwritten"]
            )
            self.assertEqual(
                output_canonical["claims"]["targeted_source_bundle_id"],
                "source-bundle",
            )
            self.assertEqual(manifest["status"], "succeeded")

    def test_empty_recovery_is_a_successful_unchanged_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical = _fixture_project(Path(temporary))
            spec = plan_selected_gaps(
                project,
                probe_id="targeted-recovery-empty",
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(10, 30)],
            )
            source_path = project / "exports/source-bundle/tracks/voice.jsonl"
            source_events = read_jsonl(source_path)
            run_manifest = (
                project
                / "runs/targeted-recovery-empty/run_manifest.json"
            )
            run_manifest.parent.mkdir(parents=True)
            atomic_write_json(
                run_manifest,
                {"schema_version": 1, "status": "succeeded"},
            )
            output = (
                project
                / "exports/targeted-recovery-empty-multitrack"
            )

            manifest = build_recovery_bundle(
                project,
                spec=spec,
                source_canonical=canonical,
                source_events=source_events,
                candidates=[],
                product_candidates=[],
                product_admission=automatic_voice_candidate_admission(
                    source_note_count=len(source_events),
                    candidate_note_count=0,
                ),
                run_manifest_path=run_manifest,
                output_dir=output,
            )

            output_canonical = json.loads(
                (output / "canonical_project.json").read_text(
                    encoding="utf-8"
                )
            )
            voice = next(
                track
                for track in output_canonical["tracks"]
                if track["track_id"] == "voice"
            )
            self.assertEqual(voice["event_count"], len(source_events))
            self.assertEqual(
                output_canonical["claims"][
                    "recovered_candidate_note_count"
                ],
                0,
            )
            self.assertFalse(
                output_canonical["claims"]["automatic_merge_performed"]
            )
            self.assertEqual(manifest["status"], "succeeded")

    def test_large_raw_voice_recovery_is_merged_without_count_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical = _fixture_project(Path(temporary))
            spec = plan_selected_gaps(
                project,
                probe_id="targeted-recovery-rejected",
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(10, 30)],
            )
            source_path = project / "exports/source-bundle/tracks/voice.jsonl"
            candidates = [
                _event(
                    f"candidate-{index}",
                    instrument="voice",
                    onset=10 + index * 0.5,
                    offset=10.2 + index * 0.5,
                    pitch=60 + index % 5,
                )
                for index in range(33)
            ]
            admission = automatic_voice_candidate_admission(
                source_note_count=2,
                candidate_note_count=len(candidates),
            )
            run_manifest = (
                project
                / "runs/targeted-recovery-rejected/run_manifest.json"
            )
            run_manifest.parent.mkdir(parents=True)
            atomic_write_json(
                run_manifest,
                {"schema_version": 1, "status": "succeeded"},
            )
            output = (
                project
                / "exports/targeted-recovery-rejected-multitrack"
            )
            build_recovery_bundle(
                project,
                spec=spec,
                source_canonical=canonical,
                source_events=read_jsonl(source_path),
                candidates=candidates,
                product_candidates=candidates,
                product_admission=admission,
                run_manifest_path=run_manifest,
                output_dir=output,
            )
            output_canonical = json.loads(
                (output / "canonical_project.json").read_text(
                    encoding="utf-8"
                )
            )
            counts = {
                track["track_id"]: track["event_count"]
                for track in output_canonical["tracks"]
            }
            self.assertEqual(counts["voice"], 35)
            self.assertNotIn("target_gap_candidate", counts)
            self.assertEqual(
                output_canonical["claims"][
                    "automatic_candidate_admission"
                ],
                "accepted_owner_selected_raw_generation",
            )
            self.assertEqual(
                output_canonical["claims"][
                    "merged_recovered_candidate_note_count"
                ],
                33,
            )
            self.assertTrue(
                output_canonical["claims"]["automatic_merge_performed"]
            )

    def test_completed_recovery_builds_three_exact_comparison_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, _canonical = _fixture_project(Path(temporary))
            run_id = "targeted-recovery-stage-comparison"
            spec = plan_selected_gaps(
                project,
                probe_id=run_id,
                source_bundle_id="source-bundle",
                source_track_id="voice",
                intervals=[(10, 30)],
            )
            config = project / "requests" / f"{run_id}.json"
            config.parent.mkdir()
            atomic_write_json(config, spec_as_dict(spec))
            raw = [
                _event(
                    f"candidate-{index}",
                    instrument="voice",
                    onset=11 + index,
                    offset=11.5 + index,
                    pitch=60 + index,
                )
                for index in range(4)
            ]
            shadowed = raw[1].event_id
            constrained = [raw[0], raw[3]]
            stages = reconstruct_recovery_stages(
                raw,
                constrained,
                {
                    "raw_candidate_count": 4,
                    "accompaniment_shadow_count": 1,
                    "monophonic_rejection_count": 1,
                    "filtered_candidate_count": 2,
                    "shadowed_event_ids": [shadowed],
                },
            )
            self.assertEqual([len(stage) for stage in stages], [4, 3, 2])

            run = project / "runs" / run_id
            normalized = run / "normalized"
            normalized.mkdir(parents=True)
            atomic_write_json(
                run / "run_manifest.json",
                {
                    "schema_version": 1,
                    "status": "succeeded",
                    "probe_id": run_id,
                    "project_id": "song",
                },
            )
            atomic_write_json(
                run / "request.json",
                {
                    "schema_version": 1,
                    "probe_id": run_id,
                    "project_id": "song",
                    "config_path": str(config.relative_to(project)),
                    "config_sha256": sha256_file(config),
                    "canonical_audio_sha256": json.loads(
                        (project / "manifest.json").read_text(encoding="utf-8")
                    )["canonical_audio"]["sha256"],
                },
            )
            write_jsonl(
                normalized / "target_gap_candidates.raw.jsonl",
                raw,
            )
            write_jsonl(
                normalized / "target_gap_candidates.jsonl",
                constrained,
            )
            atomic_write_json(
                normalized / "recovery_report.json",
                {
                    "schema_version": 1,
                    "probe_id": run_id,
                    "accompaniment_soft_mask": {
                        "raw_candidate_count": 4,
                        "accompaniment_shadow_count": 1,
                        "monophonic_rejection_count": 1,
                        "filtered_candidate_count": 2,
                        "shadowed_event_ids": [shadowed],
                    },
                },
            )

            output = project / "exports" / f"{run_id}-comparison"
            manifest = build_recovery_stage_comparison_bundle(
                project,
                recovery_run_id=run_id,
                output_bundle_id=output.name,
            )
            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [track["track_id"] for track in canonical["tracks"]],
                [
                    "gap_raw_candidate",
                    "gap_accompaniment_filtered",
                    "gap_monophonic_candidate",
                ],
            )
            self.assertEqual(
                [track["event_count"] for track in canonical["tracks"]],
                [4, 3, 2],
            )
            event_ids = [
                event.event_id
                for track in canonical["tracks"]
                for event in read_jsonl(project / track["source_events_path"])
            ]
            self.assertEqual(len(event_ids), len(set(event_ids)))
            self.assertEqual(
                canonical["main_melody_track_id"],
                "gap_monophonic_candidate",
            )
            self.assertEqual(
                manifest["claims"]["automatic_candidate_admission"],
                "rejected_excessive_voice_growth",
            )
            self.assertTrue(
                (
                    output
                    / "reports"
                    / "stage_comparison.json"
                ).is_file()
            )
            for track_id in manifest["tracks"]:
                self.assertTrue((output / f"{track_id}.mid").is_file())


if __name__ == "__main__":
    unittest.main()
