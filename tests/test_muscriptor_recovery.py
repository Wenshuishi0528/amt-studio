from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.recover_muscriptor_normalization import recover

from amt_core.events import read_jsonl
from amt_core.utils import sha256_file


class MuScriptorRecoveryTests(unittest.TestCase):
    def _project_with_failed_run(self, root: Path) -> tuple[Path, Path]:
        project = root / "project 日本語"
        canonical = project / "audio" / "canonical" / "mix.flac"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"canonical audio")
        source = project / "runs" / "failed-native"
        raw = source / "raw"
        raw.mkdir(parents=True)
        native = raw / "events.native.jsonl"
        native.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "start",
                            "pitch": 66,
                            "start_time": 1.0,
                            "index": 4,
                            "instrument": "voice",
                        }
                    ),
                    json.dumps(
                        {"type": "end", "end_time": 1.0, "start_event_index": 4}
                    ),
                    json.dumps(
                        {
                            "type": "start",
                            "pitch": 67,
                            "start_time": 2.0,
                            "index": 5,
                            "instrument": "voice",
                        }
                    ),
                    json.dumps(
                        {"type": "end", "end_time": 2.5, "start_event_index": 5}
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        midi = raw / "full.native.mid"
        midi.write_bytes(b"MThdFAKE")
        manifest = {
            "schema_version": 1,
            "run_id": "failed-native",
            "project_id": project.name,
            "worker": "muscriptor",
            "model": "large",
            "status": "failed",
            "error": {
                "type": "EventValidationError",
                "message": "offset_sec must be greater than onset_sec",
            },
            "inputs": [{"path": "/remote/mix.flac", "sha256": sha256_file(canonical)}],
            "outputs": [
                {
                    "path": "raw/events.native.jsonl",
                    "sha256": sha256_file(native),
                    "size_bytes": native.stat().st_size,
                },
                {
                    "path": "raw/full.native.mid",
                    "sha256": sha256_file(midi),
                    "size_bytes": midi.stat().st_size,
                },
            ],
            "timings": {
                "jsonl": {"exit_code": 0, "wall_time_sec": 10.0},
                "midi": {"exit_code": 0, "wall_time_sec": 9.0},
            },
            "decoding": {"skip_midi": False, "beam_size": 4},
            "environment": {"hostname": "hyak-node"},
            "model_provenance": {
                "repository": "MuScriptor/muscriptor-large",
                "revision": "fixed-revision",
            },
            "reproducibility": {"sampling": False},
        }
        (source / "run_manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        return project, source

    def test_recovers_without_rerunning_inference_and_records_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self._project_with_failed_run(Path(temporary))
            recovered = recover(
                project,
                source_run_id="failed-native",
                run_id="recovered-native",
            )
            manifest = json.loads(
                (recovered / "run_manifest.json").read_text(encoding="utf-8")
            )
            events = read_jsonl(recovered / "normalized" / "events.jsonl")
            rejected = json.loads(
                (recovered / "normalized" / "rejected_events.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(manifest["status"], "succeeded")
            self.assertTrue(manifest["recovery"]["inference_reused"])
            self.assertEqual(manifest["recovery"]["source_run_id"], "failed-native")
            self.assertEqual(len(events), 1)
            self.assertEqual(rejected["rejected_event_count"], 1)
            self.assertEqual(
                manifest["metrics"]["descriptive_event_summary"]["rejected_events"]["path"],
                "normalized/rejected_events.json",
            )
            self.assertEqual(
                sha256_file(recovered / "raw" / "events.native.jsonl"),
                sha256_file(source / "raw" / "events.native.jsonl"),
            )
            self.assertEqual(
                manifest["inputs"][0]["path"],
                str(project.resolve() / "audio" / "canonical" / "mix.flac"),
            )

    def test_refuses_tampered_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self._project_with_failed_run(Path(temporary))
            (source / "raw" / "events.native.jsonl").write_text(
                "{}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "size does not match"):
                recover(
                    project,
                    source_run_id="failed-native",
                    run_id="recovered-native",
                )
            self.assertFalse((project / "runs" / "recovered-native").exists())

    def test_recovers_separator_stem_and_preserves_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, source = self._project_with_failed_run(Path(temporary))
            canonical = project / "audio" / "canonical" / "mix.flac"
            parent = project / "runs" / "separator-a"
            stem = parent / "raw" / "stems" / "vocals.flac"
            stem.parent.mkdir(parents=True)
            stem.write_bytes(b"separated vocals")
            parent_manifest = {
                "schema_version": 1,
                "run_id": "separator-a",
                "project_id": project.name,
                "worker": "separator",
                "status": "succeeded",
                "preset": "fixture-separator",
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
            }
            parent_manifest_path = parent / "run_manifest.json"
            parent_manifest_path.write_text(
                json.dumps(parent_manifest),
                encoding="utf-8",
            )
            source_manifest_path = source / "run_manifest.json"
            source_manifest = json.loads(
                source_manifest_path.read_text(encoding="utf-8")
            )
            source_manifest["inputs"] = [
                {
                    "path": "/remote/project/runs/separator-a/raw/stems/vocals.flac",
                    "sha256": sha256_file(stem),
                }
            ]
            source_manifest["input_lineage"] = {
                "kind": "separator_stem",
                "canonical_mix_path": "/remote/project/audio/canonical/mix.flac",
                "canonical_mix_sha256": sha256_file(canonical),
                "parent_separator_run_id": "separator-a",
                "parent_separator_preset": "fixture-separator",
                "parent_manifest_path": "/remote/project/runs/separator-a/run_manifest.json",
                "parent_manifest_sha256": sha256_file(parent_manifest_path),
                "parent_output_path": "raw/stems/vocals.flac",
                "parent_stem_name": "vocals",
                "parent_stem_sha256": sha256_file(stem),
                "timeline": {
                    "mix_duration_sec": 10.0,
                    "stem_duration_sec": 10.0,
                    "stem_duration_drift_sec": 0.0,
                },
            }
            source_manifest_path.write_text(
                json.dumps(source_manifest),
                encoding="utf-8",
            )

            recovered = recover(
                project,
                source_run_id="failed-native",
                run_id="recovered-stem",
            )
            manifest = json.loads(
                (recovered / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["inputs"][0]["path"], str(stem.resolve()))
            self.assertEqual(
                manifest["input_lineage"]["kind"],
                "separator_stem",
            )
            self.assertEqual(
                manifest["input_lineage"]["parent_stem_sha256"],
                sha256_file(stem),
            )
            self.assertEqual(
                manifest["input_lineage"]["parent_manifest_path"],
                str(parent_manifest_path.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
