from __future__ import annotations

import json
import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path

from scripts import create_melody_review

from amt_core.events import NoteEvent, write_jsonl


def _event(
    run_id: str,
    index: int,
    *,
    onset: float,
    offset: float,
    pitch: float,
    instrument: str = "voice",
    is_main_melody_candidate: bool = True,
) -> NoteEvent:
    return NoteEvent(
        event_id=f"{run_id}:{index}",
        track_id=instrument,
        instrument=instrument,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        velocity=80,
        source_run_id=run_id,
        source_model=f"fixture/{run_id}",
        is_main_melody_candidate=is_main_melody_candidate,
    )


def _write_project(
    root: Path,
    *,
    project_id: str = "melody-project",
    mix_payload: bytes = b"RIFF-fixture-mix",
) -> tuple[Path, Path]:
    project_dir = root / project_id
    mix = project_dir / "audio" / "canonical" / "mix.flac"
    mix.parent.mkdir(parents=True)
    mix.write_bytes(mix_payload)
    project_manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "private": True,
        "canonical_audio": {
            "path": "audio/canonical/mix.flac",
            "sha256": create_melody_review.sha256_file(mix),
        },
    }
    (project_dir / "manifest.json").write_text(
        json.dumps(project_manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return project_dir, mix


def _write_separator(
    project_dir: Path,
    mix: Path,
    *,
    run_id: str = "selected-vocal-separator",
) -> tuple[Path, dict[str, object]]:
    run_dir = project_dir / "runs" / run_id
    stem = run_dir / "raw" / "stems" / "vocals.flac"
    stem.parent.mkdir(parents=True)
    stem.write_bytes(b"fLaC-fixture-vocal-stem")
    parent_manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "succeeded",
        "worker": "separator",
        "preset": "vocal-quality-a",
        "inputs": [
            {
                "path": str(mix),
                "sha256": create_melody_review.sha256_file(mix),
            }
        ],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": create_melody_review.sha256_file(stem),
                "size_bytes": stem.stat().st_size,
            }
        ],
    }
    parent_manifest_path = run_dir / "run_manifest.json"
    parent_manifest_path.write_text(
        json.dumps(parent_manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    lineage = {
        "kind": "separator_vocal_stem",
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_mix_path": str(mix),
        "canonical_mix_sha256": create_melody_review.sha256_file(mix),
        "parent_separator_run_id": run_id,
        "parent_separator_preset": "vocal-quality-a",
        "parent_manifest_path": str(parent_manifest_path),
        "parent_manifest_sha256": create_melody_review.sha256_file(parent_manifest_path),
        "parent_output_path": "raw/stems/vocals.flac",
        "parent_stem_name": "vocals",
        "parent_stem_sha256": create_melody_review.sha256_file(stem),
    }
    return stem, lineage


def _write_candidate(
    project_dir: Path,
    *,
    run_id: str,
    events: list[NoteEvent] | None = None,
    input_audio: Path | None = None,
    input_lineage: dict[str, object] | None = None,
    legacy_manifest: bool = False,
) -> Path:
    canonical_mix = project_dir / "audio" / "canonical" / "mix.flac"
    input_audio = input_audio or canonical_mix
    if input_lineage is None:
        input_lineage = {
            "kind": "direct_canonical_mix",
            "canonical_mix_path": str(canonical_mix),
            "canonical_mix_sha256": create_melody_review.sha256_file(canonical_mix),
        }
    run_dir = project_dir / "runs" / run_id
    events_path = run_dir / create_melody_review.EVENTS_RELATIVE_PATH
    write_jsonl(
        events_path,
        events
        or [
            _event(run_id, 0, onset=0.25, offset=1.0, pitch=60.2),
            _event(run_id, 1, onset=1.0, offset=1.5, pitch=62.8),
        ],
    )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "succeeded",
        "worker": "fixture-worker",
        "model": "fixture-model",
        "inputs": [
            {
                "path": str(input_audio),
                "sha256": create_melody_review.sha256_file(input_audio),
            }
        ],
        "outputs": [
            {
                "path": create_melody_review.EVENTS_RELATIVE_PATH,
                "sha256": create_melody_review.sha256_file(events_path),
                "size_bytes": events_path.stat().st_size,
            }
        ],
    }
    if not legacy_manifest:
        manifest["project_id"] = project_dir.name
        manifest["input_lineage"] = input_lineage
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return run_dir


def _write_fake_tool(
    path: Path,
    *,
    fail_render: bool = False,
    truncate_excerpt: bool = False,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    failure_code = "raise SystemExit(9)" if fail_render else ""
    path.write_text(
        f"""#!/usr/bin/env python3
import pathlib
import sys
import wave

args = sys.argv[1:]
if "--version" in args or "-version" in args:
    print("fixture tool 1.0")
    raise SystemExit(0)
if {fail_render!r}:
    {failure_code or "pass"}
if "-F" in args:
    destination = pathlib.Path(args[args.index("-F") + 1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"RIFF" + "工具输出".encode("utf-8"))
else:
    destination = pathlib.Path(args[-1])
    duration = float(args[args.index("-t") + 1])
    frame_count = max(0, round(duration * 44100) - (10 if {truncate_excerpt!r} else 0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\\x00\\x00\\x00\\x00" * frame_count)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fixture_inputs(root: Path) -> dict[str, object]:
    project_dir, mix = _write_project(root, project_id="项目-melody")
    stem, stem_lineage = _write_separator(project_dir, mix)
    soundfont = root / "音色库" / "钢琴.sf2"
    soundfont.parent.mkdir(parents=True)
    soundfont.write_bytes(b"fixture-soundfont")
    candidates = {
        "game": _write_candidate(
            project_dir,
            run_id="game-run",
            input_audio=stem,
            input_lineage=stem_lineage,
        ),
        "basic": _write_candidate(
            project_dir,
            run_id="basic-run",
            input_audio=stem,
            input_lineage=stem_lineage,
        ),
        # Task 002 predates explicit project_id/input_lineage fields. Its
        # canonical-mix SHA still provides a strict, portable legacy binding.
        "muscriptor": _write_candidate(
            project_dir,
            run_id="muscriptor-run",
            input_audio=mix,
            events=[
                _event(
                    "muscriptor-run",
                    0,
                    onset=0.25,
                    offset=1.0,
                    pitch=60.2,
                    is_main_melody_candidate=False,
                ),
                _event(
                    "muscriptor-run",
                    1,
                    onset=1.0,
                    offset=1.5,
                    pitch=62.8,
                    is_main_melody_candidate=False,
                ),
            ],
            legacy_manifest=True,
        ),
    }
    passages = {
        "opening": (0.0, 0.75),
        "verse": (1.25, 0.5),
        "chorus": (2.0, 1.0),
    }
    tools = root / "工具 空格"
    fluidsynth = _write_fake_tool(tools / "fake fluidsynth")
    ffmpeg = _write_fake_tool(tools / "fake ffmpeg")
    return {
        "project_dir": project_dir,
        "mix": mix,
        "soundfont": soundfont,
        "candidates": candidates,
        "passages": passages,
        "fluidsynth": fluidsynth,
        "ffmpeg": ffmpeg,
    }


def _read_variable_length(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = payload[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            return value, offset


def _parse_track_events(payload: bytes) -> list[tuple[int, bytes]]:
    assert payload[:4] == b"MThd"
    header_length, midi_format, track_count, division = struct.unpack(">IHHH", payload[4:14])
    assert (header_length, midi_format, track_count, division) == (6, 0, 1, 480)
    assert payload[14:18] == b"MTrk"
    track_length = struct.unpack(">I", payload[18:22])[0]
    track = payload[22 : 22 + track_length]

    parsed: list[tuple[int, bytes]] = []
    absolute_tick = 0
    offset = 0
    while offset < len(track):
        delta, offset = _read_variable_length(track, offset)
        absolute_tick += delta
        status = track[offset]
        offset += 1
        if status == 0xFF:
            meta_type = track[offset]
            offset += 1
            length, offset = _read_variable_length(track, offset)
            message = bytes((status, meta_type)) + track[offset : offset + length]
            offset += length
        elif status & 0xF0 == 0xC0:
            message = bytes((status, track[offset]))
            offset += 1
        else:
            message = bytes((status, track[offset], track[offset + 1]))
            offset += 2
        parsed.append((absolute_tick, message))
    return parsed


class MelodyReviewTests(unittest.TestCase):
    def test_builds_standard_midi_with_absolute_time_and_off_before_on(self) -> None:
        run_id = "ordering-run"
        events = [
            _event(run_id, 0, onset=0.5, offset=1.0, pitch=60.0),
            _event(run_id, 1, onset=1.0, offset=1.5, pitch=62.0),
        ]

        payload = create_melody_review.build_standard_midi(
            events,
            minimum_duration_sec=2.0,
        )
        parsed = _parse_track_events(payload)

        self.assertIn((0, b"\xff\x51\x07\xa1\x20"), parsed)
        self.assertIn((0, b"\xc0\x00"), parsed)
        self.assertIn((480, b"\x90\x3c\x50"), parsed)
        shared_tick = [message for tick, message in parsed if tick == 960]
        self.assertEqual(shared_tick, [b"\x80\x3c\x00", b"\x90\x3e\x50"])
        self.assertEqual(parsed[-1], (1920, b"\xff\x2f"))

    def test_unicode_paths_create_atomic_hashed_review_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "日本語 project"
            inputs = _fixture_inputs(root)
            output = root / "试听 输出"
            original_mix = Path(inputs["mix"]).read_bytes()
            original_soundfont = Path(inputs["soundfont"]).read_bytes()

            result = create_melody_review.create_review(
                mix=inputs["mix"],
                candidates=inputs["candidates"],
                passages=inputs["passages"],
                soundfont=inputs["soundfont"],
                output=output,
                fluidsynth=inputs["fluidsynth"],
                ffmpeg=inputs["ffmpeg"],
            )

            self.assertEqual(result["status"], "awaiting_human_review")
            self.assertFalse(result["task005_export"])
            self.assertFalse(result["accuracy_claimed"])
            self.assertTrue(result["human_review_pending"])
            self.assertTrue(
                result["timeline_binding"]["all_candidates_share_project_and_canonical_mix"]
            )
            self.assertTrue((output / "review_manifest.json").is_file())
            self.assertFalse(list(output.parent.glob(f".{output.name}.tmp-*")))
            self.assertEqual(Path(inputs["mix"]).read_bytes(), original_mix)
            self.assertEqual(Path(inputs["soundfont"]).read_bytes(), original_soundfont)

            persisted = json.loads((output / "review_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(persisted["candidates"]), {"game", "basic", "muscriptor"})
            for candidate in persisted["candidates"].values():
                self.assertTrue(candidate["canonical_events"]["run_id_verified"])
                self.assertTrue(candidate["canonical_events"]["source_run_id_verified"])
                self.assertTrue(candidate["canonical_events"]["voice_scope_verified"])
                self.assertEqual(candidate["canonical_events"]["event_count"], 2)
                self.assertTrue((output / candidate["preview"]["midi"]["path"]).is_file())
                self.assertTrue((output / candidate["preview"]["full_piano_wav"]["path"]).is_file())

            self.assertEqual(len(persisted["passages"]), 3)
            for passage in persisted["passages"]:
                self.assertEqual(
                    set(passage["outputs"]),
                    {"mix", "game", "basic", "muscriptor"},
                )
                command_indices = [item["command_index"] for item in passage["outputs"].values()]
                commands = [
                    persisted["commands"][command_index - 1] for command_index in command_indices
                ]
                self.assertEqual(
                    {command["argv"][command["argv"].index("-ss") + 1] for command in commands},
                    {repr(passage["start_sec"])},
                )
                self.assertEqual(
                    {command["argv"][command["argv"].index("-t") + 1] for command in commands},
                    {repr(passage["duration_sec"])},
                )
                for rendered in passage["outputs"].values():
                    validation = rendered["pcm_validation"]
                    self.assertTrue(validation["synchronized_window_verified"])
                    self.assertEqual(validation["sample_rate_hz"], 44_100)
                    self.assertEqual(validation["channels"], 2)
                    self.assertLessEqual(abs(validation["frame_error"]), 1)

            output_records = {item["path"]: item for item in persisted["outputs"]}
            generated_files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file() and path.name != "review_manifest.json"
            }
            self.assertEqual(set(output_records), generated_files)
            for relative_path, record in output_records.items():
                artifact = output / relative_path
                self.assertEqual(record["size_bytes"], artifact.stat().st_size)
                self.assertEqual(
                    record["sha256"],
                    create_melody_review.sha256_file(artifact),
                )

    def test_rejects_tampering_run_id_source_run_id_and_non_succeeded_status(self) -> None:
        mutators = {
            "size mismatch": lambda run, manifest: manifest["outputs"][0].update(
                {"size_bytes": manifest["outputs"][0]["size_bytes"] + 1}
            ),
            "SHA-256 mismatch": lambda run, manifest: (
                run / create_melody_review.EVENTS_RELATIVE_PATH
            ).write_bytes(
                (run / create_melody_review.EVENTS_RELATIVE_PATH)
                .read_bytes()
                .replace(b"60.2", b"61.2", 1)
            ),
            "run_id does not match": lambda run, manifest: manifest.update(
                {"run_id": "different-run"}
            ),
            "status is not succeeded": lambda run, manifest: manifest.update({"status": "failed"}),
        }
        for expected_error, mutate in mutators.items():
            with (
                self.subTest(expected_error=expected_error),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                project_dir, _mix = _write_project(root)
                run = _write_candidate(project_dir, run_id="candidate-run")
                manifest_path = run / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(run, manifest)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(
                    create_melody_review.MelodyReviewError,
                    expected_error,
                ):
                    create_melody_review._load_candidate("candidate", run)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_dir, _mix = _write_project(root)
            run = _write_candidate(
                project_dir,
                run_id="candidate-run",
                events=[
                    _event(
                        "another-run",
                        0,
                        onset=0.0,
                        offset=0.5,
                        pitch=60.0,
                    )
                ],
            )
            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "source_run_id does not match",
            ):
                create_melody_review._load_candidate("candidate", run)

    def test_rejects_unrelated_project_and_canonical_mix_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            other_project, other_mix = _write_project(
                root,
                project_id="unrelated-project",
                mix_payload=b"RIFF-other-song",
            )
            unrelated = _write_candidate(
                other_project,
                run_id="unrelated-run",
                input_audio=other_mix,
                legacy_manifest=True,
            )
            mixed_candidates = dict(inputs["candidates"])
            mixed_candidates["muscriptor"] = unrelated
            output = root / "cross-project-review"

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "share one project identity",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=mixed_candidates,
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertFalse(os.path.lexists(output))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            run = inputs["candidates"]["game"]
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["input_lineage"]["canonical_mix_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "lineage-mismatch-review"

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "lineage canonical mix SHA-256",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=inputs["candidates"],
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertFalse(os.path.lexists(output))

    def test_rejects_non_voice_candidate_but_allows_false_main_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_dir, _mix = _write_project(root)
            run = _write_candidate(
                project_dir,
                run_id="mixed-instrument-run",
                events=[
                    _event(
                        "mixed-instrument-run",
                        0,
                        onset=0.0,
                        offset=0.5,
                        pitch=60.0,
                        is_main_melody_candidate=False,
                    ),
                    _event(
                        "mixed-instrument-run",
                        1,
                        onset=0.5,
                        offset=1.0,
                        pitch=48.0,
                        instrument="bass",
                    ),
                ],
            )
            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "not entirely voice-scoped",
            ):
                create_melody_review._load_candidate("mixed", run)

            voice_run = _write_candidate(
                project_dir,
                run_id="voice-not-main-run",
                events=[
                    _event(
                        "voice-not-main-run",
                        0,
                        onset=0.0,
                        offset=0.5,
                        pitch=60.0,
                        is_main_melody_candidate=False,
                    )
                ],
            )
            record = create_melody_review._load_candidate("voice", voice_run)
            self.assertTrue(record["canonical_events"]["voice_scope_verified"])

    def test_rejects_intermediate_symlink_escape_for_canonical_mix_and_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            mix = Path(inputs["mix"])
            outside_canonical = root / "outside-canonical"
            outside_canonical.mkdir()
            (outside_canonical / "mix.flac").write_bytes(mix.read_bytes())
            canonical_dir = mix.parent
            mix.unlink()
            canonical_dir.rmdir()
            os.symlink(outside_canonical, canonical_dir, target_is_directory=True)

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "symbolic-link component",
            ):
                create_melody_review._load_candidate(
                    "game",
                    inputs["candidates"]["game"],
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            project_dir = Path(inputs["project_dir"])
            stem = (
                project_dir / "runs" / "selected-vocal-separator" / "raw" / "stems" / "vocals.flac"
            )
            outside_stems = root / "outside-stems"
            outside_stems.mkdir()
            (outside_stems / "vocals.flac").write_bytes(stem.read_bytes())
            stems_dir = stem.parent
            stem.unlink()
            stems_dir.rmdir()
            os.symlink(outside_stems, stems_dir, target_is_directory=True)

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "symbolic-link component",
            ):
                create_melody_review._load_candidate(
                    "game",
                    inputs["candidates"]["game"],
                )

    def test_requires_three_candidates_and_passages_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            output = root / "review"
            candidates = dict(inputs["candidates"])
            passages = dict(inputs["passages"])

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "At least three independent",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=dict(list(candidates.items())[:2]),
                    passages=passages,
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertFalse(output.exists())

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "At least three review passages",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=candidates,
                    passages=dict(list(passages.items())[:2]),
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertFalse(output.exists())

    def test_refuses_existing_or_symlink_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "Refusing to overwrite",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=inputs["candidates"],
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=existing,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

            target = root / "target"
            target.mkdir()
            symlink_output = root / "review-link"
            os.symlink(target, symlink_output)
            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "Refusing to overwrite",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=inputs["candidates"],
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=symlink_output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=inputs["ffmpeg"],
                )
            self.assertEqual(list(target.iterdir()), [])

    def test_external_failure_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            failing_ffmpeg = _write_fake_tool(
                root / "工具 空格" / "failing ffmpeg",
                fail_render=True,
            )
            output = root / "atomic review"

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "ffmpeg failed",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=inputs["candidates"],
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=failing_ffmpeg,
                )

            self.assertFalse(os.path.lexists(output))
            self.assertFalse(list(output.parent.glob(f".{output.name}.tmp-*")))

    def test_truncated_pcm_excerpt_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _fixture_inputs(root)
            truncating_ffmpeg = _write_fake_tool(
                root / "工具 空格" / "truncating ffmpeg",
                truncate_excerpt=True,
            )
            output = root / "truncated review"

            with self.assertRaisesRegex(
                create_melody_review.MelodyReviewError,
                "duration is truncated or mismatched",
            ):
                create_melody_review.create_review(
                    mix=inputs["mix"],
                    candidates=inputs["candidates"],
                    passages=inputs["passages"],
                    soundfont=inputs["soundfont"],
                    output=output,
                    fluidsynth=inputs["fluidsynth"],
                    ffmpeg=truncating_ffmpeg,
                )

            self.assertFalse(os.path.lexists(output))
            self.assertFalse(list(output.parent.glob(f".{output.name}.tmp-*")))


if __name__ == "__main__":
    unittest.main()
