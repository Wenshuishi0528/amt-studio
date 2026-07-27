from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.utils import atomic_write_json, sha256_file
from workers.muscriptor.gap_probe import ProbeWindow, TargetInterval
from workers.muscriptor.gap_probe import _directed_child_arguments
from workers.muscriptor.targeted_gap_recovery import (
    TargetedGapRecoveryError,
    build_recovery_bundle,
    plan_selected_gaps,
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


if __name__ == "__main__":
    unittest.main()
