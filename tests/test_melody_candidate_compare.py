from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import compare_melody_candidates

from amt_core.events import NoteEvent, write_jsonl

CANONICAL_AUDIO_BYTES = b"canonical-audio-fixture"
VOCALS_AUDIO_BYTES = b"separator-vocals-fixture"


def _event(
    run_id: str,
    index: int,
    *,
    pitch: float,
    onset: float,
    offset: float,
    source_model: str = "fixture/model@revision",
    instrument: str | None = "voice",
    confidence: float | None = None,
    is_main_melody_candidate: bool = True,
) -> NoteEvent:
    return NoteEvent(
        event_id=f"{run_id}:{index}",
        track_id="voice",
        instrument=instrument,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        confidence=confidence,
        source_run_id=run_id,
        source_model=source_model,
        is_main_melody_candidate=is_main_melody_candidate,
    )


def _write_project(
    root: Path,
    *,
    project_dir_name: str,
    project_id: str,
    canonical_audio_bytes: bytes,
) -> tuple[Path, Path, str]:
    project_dir = root / project_dir_name
    canonical_path = project_dir / "audio" / "canonical" / "mix.flac"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_bytes(canonical_audio_bytes)
    canonical_sha256 = compare_melody_candidates.sha256_file(canonical_path)
    project_manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "canonical_audio": {
            "path": "audio/canonical/mix.flac",
            "sha256": canonical_sha256,
        },
    }
    (project_dir / "manifest.json").write_text(
        json.dumps(project_manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return project_dir, canonical_path, canonical_sha256


def _write_separator_parent(
    project_dir: Path,
    *,
    project_id: str,
    canonical_path: Path,
    canonical_sha256: str,
    parent_run_id: str,
) -> tuple[Path, Path, str]:
    parent_dir = project_dir / "runs" / parent_run_id
    stem_path = parent_dir / "raw" / "stems" / "vocals.flac"
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    stem_path.write_bytes(VOCALS_AUDIO_BYTES)
    stem_sha256 = compare_melody_candidates.sha256_file(stem_path)
    parent_manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "run_id": parent_run_id,
        "worker": "separator",
        "status": "succeeded",
        "inputs": [
            {
                "path": str(canonical_path),
                "sha256": canonical_sha256,
            }
        ],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": stem_sha256,
                "size_bytes": stem_path.stat().st_size,
            }
        ],
    }
    parent_manifest_path = parent_dir / "run_manifest.json"
    parent_manifest_path.write_text(
        json.dumps(parent_manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return parent_manifest_path, stem_path, stem_sha256


def _write_run(
    root: Path,
    *,
    run_id: str,
    events: list[NoteEvent],
    status: str = "succeeded",
    project_dir_name: str = "项目 空格",
    project_id: str = "fixture-project",
    canonical_audio_bytes: bytes = CANONICAL_AUDIO_BYTES,
    lineage_kind: str = "direct_canonical_mix",
    parent_run_id: str = "separator-parent",
) -> Path:
    project_dir, canonical_path, canonical_sha256 = _write_project(
        root,
        project_dir_name=project_dir_name,
        project_id=project_id,
        canonical_audio_bytes=canonical_audio_bytes,
    )
    if lineage_kind == "direct_canonical_mix":
        input_path = canonical_path
        input_sha256 = canonical_sha256
        input_lineage = {
            "kind": "direct_canonical_mix",
            "canonical_mix_path": str(canonical_path),
            "canonical_mix_sha256": canonical_sha256,
        }
    elif lineage_kind in {"separator_stem", "separator_vocal_stem"}:
        parent_manifest_path, stem_path, stem_sha256 = _write_separator_parent(
            project_dir,
            project_id=project_id,
            canonical_path=canonical_path,
            canonical_sha256=canonical_sha256,
            parent_run_id=parent_run_id,
        )
        input_path = stem_path
        input_sha256 = stem_sha256
        input_lineage = {
            "kind": lineage_kind,
            "canonical_mix_path": str(canonical_path),
            "canonical_mix_sha256": canonical_sha256,
            "parent_separator_run_id": parent_run_id,
            "parent_manifest_path": str(parent_manifest_path),
            "parent_manifest_sha256": compare_melody_candidates.sha256_file(parent_manifest_path),
            "parent_output_path": "raw/stems/vocals.flac",
            "parent_stem_name": "vocals",
            "parent_stem_sha256": stem_sha256,
        }
    else:
        raise ValueError(f"Unsupported fixture lineage kind: {lineage_kind}")

    run_dir = project_dir / "runs" / run_id
    events_path = run_dir / "normalized" / "events.jsonl"
    write_jsonl(events_path, events)
    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "run_id": run_id,
        "worker": "fixture-worker",
        "model": "fixture-model",
        "status": status,
        "input_lineage": input_lineage,
        "inputs": [
            {
                "path": str(input_path),
                "sha256": input_sha256,
            }
        ],
        "outputs": [
            {
                "path": compare_melody_candidates.EVENTS_RELATIVE_PATH,
                "sha256": compare_melody_candidates.sha256_file(events_path),
                "size_bytes": events_path.stat().st_size,
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return run_dir


class MelodyCandidateComparisonTests(unittest.TestCase):
    def test_unicode_paths_statistics_and_atomic_cli_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a_id = "candidate-a"
            run_b_id = "candidate-b"
            run_a = _write_run(
                root,
                run_id=run_a_id,
                events=[
                    _event(run_a_id, 0, pitch=60.0, onset=0.0, offset=0.5),
                    _event(run_a_id, 1, pitch=72.0, onset=0.4, offset=0.8),
                    _event(run_a_id, 2, pitch=84.0, onset=2.0, offset=2.1),
                ],
            )
            run_b = _write_run(
                root,
                run_id=run_b_id,
                events=[
                    _event(run_b_id, 0, pitch=48.0, onset=0.0, offset=0.4),
                    _event(run_b_id, 1, pitch=50.0, onset=1.5, offset=2.0),
                ],
            )

            report_path = root / "报告 目录" / "旋律比较.json"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = compare_melody_candidates.main(
                    [
                        "--run",
                        f"vocal_a={run_a}",
                        "--run",
                        f"direct={run_b}",
                        "--output",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(report_path.is_file())
            self.assertFalse(list(report_path.parent.glob(f".{report_path.name}.*")))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["claims"]["accuracy_claimed"])
            self.assertFalse(report["claims"]["human_reference_annotations_used"])
            self.assertFalse(report["claims"]["preferred_candidate_selected"])
            self.assertEqual(
                report["lineage_validation"]["project_id"],
                "fixture-project",
            )
            self.assertTrue(report["lineage_validation"]["all_candidates_share_project_identity"])
            self.assertTrue(report["lineage_validation"]["all_candidates_share_canonical_mix"])

            candidate = report["candidates"]["vocal_a"]
            self.assertIn("项目 空格", candidate["run_dir"])
            self.assertEqual(
                candidate["input_lineage"]["kind"],
                "direct_canonical_mix",
            )
            self.assertTrue(candidate["input_lineage"]["verified"])
            self.assertTrue(candidate["canonical_events"]["run_id_verified"])
            self.assertEqual(candidate["canonical_events"]["source_model_count"], 1)
            stats = candidate["statistics"]
            self.assertEqual(stats["event_count"], 3)
            self.assertEqual(stats["pitch_midi"]["minimum"], 60.0)
            self.assertEqual(stats["pitch_midi"]["median"], 72.0)
            self.assertEqual(stats["pitch_midi"]["maximum"], 84.0)
            self.assertEqual(stats["pitch_midi"]["span_semitones"], 24.0)
            self.assertEqual(stats["note_duration_sec"]["median"], 0.4)
            self.assertEqual(stats["adjacent_onset_gap_sec"]["median"], 1.0)
            self.assertEqual(stats["phrase_gap"]["threshold_sec"], 1.0)
            self.assertEqual(stats["phrase_gap"]["count"], 1)
            self.assertEqual(
                stats["overlap"]["events_starting_during_prior_note_count"],
                1,
            )
            self.assertAlmostEqual(stats["polyphony"]["active_time_rate"], 1.0 / 9.0)
            self.assertEqual(
                stats["register"]["octave_counts"],
                {"4": 1, "5": 1, "6": 1},
            )
            self.assertEqual(
                stats["register"]["register_bands"]["middle"]["count"],
                1,
            )
            self.assertEqual(
                stats["register"]["register_bands"]["upper_middle"]["count"],
                1,
            )
            self.assertEqual(
                stats["register"]["register_bands"]["high"]["count"],
                1,
            )
            self.assertEqual(
                report["failure_taxonomy_draft"]["status"],
                "heuristic_review_only",
            )
            self.assertEqual(
                report["complementarity_draft"]["status"],
                "structural_signals_only",
            )
            self.assertIn(
                "octave_coverage_difference",
                {
                    signal["signal"]
                    for signal in report["complementarity_draft"]["pairs"][0]["signals"]
                },
            )

    def test_rejects_invalid_and_duplicate_labels_or_paths(self) -> None:
        with self.assertRaisesRegex(
            compare_melody_candidates.MelodyComparisonError,
            "expected LABEL=RUN_DIR",
        ):
            compare_melody_candidates.parse_named_runs(["missing-separator"])

        with self.assertRaisesRegex(
            compare_melody_candidates.MelodyComparisonError,
            "Candidate labels",
        ):
            compare_melody_candidates.parse_named_runs(["../escape=/tmp/one", "safe=/tmp/two"])

        with self.assertRaisesRegex(
            compare_melody_candidates.MelodyComparisonError,
            "Duplicate candidate label",
        ):
            compare_melody_candidates.parse_named_runs(["Vocal=/tmp/one", "vocal=/tmp/two"])

        with self.assertRaisesRegex(
            compare_melody_candidates.MelodyComparisonError,
            "run directories must be distinct",
        ):
            compare_melody_candidates.parse_named_runs(["one=/tmp/same", "two=/tmp/same"])

    def test_rejects_missing_run_and_tampered_events_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a_id = "candidate-a"
            run_b_id = "candidate-b"
            run_a = _write_run(
                root,
                run_id=run_a_id,
                events=[_event(run_a_id, 0, pitch=60.0, onset=0.0, offset=0.5)],
            )
            run_b = _write_run(
                root,
                run_id=run_b_id,
                events=[_event(run_b_id, 0, pitch=62.0, onset=0.0, offset=0.5)],
            )

            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "run directory is missing or unsafe",
            ):
                compare_melody_candidates.compare_candidates(
                    {"a": run_a, "missing": root / "不存在"}
                )

            events_path = run_b / "normalized" / "events.jsonl"
            original_events = events_path.read_bytes()
            events_path.write_text(
                original_events.decode("utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "size mismatch",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "b": run_b})

            same_size_tamper = original_events.replace(b"62.0", b"63.0", 1)
            self.assertNotEqual(same_size_tamper, original_events)
            self.assertEqual(len(same_size_tamper), len(original_events))
            events_path.write_bytes(same_size_tamper)
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "SHA-256 mismatch",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "b": run_b})

    def test_rejects_manifest_run_id_and_event_source_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a_id = "candidate-a"
            run_b_id = "candidate-b"
            run_a = _write_run(
                root,
                run_id=run_a_id,
                events=[_event(run_a_id, 0, pitch=60.0, onset=0.0, offset=0.5)],
            )
            run_b = _write_run(
                root,
                run_id=run_b_id,
                events=[_event(run_b_id, 0, pitch=62.0, onset=0.0, offset=0.5)],
            )

            manifest_path = run_b / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["run_id"] = "another-run"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "run_id does not match",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "b": run_b})

            run_c_id = "candidate-c"
            run_c = _write_run(
                root,
                run_id=run_c_id,
                events=[
                    _event(
                        "wrong-source-run",
                        0,
                        pitch=64.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
            )
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "source_run_id values from another run",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "c": run_c})

    def test_accepts_verified_separator_vocal_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct_id = "direct-run"
            separator_stem_id = "separator-stem-run"
            separator_vocal_id = "separator-vocal-run"
            direct = _write_run(
                root,
                run_id=direct_id,
                events=[
                    _event(
                        direct_id,
                        0,
                        pitch=60.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
            )
            separator_stem = _write_run(
                root,
                run_id=separator_stem_id,
                events=[
                    _event(
                        separator_stem_id,
                        0,
                        pitch=62.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
                lineage_kind="separator_stem",
            )
            separator_vocal = _write_run(
                root,
                run_id=separator_vocal_id,
                events=[
                    _event(
                        separator_vocal_id,
                        0,
                        pitch=64.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
                lineage_kind="separator_vocal_stem",
            )

            report = compare_melody_candidates.compare_candidates(
                {
                    "direct": direct,
                    "legacy_separator": separator_stem,
                    "vocal_separator": separator_vocal,
                }
            )

            self.assertEqual(
                report["candidates"]["legacy_separator"]["input_lineage"]["kind"],
                "separator_stem",
            )
            vocal_lineage = report["candidates"]["vocal_separator"]["input_lineage"]
            self.assertEqual(vocal_lineage["kind"], "separator_vocal_stem")
            self.assertEqual(vocal_lineage["parent_stem_name"], "vocals")
            self.assertTrue(vocal_lineage["verified"])

    def test_rejects_missing_or_ambiguous_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a_id = "candidate-a"
            run_b_id = "candidate-b"
            run_a = _write_run(
                root,
                run_id=run_a_id,
                events=[_event(run_a_id, 0, pitch=60.0, onset=0.0, offset=0.5)],
            )
            run_b = _write_run(
                root,
                run_id=run_b_id,
                events=[_event(run_b_id, 0, pitch=62.0, onset=0.0, offset=0.5)],
            )
            manifest_path = run_b / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["input_lineage"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "no unambiguous input_lineage",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "b": run_b})

            run_c_id = "candidate-c"
            run_c = _write_run(
                root,
                run_id=run_c_id,
                events=[_event(run_c_id, 0, pitch=64.0, onset=0.0, offset=0.5)],
            )
            manifest_path = run_c / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["inputs"].append(dict(manifest["inputs"][0]))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "exactly one unambiguous audio input",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "c": run_c})

    def test_rejects_cross_project_or_cross_song_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a_id = "candidate-a"
            run_b_id = "candidate-b"
            run_a = _write_run(
                root,
                run_id=run_a_id,
                events=[_event(run_a_id, 0, pitch=60.0, onset=0.0, offset=0.5)],
                project_dir_name="project-a",
                project_id="project-a",
            )
            run_b = _write_run(
                root,
                run_id=run_b_id,
                events=[_event(run_b_id, 0, pitch=62.0, onset=0.0, offset=0.5)],
                project_dir_name="project-b",
                project_id="project-b",
            )
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "one project identity",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "b": run_b})

            run_c_id = "candidate-c"
            run_c = _write_run(
                root,
                run_id=run_c_id,
                events=[_event(run_c_id, 0, pitch=64.0, onset=0.0, offset=0.5)],
                project_dir_name="project-c",
                project_id="project-a",
                canonical_audio_bytes=b"a-different-song",
            )
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "one canonical mix SHA-256",
            ):
                compare_melody_candidates.compare_candidates({"a": run_a, "c": run_c})

    def test_rejects_tampered_separator_parent_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct_id = "direct-run"
            stem_id = "stem-run"
            direct = _write_run(
                root,
                run_id=direct_id,
                events=[_event(direct_id, 0, pitch=60.0, onset=0.0, offset=0.5)],
            )
            stem = _write_run(
                root,
                run_id=stem_id,
                events=[_event(stem_id, 0, pitch=62.0, onset=0.0, offset=0.5)],
                lineage_kind="separator_vocal_stem",
            )
            parent_manifest_path = stem.parent / "separator-parent" / "run_manifest.json"
            parent = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
            parent["project_id"] = "another-project"
            parent_manifest_path.write_text(json.dumps(parent), encoding="utf-8")

            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "parent separator manifest SHA-256 has changed",
            ):
                compare_melody_candidates.compare_candidates({"direct": direct, "stem": stem})

    def test_rejects_non_finite_event_values_before_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_id = "baseline-run"
            baseline = _write_run(
                root,
                run_id=baseline_id,
                events=[
                    _event(
                        baseline_id,
                        0,
                        pitch=60.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
            )
            for index, field in enumerate(("onset_sec", "offset_sec", "pitch_midi", "confidence")):
                with self.subTest(field=field):
                    candidate_id = f"non-finite-{index}"
                    candidate = _write_run(
                        root,
                        run_id=candidate_id,
                        events=[
                            _event(
                                candidate_id,
                                0,
                                pitch=62.0,
                                onset=0.0,
                                offset=0.5,
                            )
                        ],
                    )
                    events_path = candidate / "normalized" / "events.jsonl"
                    payload = json.loads(events_path.read_text(encoding="utf-8"))
                    payload[field] = float("nan")
                    events_path.write_text(
                        json.dumps(payload, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    manifest_path = candidate / "run_manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    output = manifest["outputs"][0]
                    output["sha256"] = compare_melody_candidates.sha256_file(events_path)
                    output["size_bytes"] = events_path.stat().st_size
                    manifest_path.write_text(
                        json.dumps(manifest),
                        encoding="utf-8",
                    )

                    with self.assertRaises(
                        compare_melody_candidates.MelodyComparisonError
                    ) as raised:
                        compare_melody_candidates.compare_candidates(
                            {"baseline": baseline, "candidate": candidate}
                        )
                    message = str(raised.exception)
                    self.assertTrue(
                        f"non-finite {field}" in message
                        or "canonical events are invalid" in message
                    )

    def test_rejects_non_voice_but_allows_unflagged_voice_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_id = "baseline-run"
            baseline = _write_run(
                root,
                run_id=baseline_id,
                events=[
                    _event(
                        baseline_id,
                        0,
                        pitch=60.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
            )
            multi_instrument_id = "multi-instrument-run"
            multi_instrument = _write_run(
                root,
                run_id=multi_instrument_id,
                events=[
                    _event(
                        multi_instrument_id,
                        0,
                        pitch=62.0,
                        onset=0.0,
                        offset=0.5,
                    ),
                    _event(
                        multi_instrument_id,
                        1,
                        pitch=48.0,
                        onset=0.0,
                        offset=0.5,
                        instrument="piano",
                    ),
                ],
            )
            with self.assertRaisesRegex(
                compare_melody_candidates.MelodyComparisonError,
                "not entirely voice-scoped",
            ):
                compare_melody_candidates.compare_candidates(
                    {"baseline": baseline, "candidate": multi_instrument}
                )

            non_melody_id = "non-melody-run"
            non_melody = _write_run(
                root,
                run_id=non_melody_id,
                events=[
                    _event(
                        non_melody_id,
                        0,
                        pitch=62.0,
                        onset=0.0,
                        offset=0.5,
                        is_main_melody_candidate=False,
                    )
                ],
            )
            report = compare_melody_candidates.compare_candidates(
                {"baseline": baseline, "candidate": non_melody}
            )
            self.assertEqual(
                report["candidates"]["candidate"]["statistics"]["event_count"],
                1,
            )

    def test_empty_candidate_is_reported_as_a_review_failure_not_accuracy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = _write_run(root, run_id="empty-run", events=[])
            populated_id = "populated-run"
            populated = _write_run(
                root,
                run_id=populated_id,
                events=[
                    _event(
                        populated_id,
                        0,
                        pitch=60.0,
                        onset=0.0,
                        offset=0.5,
                    )
                ],
            )

            report = compare_melody_candidates.compare_candidates(
                {"empty": empty, "populated": populated}
            )
            empty_failure = report["failure_taxonomy_draft"]["candidates"]["empty"]
            self.assertEqual(empty_failure["classification"], "review_flags_present")
            self.assertEqual(empty_failure["flags"][0]["category"], "empty_output")
            self.assertFalse(report["claims"]["accuracy_claimed"])


if __name__ == "__main__":
    unittest.main()
