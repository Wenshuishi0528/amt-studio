from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json, sha256_file
from workers.muscriptor.gap_probe import (
    GapProbeError,
    ProbeWindow,
    TargetInterval,
    build_coverage_report,
    build_review_bundle,
    derive_owner_approved_voice,
    load_spec,
    run_probe,
    shift_voice_candidates,
    validate_empty_source_gaps,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _event(
    event_id: str,
    *,
    instrument: str,
    onset: float,
    offset: float,
    pitch: float = 64,
) -> NoteEvent:
    return NoteEvent(
        event_id=event_id,
        track_id=f"native:{instrument}",
        instrument=instrument,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        quantized_pitch_midi=round(pitch),
        velocity=None,
        confidence=None,
        is_main_melody_candidate=False,
        source_run_id="child-run",
        source_model="MuScriptor/muscriptor-large@fixture",
        source_event_ids=[f"native:{event_id}"],
        tags=["candidate"],
        extra={"fixture": True},
    )


def _spec_path(root: Path) -> Path:
    path = root / "config.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "probe_id": "gap-probe-v1",
            "source_bundle_id": "source-bundle",
            "source_voice_track_id": "voice",
            "canonical_duration_sec": 120,
            "context_sec": 4,
            "windows": [
                {
                    "window_id": "mid",
                    "clip_start_sec": 56,
                    "clip_end_sec": 94,
                    "targets": [
                        {
                            "target_id": "gap-01",
                            "start_sec": 60,
                            "end_sec": 90,
                            "expectation": "owner-reported vocal omission",
                        }
                    ],
                }
            ],
        },
    )
    return path


class MuScriptorGapProbeTests(unittest.TestCase):
    def test_spec_is_explicit_and_rejects_overlapping_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = _spec_path(root)
            spec = load_spec(path)
            self.assertEqual(spec.probe_id, "gap-probe-v1")
            self.assertEqual(spec.windows[0].targets[0].start_sec, 60)

            value = json.loads(path.read_text(encoding="utf-8"))
            value["windows"].append(
                {
                    "window_id": "overlap",
                    "clip_start_sec": 80,
                    "clip_end_sec": 100,
                    "targets": [
                        {
                            "target_id": "gap-02",
                            "start_sec": 85,
                            "end_sec": 95,
                            "expectation": "invalid overlap",
                        }
                    ],
                }
            )
            atomic_write_json(path, value)
            with self.assertRaisesRegex(GapProbeError, "overlap"):
                load_spec(path)

    def test_source_voice_must_be_empty_and_candidate_stays_separate(self) -> None:
        target = TargetInterval("gap-01", 60, 90, "reported omission")
        window = ProbeWindow("mid", 56, 94, (target,))
        source = [_event("source-before", instrument="voice", onset=40, offset=41)]
        spec = type(
            "SpecFixture",
            (),
            {"probe_id": "gap-probe-v1", "source_voice_track_id": "voice", "windows": (window,)},
        )()
        validate_empty_source_gaps(source, spec)
        with self.assertRaisesRegex(GapProbeError, "not empty"):
            validate_empty_source_gaps(
                [*source, _event("source-inside", instrument="voice", onset=70, offset=71)],
                spec,
            )

        child = [
            _event("voice-1", instrument="voice", onset=5, offset=6, pitch=65),
            _event("guitar-1", instrument="acoustic_guitar", onset=7, offset=8),
            _event("voice-context", instrument="voice", onset=36.5, offset=37),
        ]
        shifted = shift_voice_candidates(
            child,
            probe_id="gap-probe-v1",
            window=window,
        )
        self.assertEqual(len(shifted), 1)
        self.assertEqual(shifted[0].onset_sec, 61)
        self.assertEqual(shifted[0].track_id, "muscriptor-gap:voice")
        self.assertTrue(shifted[0].is_main_melody_candidate)
        self.assertFalse(
            shifted[0].extra["gap_probe"]["automatic_merge_performed"]
        )

    def test_owner_approved_voice_is_derived_without_changing_sources(self) -> None:
        raw = _event(
            "raw-note",
            instrument="voice",
            onset=10,
            offset=11,
        )
        candidate = _event(
            "gap-note",
            instrument="voice",
            onset=20,
            offset=21,
        )
        enhanced = derive_owner_approved_voice(
            [raw],
            [candidate],
            probe_id="gap-probe-v1",
        )

        self.assertEqual([event.onset_sec for event in enhanced], [10, 20])
        self.assertEqual(raw.event_id, "raw-note")
        self.assertEqual(candidate.event_id, "gap-note")
        self.assertEqual(
            {
                event.extra["owner_approved_voice_enhancement"][
                    "origin_track_id"
                ]
                for event in enhanced
            },
            {"voice_raw", "voice_gap_candidate"},
        )
        self.assertTrue(
            all(
                event.track_id == "derived:voice_enhanced"
                for event in enhanced
            )
        )
        self.assertTrue(
            all(
                source.event_id in derived.source_event_ids
                for source, derived in zip(
                    [raw, candidate],
                    enhanced,
                    strict=True,
                )
            )
        )

    def test_report_leaves_correct_and_false_positive_counts_for_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spec = load_spec(_spec_path(Path(temporary)))
        candidates = [
            _event("candidate", instrument="voice", onset=61, offset=62, pitch=65)
        ]
        report = build_coverage_report(spec, candidates)
        self.assertEqual(report["candidate_note_count"], 1)
        self.assertFalse(report["automatic_merge_performed"])
        self.assertFalse(report["accuracy_claimed"])
        self.assertIsNone(report["targets"][0]["correct_recovered_note_count"])
        self.assertIsNone(report["targets"][0]["false_positive_note_count"])
        self.assertEqual(report["decision"], "awaiting_owner_gap_review")

    def test_review_bundle_keeps_raw_and_gap_candidate_as_two_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "歌曲 project"
            (project / "audio" / "canonical").mkdir(parents=True)
            (project / "exports" / "source-bundle").mkdir(parents=True)
            (project / "runs" / "gap-probe-v1" / "normalized").mkdir(parents=True)
            canonical_audio = project / "audio" / "canonical" / "mix.flac"
            canonical_audio.write_bytes(b"fixture-audio")
            atomic_write_json(
                project / "manifest.json",
                {
                    "schema_version": 1,
                    "project_id": project.name,
                    "title": "fixture",
                    "canonical_audio": {
                        "path": "audio/canonical/mix.flac",
                        "sha256": sha256_file(canonical_audio),
                    },
                },
            )
            source_voice = project / "exports" / "source-bundle" / "voice.jsonl"
            source_events = [
                _event("source", instrument="voice", onset=20, offset=21)
            ]
            write_jsonl(source_voice, source_events)
            source_manifest = project / "runs" / "source-run.json"
            source_manifest.write_text("{}", encoding="utf-8")
            source_canonical = {
                "schema_version": 1,
                "artifact_type": "amt-canonical-project",
                "project_id": project.name,
                "timeline_basis": "original_canonical_mix_seconds",
                "canonical_audio": {
                    "path": "audio/canonical/mix.flac",
                    "sha256": sha256_file(canonical_audio),
                },
                "tracks": [
                    {
                        "track_id": "voice",
                        "label": "voice",
                        "role": "candidate",
                        "instrument": "voice",
                        "event_count": 1,
                        "source_events_path": str(source_voice.relative_to(project)),
                        "provenance": {
                            "source_run_id": "source-run",
                            "source_model": "MuScriptor/source",
                            "run_manifest_sha256": sha256_file(source_manifest),
                            "normalized_artifact_sha256": sha256_file(source_voice),
                        },
                    }
                ],
                "rhythm": {
                    "tempo_map": [
                        {
                            "time_sec": 0,
                            "bpm": 120,
                        }
                    ],
                    "meter_map": [
                        {
                            "time_sec": 0,
                            "numerator": 4,
                            "denominator": 4,
                        }
                    ],
                },
            }
            spec = load_spec(_spec_path(project))
            candidate_path = (
                project
                / "runs"
                / "gap-probe-v1"
                / "normalized"
                / "voice_gap_candidate.jsonl"
            )
            candidates = [
                _event("candidate", instrument="voice", onset=61, offset=62)
            ]
            write_jsonl(candidate_path, candidates)
            parent_manifest = project / "runs" / "gap-probe-v1" / "run_manifest.json"
            atomic_write_json(parent_manifest, {"status": "succeeded"})
            output = project / "exports" / "gap-probe-v1-review"
            bundle = build_review_bundle(
                project,
                spec=spec,
                source_voice_path=source_voice,
                source_canonical=source_canonical,
                source_events=source_events,
                candidate_path=candidate_path,
                candidates=candidates,
                parent_manifest_path=parent_manifest,
                output_dir=output,
            )
            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [track["track_id"] for track in canonical["tracks"]],
                ["voice_raw", "voice_gap_candidate"],
            )
            self.assertFalse(canonical["claims"]["automatic_merge_performed"])
            self.assertTrue(bundle["limitations"])
            self.assertEqual(bundle["status"], "succeeded")

            enhanced_output = project / "exports" / "gap-probe-v1-enhanced"
            enhanced_bundle = build_review_bundle(
                project,
                spec=spec,
                source_voice_path=source_voice,
                source_canonical=source_canonical,
                source_events=source_events,
                candidate_path=candidate_path,
                candidates=candidates,
                parent_manifest_path=parent_manifest,
                output_dir=enhanced_output,
                owner_approved_enhanced=True,
            )
            enhanced_canonical = json.loads(
                (enhanced_output / "canonical_project.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [track["track_id"] for track in enhanced_canonical["tracks"]],
                ["voice_raw", "voice_gap_candidate", "voice_enhanced"],
            )
            self.assertEqual(enhanced_canonical["tracks"][2]["event_count"], 2)
            self.assertTrue(
                enhanced_canonical["claims"][
                    "owner_approved_derivation_performed"
                ]
            )
            self.assertTrue(
                enhanced_canonical["claims"]["preferred_candidate_selected"]
            )
            self.assertIn(
                "tracks/voice_enhanced.jsonl",
                [record["path"] for record in enhanced_bundle["outputs"]],
            )

    def test_run_requires_slurm_before_touching_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(GapProbeError, "Slurm"):
                run_probe(
                    root / "missing-project",
                    root / "missing-config",
                    worker_env=root / "missing-env",
                    weight_provenance=root / "missing-provenance",
                    ffmpeg="ffmpeg",
                )

    def test_slurm_entrypoint_is_compute_only_and_same_model(self) -> None:
        script = (REPO_ROOT / "slurm" / "41_muscriptor_gap_probe.slurm").read_text(
            encoding="utf-8"
        )
        self.assertIn("Refusing to run the MuScriptor gap probe on a login node", script)
        self.assertIn("workers/muscriptor/gap_probe.py", script)
        self.assertIn('module load "${AMT_FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"', script)
        self.assertIn("set +u", script)
        self.assertIn("set -u", script)
        self.assertIn('--ffmpeg "$FFMPEG"', script)
        self.assertNotIn("GAME", script)
        self.assertNotIn("separator", script)

        direct = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "workers" / "muscriptor" / "gap_probe.py"),
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=REPO_ROOT,
        )
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertIn("same-model MuScriptor probes", direct.stdout)


if __name__ == "__main__":
    unittest.main()
