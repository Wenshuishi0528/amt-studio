from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from scripts.calibrate_fusion import CalibrationRunError, calibrate
from scripts.run_fusion import create_fusion_run

from amt_core.benchmark import canonical_json_sha256
from amt_core.events import NoteEvent, write_jsonl
from amt_core.fusion import FusionConfig
from amt_core.utils import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path, run_dir: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(run_dir)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


class FusionCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "development-project"
        canonical = self.project / "audio" / "canonical" / "mix.flac"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"development-audio")
        self.canonical_sha = sha256_file(canonical)
        _write_json(
            self.project / "manifest.json",
            {
                "schema_version": 1,
                "project_id": "development-project",
                "canonical_audio": {"sha256": self.canonical_sha},
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _candidate(
        self,
        run_id: str,
        worker: str,
        pitches: tuple[float, float],
    ) -> Path:
        run_dir = self.project / "runs" / run_id
        events_path = run_dir / "normalized" / "events.jsonl"
        events = [
            NoteEvent(
                event_id=f"{run_id}:outside",
                track_id=f"{run_id}:voice",
                onset_sec=0.1,
                offset_sec=0.4,
                pitch_midi=55,
                source_run_id=run_id,
                source_model="fixture",
                instrument="voice",
                is_main_melody_candidate=True,
            )
        ]
        events.extend(
            [
                NoteEvent(
                    event_id=f"{run_id}:{index}",
                    track_id=f"{run_id}:voice",
                    onset_sec=onset,
                    offset_sec=onset + 0.4,
                    pitch_midi=pitch,
                    source_run_id=run_id,
                    source_model="fixture",
                    instrument="voice",
                    is_main_melody_candidate=True,
                )
                for index, (onset, pitch) in enumerate(zip((1.1, 2.1), pitches, strict=True))
            ]
        )
        write_jsonl(events_path, events)
        summary = run_dir / "normalized" / "summary.json"
        _write_json(summary, {"count": len(events)})
        _write_json(
            run_dir / "run_manifest.json",
            {
                "schema_version": 1,
                "contract_version": "amt-worker-result/v1",
                "status": "succeeded",
                "run_id": run_id,
                "project_id": "development-project",
                "worker": worker,
                "input_lineage": {
                    "canonical_mix_sha256": self.canonical_sha,
                },
                "outputs": [
                    _artifact(events_path, run_dir),
                    _artifact(summary, run_dir),
                ],
            },
        )
        return run_dir

    def _benchmark(self, *, split: str = "development") -> Path:
        references = {}
        for annotator, pitches in {
            "a1": (60.0, 62.0),
            "a2": (60.0, 62.0),
        }.items():
            path = self.root / f"{annotator}.csv"
            rows = [
                f"{local_onset},{440 * 2 ** ((pitch - 69) / 12)},{0.4}\n"
                for local_onset, pitch in zip((0.1, 1.1), pitches, strict=True)
            ]
            path.write_text("".join(rows), encoding="utf-8")
            references[annotator] = {
                "path": str(path),
                "sha256": sha256_file(path),
                "note_count": 2,
            }
        freeze = {
            "schema": "amt-external-note-benchmark-manifest/v1",
            "benchmark_id": "fixture-development",
            "project_id": "development-project",
            "split": split,
            "prior_system_exposure": split == "development",
            "canonical_audio_sha256": self.canonical_sha,
            "excerpts": [
                {
                    "excerpt_id": "dev-01",
                    "evaluation_start_sec": 1.0,
                    "evaluation_end_sec": 3.0,
                    "duration_sec": 2.0,
                    "note_references": references,
                }
            ],
        }
        benchmark = self.root / "benchmark.json"
        _write_json(
            benchmark,
            {
                "schema": "amt-benchmark-pack/v1",
                "freeze_payload": freeze,
                "benchmark_freeze_sha256": canonical_json_sha256(freeze),
            },
        )
        return benchmark

    def _metadata_and_config(self) -> tuple[Path, Path]:
        metadata = self.root / "sources.json"
        config = self.root / "config.json"
        _write_json(
            metadata,
            {
                "schema": "amt-fusion-source-metadata/v1",
                "sources": [
                    {
                        "label": "game",
                        "stem_quality": 1.0,
                        "instrument_presence": 1.0,
                    },
                    {
                        "label": "basic",
                        "stem_quality": 1.0,
                        "instrument_presence": 1.0,
                    },
                ],
            },
        )
        _write_json(
            config,
            {
                "schema": "amt-fusion-config/v1",
                "config": FusionConfig().to_dict(),
            },
        )
        return metadata, config

    def test_calibration_uses_development_and_freezes_outputs(self) -> None:
        game = self._candidate("game-run", "game", (60.0, 62.0))
        basic = self._candidate("basic-run", "basic_pitch", (60.0, 65.0))
        metadata, config = self._metadata_and_config()
        output = self.root / "calibration"
        manifest = calibrate(
            self._benchmark(),
            [("game", game), ("basic", basic)],
            metadata,
            config,
            output,
            calibration_id="fixture-development-v1",
        )
        self.assertEqual(manifest["status"], "succeeded")
        self.assertFalse(manifest["claims"]["blind_data_used_for_tuning"])
        calibration = json.loads((output / "calibration.json").read_text())
        self.assertEqual(calibration["provenance"]["split"], "development")
        report = json.loads((output / "development_report.json").read_text())
        self.assertEqual(report["strongest_baseline"]["label"], "game")
        self.assertEqual(len(report["threshold_trials"]), 41)
        self.assertTrue(math.isfinite(report["selected_threshold"]))
        self.assertEqual(report["cluster_count"], 4)
        self.assertEqual(report["calibration_cluster_count"], 3)
        self.assertEqual(
            report["clusters_outside_evaluation_windows_excluded"],
            1,
        )
        self.assertEqual(
            report["baseline_reports"]["game"]["per_excerpt"][0]["chosen_annotator"],
            "a1",
        )

        fusion_output = self.project / "fusion" / "development-fusion"
        fusion_output.parent.mkdir()
        fusion_manifest = create_fusion_run(
            [("game", game), ("basic", basic)],
            output / "profiles.json",
            output / "config.json",
            fusion_output,
            run_id="development-fusion",
            calibration_path=output / "calibration.json",
        )
        self.assertTrue(fusion_manifest["claims"]["calibrated_confidence"])
        fused = json.loads((fusion_output / "events.jsonl").read_text().splitlines()[0])
        self.assertIsNotNone(fused["confidence"])

    def test_calibration_rejects_blind_manifest(self) -> None:
        game = self._candidate("game-run", "game", (60.0, 62.0))
        basic = self._candidate("basic-run", "basic_pitch", (60.0, 65.0))
        metadata, config = self._metadata_and_config()
        with self.assertRaisesRegex(CalibrationRunError, "freeze is invalid"):
            calibrate(
                self._benchmark(split="blind_test"),
                [("game", game), ("basic", basic)],
                metadata,
                config,
                self.root / "calibration",
                calibration_id="fixture-blind-invalid",
            )


if __name__ == "__main__":
    unittest.main()
