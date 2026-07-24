from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from workers.separator import compare_amt

from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import sha256_file

MODEL_REPOSITORY = "MuScriptor/muscriptor-large"
MODEL_REVISION = "fixture-revision"
MODEL_SOURCE = f"{MODEL_REPOSITORY}@{MODEL_REVISION}"


def _event(
    run_id: str,
    index: int,
    pitch: int,
    onset: float,
    offset: float,
) -> NoteEvent:
    return NoteEvent(
        event_id=f"{run_id}:{index}",
        track_id="voice",
        instrument="voice",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=float(pitch),
        quantized_pitch_midi=pitch,
        source_run_id=run_id,
        source_model=MODEL_SOURCE,
    )


def _write_separator_run(
    project: Path,
    *,
    run_id: str,
    preset: str,
    stem_bytes: bytes,
) -> tuple[Path, dict[str, object]]:
    canonical = project / "audio" / "canonical" / "mix.flac"
    run_dir = project / "runs" / run_id
    stem = run_dir / "raw" / "stems" / "vocals.flac"
    stem.parent.mkdir(parents=True)
    stem.write_bytes(stem_bytes)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "worker": "separator",
        "status": "succeeded",
        "preset": preset,
        "inputs": [
            {
                "path": str(canonical),
                "sha256": sha256_file(canonical),
            }
        ],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": sha256_file(stem),
                "size_bytes": stem.stat().st_size,
            }
        ],
        "metrics": {
            "audio": {
                "mix": {"duration_sec": 12.0},
                "stems": {
                    "vocals": {
                        "duration_sec": 12.0,
                        "duration_drift_sec": 0.0,
                    }
                },
            }
        },
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lineage: dict[str, object] = {
        "kind": "separator_stem",
        "canonical_mix_path": str(canonical),
        "canonical_mix_sha256": sha256_file(canonical),
        "parent_separator_run_id": run_id,
        "parent_separator_preset": preset,
        "parent_manifest_path": str(manifest_path),
        "parent_manifest_sha256": sha256_file(manifest_path),
        "parent_output_path": "raw/stems/vocals.flac",
        "parent_stem_name": "vocals",
        "parent_stem_sha256": sha256_file(stem),
        "timeline": {
            "mix_duration_sec": 12.0,
            "stem_duration_sec": 12.0,
            "stem_duration_drift_sec": 0.0,
        },
    }
    return stem, lineage


def _write_amt_run(
    project: Path,
    *,
    run_id: str,
    audio: Path,
    lineage: dict[str, object],
    events: list[NoteEvent],
    beam_size: int = 4,
) -> Path:
    run_dir = project / "runs" / run_id
    normalized_dir = run_dir / "normalized"
    normalized_dir.mkdir(parents=True)
    events_path = normalized_dir / "events.jsonl"
    write_jsonl(events_path, events)
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "source_model": MODEL_SOURCE,
        "event_count": len(events),
        "instrument_counts": {"voice": len(events)},
        "pitch_midi": {
            "minimum": min((event.pitch_midi for event in events), default=None),
            "maximum": max((event.pitch_midi for event in events), default=None),
        },
        "timeline_sec": {
            "first_onset": min((event.onset_sec for event in events), default=None),
            "last_offset": max((event.offset_sec for event in events), default=None),
        },
        "confidence": {"available": False},
        "velocity": {"available": False},
        "instrument_mapping": {"status": "unmapped"},
    }
    summary_path = normalized_dir / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "worker": "muscriptor",
        "status": "succeeded",
        "model": "large",
        "inputs": [
            {
                "path": str(audio),
                "sha256": sha256_file(audio),
            }
        ],
        "input_lineage": lineage,
        "outputs": [
            {
                "path": "normalized/events.jsonl",
                "sha256": sha256_file(events_path),
                "size_bytes": events_path.stat().st_size,
            },
            {
                "path": "normalized/summary.json",
                "sha256": sha256_file(summary_path),
                "size_bytes": summary_path.stat().st_size,
            },
        ],
        "model_provenance": {
            "package": {"name": "muscriptor", "version": "0.2.2"},
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "weight_sha256": "weight-hash",
            "config_sha256": "config-hash",
        },
        "decoding": {
            "beam_size": beam_size,
            "instruments": ["voice"],
            "dtype": "float32",
            "device": "cuda",
            "skip_midi": True,
            "prelude_forcing": True,
            "sampling": False,
            "cfg_coef": 1.0,
        },
        "metrics": {
            "descriptive_event_summary": summary,
            "accuracy_claimed": False,
        },
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return run_dir


def _fixture(
    project: Path,
    *,
    preset_a: str = "vocal_quality_a",
    preset_b: str = "multistem_quality_a",
) -> dict[str, Path]:
    canonical = project / "audio" / "canonical" / "mix.flac"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical fixture audio")
    stem_a, lineage_a = _write_separator_run(
        project,
        run_id="separator-a",
        preset=preset_a,
        stem_bytes=b"vocal stem a",
    )
    stem_b, lineage_b = _write_separator_run(
        project,
        run_id="separator-b",
        preset=preset_b,
        stem_bytes=b"vocal stem b",
    )
    direct_id = "amt-direct"
    vocal_a_id = "amt-vocal-a"
    vocal_b_id = "amt-vocal-b"
    return {
        "direct": _write_amt_run(
            project,
            run_id=direct_id,
            audio=canonical,
            lineage={
                "kind": "direct_canonical_mix",
                "canonical_mix_path": str(canonical),
                "canonical_mix_sha256": sha256_file(canonical),
            },
            events=[
                _event(direct_id, 0, 60, 1.0, 2.0),
                _event(direct_id, 1, 62, 3.0, 4.0),
            ],
        ),
        "vocal_a": _write_amt_run(
            project,
            run_id=vocal_a_id,
            audio=stem_a,
            lineage=lineage_a,
            events=[
                _event(vocal_a_id, 0, 60, 1.02, 2.05),
                _event(vocal_a_id, 1, 64, 5.0, 6.0),
            ],
        ),
        "vocal_b": _write_amt_run(
            project,
            run_id=vocal_b_id,
            audio=stem_b,
            lineage=lineage_b,
            events=[
                _event(vocal_b_id, 0, 60, 1.01, 2.02),
                _event(vocal_b_id, 1, 62, 3.2, 4.1),
            ],
        ),
    }


class SeparatorAMTComparisonTests(unittest.TestCase):
    def test_controlled_comparison_is_descriptive_and_hash_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project 日本語"
            runs = _fixture(project)
            result = compare_amt.compare_runs(runs)

            self.assertEqual(
                result["comparison_type"],
                "descriptive_amt_path_agreement",
            )
            self.assertFalse(result["claims"]["accuracy_claimed"])
            self.assertFalse(result["claims"]["human_reference_annotations_used"])
            self.assertEqual(
                result["controlled_configuration"]["instruments"],
                ["voice"],
            )
            self.assertTrue(result["timeline_validation"]["all_paths_share_canonical_mix"])
            self.assertTrue(result["timeline_validation"]["parent_stem_hashes_verified"])
            self.assertEqual(
                result["timeline_validation"]["parent_separator_presets"],
                ["multistem_quality_a", "vocal_quality_a"],
            )
            self.assertEqual(
                result["runs"]["vocal_a"]["lineage"]["parent_stem_sha256"],
                sha256_file(project / "runs" / "separator-a" / "raw" / "stems" / "vocals.flac"),
            )
            direct_vocal_a = result["path_agreement"][0]
            self.assertEqual(direct_vocal_a["onset_partner_count"], 1)
            self.assertEqual(
                direct_vocal_a["onset_and_offset_partner_count"],
                1,
            )
            self.assertEqual(
                result["runs"]["direct"]["instrument_constraint_violation_count"],
                0,
            )

            output = Path(temporary) / "report.json"
            argv = [
                "--run",
                f"direct={runs['direct']}",
                "--run",
                f"vocalA={runs['vocal_a']}",
                "--run",
                f"vocalB={runs['vocal_b']}",
                "--output",
                str(output),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(compare_amt.main(argv), 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["claims"][
                    "selection_or_ranking_claimed"
                ],
                False,
            )

    def test_rejects_decoding_configuration_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            runs = _fixture(project)
            manifest_path = runs["vocal_b"] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["decoding"]["beam_size"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                compare_amt.ComparisonError,
                "configuration differs",
            ):
                compare_amt.compare_runs(runs)

    def test_rejects_parent_stem_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            runs = _fixture(project)
            manifest_path = runs["vocal_a"] / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["input_lineage"]["parent_stem_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                compare_amt.ComparisonError,
                "parent stem lineage",
            ):
                compare_amt.compare_runs(runs)

    def test_rejects_wrong_separator_preset_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            runs = _fixture(project, preset_a="experimental_vocals")

            with self.assertRaisesRegex(
                compare_amt.ComparisonError,
                "requires separator preset set",
            ):
                compare_amt.compare_runs(runs)


if __name__ == "__main__":
    unittest.main()
