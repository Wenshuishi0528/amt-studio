from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amt_core.contracts import (
    ArtifactRecord,
    ContractValidationError,
    WorkerRequestV1,
    load_worker_request,
    load_worker_result,
)
from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json, sha256_file


def _record(path: Path, run_dir: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(run_dir)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _write_note_run(project: Path, worker: str, run_id: str) -> Path:
    run_dir = project / "runs" / run_id
    events_path = run_dir / "normalized" / "events.jsonl"
    write_jsonl(
        events_path,
        [
            NoteEvent(
                event_id=f"{run_id}-event",
                track_id="voice",
                instrument="voice",
                onset_sec=0.1,
                offset_sec=0.5,
                pitch_midi=69.0,
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
            "status": "succeeded",
            "outputs": [_record(events_path, run_dir)],
        },
    )
    return run_dir


class WorkerContractTests(unittest.TestCase):
    def test_request_round_trip_with_unicode_input(self) -> None:
        request = WorkerRequestV1(
            request_id="beat-request",
            run_id="beat-run",
            project_id="project",
            worker="beat_this",
            created_at="2026-07-24T00:00:00+00:00",
            input=ArtifactRecord(
                path="/tmp/音楽 mix.flac",
                sha256="a" * 64,
                size_bytes=123,
            ),
            configuration={"checkpoint": "final0", "dbn": False},
            requested_outputs=(
                "raw/native/mix.beats",
                "normalized/rhythm.json",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            request.write(path)
            loaded = load_worker_request(path)
            self.assertEqual(loaded, request)

            malformed = request.to_dict()
            malformed["requested_outputs"] = "normalized/events.jsonl"
            with self.assertRaisesRegex(
                ContractValidationError,
                "requested_outputs must be an array",
            ):
                WorkerRequestV1.from_dict(malformed)

    def test_all_note_baselines_load_through_one_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            for worker in ("muscriptor", "game", "basic_pitch"):
                result = load_worker_result(_write_note_run(project, worker, f"{worker}-run"))
                events = result.read_note_events()
                self.assertEqual(result.worker, worker)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].source_run_id, f"{worker}-run")

    def test_result_rejects_tampering_and_symlink_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            run_dir = _write_note_run(project, "game", "game-run")
            events_path = run_dir / "normalized" / "events.jsonl"
            events_path.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractValidationError, "size mismatch"):
                load_worker_result(run_dir)

            outside = Path(temporary) / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            events_path.unlink()
            events_path.symlink_to(outside)
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            manifest["outputs"] = [_record(outside, Path(temporary))]
            manifest["outputs"][0]["path"] = "normalized/events.jsonl"
            atomic_write_json(run_dir / "run_manifest.json", manifest)
            with self.assertRaisesRegex(ContractValidationError, "symbolic link"):
                load_worker_result(run_dir)

    def test_non_note_worker_refuses_note_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            run_dir = project / "runs" / "separator-run"
            output = run_dir / "raw" / "stems" / "vocals.flac"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"fake")
            atomic_write_json(
                run_dir / "run_manifest.json",
                {
                    "schema_version": 1,
                    "run_id": run_dir.name,
                    "project_id": project.name,
                    "worker": "separator",
                    "status": "succeeded",
                    "outputs": [_record(output, run_dir)],
                },
            )
            result = load_worker_result(run_dir)
            with self.assertRaisesRegex(ContractValidationError, "does not emit note"):
                result.read_note_events()


if __name__ == "__main__":
    unittest.main()
