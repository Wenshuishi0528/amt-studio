from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import mido

from amt_core.bundle import (
    BundleBuildError,
    build_canonical_bundle,
    build_muscriptor_multitrack_bundle,
)
from amt_core.canonical import MeterPoint, RhythmEvent, RhythmMap, TempoPoint
from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json, sha256_file


def _output(path: Path, run_dir: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(run_dir)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _project(root: Path) -> tuple[Path, str]:
    project = root / "项目"
    canonical = project / "audio" / "canonical" / "mix.flac"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical audio fixture")
    canonical_hash = sha256_file(canonical)
    atomic_write_json(
        project / "manifest.json",
        {
            "schema_version": 1,
            "project_id": project.name,
            "canonical_audio": {
                "path": "audio/canonical/mix.flac",
                "sha256": canonical_hash,
                "metadata": {"duration_sec": 10},
            },
        },
    )
    return project, canonical_hash


def _note_run(
    project: Path,
    canonical_hash: str,
    *,
    worker: str,
    run_id: str,
    pitch: float,
) -> Path:
    run_dir = project / "runs" / run_id
    events_path = run_dir / "normalized" / "events.jsonl"
    write_jsonl(
        events_path,
        [
            NoteEvent(
                event_id=f"{run_id}-note",
                track_id="voice",
                instrument="voice",
                onset_sec=0.13,
                offset_sec=0.91,
                pitch_midi=pitch,
                source_run_id=run_id,
                source_model=f"{worker}-model",
            )
        ],
    )
    atomic_write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "project_id": project.name,
            "worker": worker,
            "model": f"{worker}-model",
            "status": "succeeded",
            "input_lineage": {"canonical_mix_sha256": canonical_hash},
            "outputs": [_output(events_path, run_dir)],
        },
    )
    return run_dir


def _beat_run(project: Path, canonical_hash: str) -> Path:
    run_id = "beat-run"
    run_dir = project / "runs" / run_id
    rhythm_path = run_dir / "normalized" / "rhythm.json"
    events = tuple(
        RhythmEvent(
            event_id=f"beat-{index + 1}",
            time_sec=index * 0.5,
            beat_number=index % 4 + 1,
            is_downbeat=index % 4 == 0,
            confidence=None,
            source_frame_index=index * 25,
        )
        for index in range(9)
    )
    rhythm = RhythmMap(
        source_run_id=run_id,
        source_model="final0",
        canonical_audio_sha256=canonical_hash,
        events=events,
        tempo_map=(
            TempoPoint(
                time_sec=0.0,
                bpm=120.0,
                confidence=None,
                uncertainty_bpm=None,
                source_event_ids=("beat-1", "beat-2"),
                method="adjacent_beat_interval",
            ),
        ),
        meter_map=(
            MeterPoint(
                time_sec=0.0,
                numerator=4,
                denominator=4,
                confidence=None,
                source_event_ids=("beat-1", "beat-5"),
                status="inferred",
            ),
        ),
        uncertainty={
            "event_confidence_available": False,
            "raw_framewise_logits_preserved": True,
        },
    )
    atomic_write_json(rhythm_path, rhythm.to_dict())
    atomic_write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "contract_version": "amt-worker-result/v1",
            "run_id": run_id,
            "project_id": project.name,
            "worker": "beat_this",
            "model": "final0",
            "status": "succeeded",
            "input_lineage": {"canonical_mix_sha256": canonical_hash},
            "outputs": [_output(rhythm_path, run_dir)],
        },
    )
    return run_dir


class BundleTests(unittest.TestCase):
    def test_multitrack_bundle_derives_tail_sustain_and_preserves_raw_events(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            run_id = "muscriptor-tail"
            run_dir = project / "runs" / run_id
            events_path = run_dir / "normalized" / "events.jsonl"
            fragments = [
                NoteEvent(
                    event_id=f"tail-{index}",
                    track_id="muscriptor-native:clean_electric_guitar",
                    instrument="clean_electric_guitar",
                    onset_sec=8 + index * 0.27,
                    offset_sec=8.25 + index * 0.27,
                    pitch_midi=64,
                    source_run_id=run_id,
                    source_model="muscriptor-model",
                )
                for index in range(8)
            ]
            write_jsonl(events_path, fragments)
            atomic_write_json(
                run_dir / "run_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "project_id": project.name,
                    "worker": "muscriptor",
                    "status": "succeeded",
                    "input_lineage": {
                        "canonical_mix_sha256": canonical_hash
                    },
                    "outputs": [_output(events_path, run_dir)],
                },
            )

            output = project / "exports" / "muscriptor-tail-product"
            build_muscriptor_multitrack_bundle(project, run_dir, output)
            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (
                    output / "reports" / "trailing_sustain_cleanup.json"
                ).read_text(encoding="utf-8")
            )

            self.assertEqual(canonical["tracks"][0]["event_count"], 1)
            self.assertEqual(report["tracks"][0]["group_count"], 1)
            self.assertEqual(
                len(
                    (output / "raw_tracks" / "clean_electric_guitar.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ),
                8,
            )
            self.assertEqual(
                len(events_path.read_text(encoding="utf-8").splitlines()),
                8,
            )

    def test_builds_muscriptor_instrument_tracks_with_voice_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            run_id = "muscriptor-full"
            run_dir = project / "runs" / run_id
            events_path = run_dir / "normalized" / "events.jsonl"
            write_jsonl(
                events_path,
                [
                    NoteEvent(
                        event_id="piano-note",
                        track_id="muscriptor-native:acoustic_piano",
                        instrument="acoustic_piano",
                        onset_sec=0.1,
                        offset_sec=0.5,
                        pitch_midi=60,
                        source_run_id=run_id,
                        source_model="muscriptor-model",
                    ),
                    NoteEvent(
                        event_id="voice-note",
                        track_id="muscriptor-native:voice",
                        instrument="voice",
                        onset_sec=0.2,
                        offset_sec=0.8,
                        pitch_midi=72,
                        source_run_id=run_id,
                        source_model="muscriptor-model",
                    ),
                    NoteEvent(
                        event_id="trumpet-note",
                        track_id="muscriptor-native:trumpet",
                        instrument="trumpet",
                        onset_sec=0.3,
                        offset_sec=0.9,
                        pitch_midi=67,
                        source_run_id=run_id,
                        source_model="muscriptor-model",
                    ),
                ],
            )
            native_midi = run_dir / "raw" / "full.native.mid"
            native_midi.parent.mkdir(parents=True)
            native_midi.write_bytes(b"MThd-native")
            atomic_write_json(
                run_dir / "run_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "project_id": project.name,
                    "worker": "muscriptor",
                    "status": "succeeded",
                    "input_lineage": {"canonical_mix_sha256": canonical_hash},
                    "outputs": [
                        _output(events_path, run_dir),
                        _output(native_midi, run_dir),
                    ],
                },
            )
            output = project / "exports" / "muscriptor-multitrack"
            manifest = build_muscriptor_multitrack_bundle(project, run_dir, output)
            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )
            midi = mido.MidiFile(output / "performance.mid")

            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(
                [track["track_id"] for track in canonical["tracks"]],
                ["voice", "acoustic_piano", "trumpet"],
            )
            self.assertEqual(canonical["main_melody_track_id"], "voice")
            self.assertEqual(len(midi.tracks), 4)
            self.assertEqual(
                [
                    message.program
                    for message in midi.tracks[1]
                    if message.type == "program_change"
                ],
                [52],
            )
            self.assertEqual(
                [
                    message.program
                    for message in midi.tracks[3]
                    if message.type == "program_change"
                ],
                [56],
            )
            self.assertTrue((output / "muscriptor.native.mid").is_file())
            self.assertEqual(
                {
                    record["path"]
                    for record in manifest["outputs"]
                    if record["path"].startswith("tracks/")
                },
                {
                    "tracks/acoustic_piano.jsonl",
                    "tracks/trumpet.jsonl",
                    "tracks/voice.jsonl",
                },
            )
            self.assertFalse(canonical["claims"]["accuracy_claimed"])

    def test_multitrack_bundle_uses_verified_rhythm_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            note_run = _note_run(
                project,
                canonical_hash,
                worker="muscriptor",
                run_id="muscriptor-with-rhythm",
                pitch=69.0,
            )
            beat_run = _beat_run(project, canonical_hash)
            output = project / "exports" / "muscriptor-with-rhythm"

            build_muscriptor_multitrack_bundle(
                project,
                note_run,
                output,
                beat_run_dir=beat_run,
            )

            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )
            midi = mido.MidiFile(output / "performance.mid")
            rhythm = canonical["rhythm"]
            self.assertEqual(rhythm["source_run_id"], "beat-run")
            self.assertEqual(rhythm["source_model"], "final0")
            self.assertEqual(len(rhythm["events"]), 9)
            self.assertEqual(rhythm["meter_map"][0]["numerator"], 4)
            self.assertEqual(
                {result["worker"] for result in canonical["worker_results"]},
                {"muscriptor", "beat_this"},
            )
            self.assertTrue(canonical["claims"]["tempo_inferred"])
            tempo_messages = [
                message
                for message in midi.tracks[0]
                if message.type == "set_tempo"
            ]
            self.assertTrue(tempo_messages)
            self.assertEqual(mido.tempo2bpm(tempo_messages[0].tempo), 120.0)

    def test_multitrack_bundle_preserves_tracks_beyond_one_midi_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            run_id = "muscriptor-many-tracks"
            run_dir = project / "runs" / run_id
            events_path = run_dir / "normalized" / "events.jsonl"
            instruments = [f"instrument_{index:02d}" for index in range(17)]
            write_jsonl(
                events_path,
                [
                    NoteEvent(
                        event_id=f"note-{index}",
                        track_id=f"muscriptor-native:{instrument}",
                        instrument=instrument,
                        onset_sec=index * 0.01,
                        offset_sec=index * 0.01 + 0.2,
                        pitch_midi=60 + index % 12,
                        source_run_id=run_id,
                        source_model="muscriptor-model",
                    )
                    for index, instrument in enumerate(instruments)
                ],
            )
            atomic_write_json(
                run_dir / "run_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "project_id": project.name,
                    "worker": "muscriptor",
                    "status": "succeeded",
                    "input_lineage": {"canonical_mix_sha256": canonical_hash},
                    "outputs": [_output(events_path, run_dir)],
                },
            )
            output = project / "exports" / "many-tracks"
            build_muscriptor_multitrack_bundle(project, run_dir, output)
            canonical = json.loads(
                (output / "canonical_project.json").read_text(encoding="utf-8")
            )

            self.assertEqual(len(canonical["tracks"]), 17)
            self.assertFalse((output / "performance.mid").exists())
            self.assertEqual(
                canonical["exports"]["performance_midi"]["report"]["status"],
                "unavailable",
            )
            self.assertEqual(
                len(list((output / "tracks").glob("*.jsonl"))),
                17,
            )

    def test_performance_midi_accepts_fifteen_melodic_tracks_plus_drums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            run_id = "muscriptor-sixteen-tracks"
            run_dir = project / "runs" / run_id
            events_path = run_dir / "normalized" / "events.jsonl"
            instruments = ["drums", *[f"melodic_{index:02d}" for index in range(15)]]
            write_jsonl(
                events_path,
                [
                    NoteEvent(
                        event_id=f"note-{index}",
                        track_id=f"muscriptor-native:{instrument}",
                        instrument=instrument,
                        onset_sec=index * 0.01,
                        offset_sec=index * 0.01 + 0.2,
                        pitch_midi=36 if instrument == "drums" else 60,
                        source_run_id=run_id,
                        source_model="muscriptor-model",
                    )
                    for index, instrument in enumerate(instruments)
                ],
            )
            atomic_write_json(
                run_dir / "run_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "project_id": project.name,
                    "worker": "muscriptor",
                    "status": "succeeded",
                    "input_lineage": {"canonical_mix_sha256": canonical_hash},
                    "outputs": [_output(events_path, run_dir)],
                },
            )
            output = project / "exports" / "sixteen-tracks"
            build_muscriptor_multitrack_bundle(project, run_dir, output)
            midi = mido.MidiFile(output / "performance.mid")

            self.assertEqual(len(midi.tracks), 17)
            drum_note_ons = [
                message
                for track in midi.tracks
                for message in track
                if message.type == "note_on"
                and message.velocity > 0
                and message.channel == 9
            ]
            self.assertEqual(len(drum_note_ons), 1)

    def test_builds_separate_candidate_tracks_performance_midi_and_score_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            candidates = {
                "game": _note_run(
                    project,
                    canonical_hash,
                    worker="game",
                    run_id="game-run",
                    pitch=69.2,
                ),
                "basic": _note_run(
                    project,
                    canonical_hash,
                    worker="basic_pitch",
                    run_id="basic-run",
                    pitch=70.0,
                ),
                "muscriptor": _note_run(
                    project,
                    canonical_hash,
                    worker="muscriptor",
                    run_id="muscriptor-run",
                    pitch=71.0,
                ),
            }
            output = project / "exports" / "task005"
            manifest = build_canonical_bundle(
                project,
                _beat_run(project, canonical_hash),
                candidates,
                output,
            )
            canonical = json.loads((output / "canonical_project.json").read_text(encoding="utf-8"))
            score_lines = (
                (output / "score-grid-experiment.jsonl").read_text(encoding="utf-8").splitlines()
            )
            midi = mido.MidiFile(output / "performance.mid")

        self.assertEqual(manifest["status"], "succeeded")
        self.assertEqual(len(canonical["tracks"]), 3)
        self.assertEqual({track["role"] for track in canonical["tracks"]}, {"candidate"})
        self.assertEqual(len(score_lines), 3)
        self.assertEqual(len(midi.tracks), 4)
        self.assertFalse(canonical["claims"]["candidate_fusion_performed"])
        self.assertFalse(canonical["claims"]["preferred_candidate_selected"])
        self.assertEqual(
            canonical["exports"]["score_grid_experiment"]["status"],
            "experimental_not_notation",
        )

    def test_rejects_cross_song_candidate_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            candidate = _note_run(
                project,
                "b" * 64,
                worker="game",
                run_id="game-run",
                pitch=69.0,
            )
            output = project / "exports" / "task005"
            with self.assertRaisesRegex(BundleBuildError, "canonical mix"):
                build_canonical_bundle(
                    project,
                    _beat_run(project, canonical_hash),
                    {"game": candidate},
                    output,
                )
            self.assertFalse(output.exists())

    def test_refuses_existing_output_and_duplicate_candidate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, canonical_hash = _project(Path(temporary))
            candidate = _note_run(
                project,
                canonical_hash,
                worker="game",
                run_id="game-run",
                pitch=69.0,
            )
            beat = _beat_run(project, canonical_hash)
            existing = project / "exports" / "existing"
            existing.mkdir(parents=True)
            with self.assertRaisesRegex(BundleBuildError, "already exists"):
                build_canonical_bundle(
                    project,
                    beat,
                    {"game": candidate},
                    existing,
                )
            with self.assertRaisesRegex(BundleBuildError, "paths must be distinct"):
                build_canonical_bundle(
                    project,
                    beat,
                    {"a": candidate, "b": candidate},
                    project / "exports" / "new",
                )

    def test_rejects_canonical_audio_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, canonical_hash = _project(root)
            outside = root / "outside.flac"
            outside.write_bytes(b"canonical audio fixture")
            manifest_path = project / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["canonical_audio"] = {
                "path": "../outside.flac",
                "sha256": canonical_hash,
            }
            atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(BundleBuildError, "escapes"):
                build_canonical_bundle(
                    project,
                    project / "runs" / "unused",
                    {"unused": project / "runs" / "unused"},
                    project / "exports" / "unsafe",
                )


if __name__ == "__main__":
    unittest.main()
