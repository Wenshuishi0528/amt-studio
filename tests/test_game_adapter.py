from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from workers.game.normalize import GameNativeError, normalize_native_csv
from workers.game.prepare_assets import _safe_zip_member

from amt_core.events import read_jsonl


class GameAdapterTests(unittest.TestCase):
    def test_normalize_preserves_float_pitch_and_native_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "GAME 日本語.csv"
            with native.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["onset", "offset", "pitch"])
                writer.writerow(["1.250", "1.750", "60.375"])
                writer.writerow(["1.750", "2.000", "62.000"])

            output = root / "events.jsonl"
            summary_path = root / "summary.json"
            summary = normalize_native_csv(
                native,
                output,
                summary_path,
                run_id="game-fixture",
                source_model="openvpi/GAME@fixture",
            )

            events = read_jsonl(output)
            self.assertEqual(summary["event_count"], 2)
            self.assertEqual(events[0].pitch_midi, 60.375)
            self.assertEqual(events[0].quantized_pitch_midi, 60)
            self.assertTrue(events[0].is_main_melody_candidate)
            self.assertEqual(events[0].instrument, "voice")
            self.assertIsNone(events[0].confidence)
            self.assertEqual(
                events[0].extra["native_csv_row"],
                {"onset": "1.250", "offset": "1.750", "pitch": "60.375"},
            )
            self.assertFalse(
                json.loads(summary_path.read_text(encoding="utf-8"))["accuracy_claimed"]
            )

    def test_normalize_rejects_header_and_overlap_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "events.jsonl"
            summary = root / "summary.json"
            bad_header = root / "bad-header.csv"
            bad_header.write_text("start,offset,pitch\n0,1,60\n", encoding="utf-8")
            with self.assertRaisesRegex(GameNativeError, "expected CSV header"):
                normalize_native_csv(
                    bad_header,
                    output,
                    summary,
                    run_id="game-fixture",
                    source_model="fixture",
                )

            overlap = root / "overlap.csv"
            overlap.write_text(
                "onset,offset,pitch\n0.000,1.000,60.000\n0.900,1.500,62.000\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GameNativeError, "overlap"):
                normalize_native_csv(
                    overlap,
                    output,
                    summary,
                    run_id="game-fixture",
                    source_model="fixture",
                )

    def test_archive_member_rejects_path_escape_and_symlink(self) -> None:
        self.assertEqual(
            _safe_zip_member(zipfile.ZipInfo("model/config.yaml")).as_posix(),
            "model/config.yaml",
        )
        with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
            _safe_zip_member(zipfile.ZipInfo("../escape.pt"))
        symlink = zipfile.ZipInfo("model/link.pt")
        symlink.external_attr = 0o120777 << 16
        with self.assertRaisesRegex(RuntimeError, "Symbolic link"):
            _safe_zip_member(symlink)


if __name__ == "__main__":
    unittest.main()
