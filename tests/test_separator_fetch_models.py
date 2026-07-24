from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workers.separator.fetch_models import download_expected_file_atomic

from amt_core.utils import sha256_file


class SeparatorModelFetchTests(unittest.TestCase):
    def test_atomic_download_then_verified_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source weights.bin"
            source.write_bytes(b"fixture model bytes")
            model_dir = root / "model cache"
            model_dir.mkdir()
            expected = {
                "path": "weights.bin",
                "sha256": sha256_file(source),
                "size_bytes": source.stat().st_size,
                "source": source.as_uri(),
            }

            first_record, first_action = download_expected_file_atomic(
                model_dir,
                expected,
            )
            self.assertEqual(first_action["status"], "downloaded_atomically")
            self.assertEqual(first_record["sha256"], expected["sha256"])
            self.assertFalse((model_dir / "weights.bin.part").exists())

            second_record, second_action = download_expected_file_atomic(
                model_dir,
                expected,
            )
            self.assertEqual(second_action["status"], "verified_cached")
            self.assertEqual(second_record, first_record)

    def test_failed_validation_leaves_no_partial_or_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"short")
            model_dir = root / "models"
            model_dir.mkdir()
            expected = {
                "path": "weights.bin",
                "sha256": None,
                "size_bytes": 999,
                "source": source.as_uri(),
            }

            with self.assertRaisesRegex(RuntimeError, "Unexpected size"):
                download_expected_file_atomic(model_dir, expected)
            self.assertFalse((model_dir / "weights.bin").exists())
            self.assertFalse((model_dir / "weights.bin.part").exists())

    def test_invalid_cached_file_is_replaced_only_after_valid_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"valid fixture model")
            model_dir = root / "models"
            model_dir.mkdir()
            destination = model_dir / "weights.bin"
            destination.write_bytes(b"bad cache")
            expected = {
                "path": destination.name,
                "sha256": sha256_file(source),
                "size_bytes": source.stat().st_size,
                "source": source.as_uri(),
            }

            record, action = download_expected_file_atomic(model_dir, expected)

            self.assertEqual(action["status"], "replaced_invalid_cache")
            self.assertEqual(record["sha256"], expected["sha256"])
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertFalse((model_dir / "weights.bin.part").exists())

    def test_failed_repair_preserves_invalid_cached_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "short-source.bin"
            source.write_bytes(b"short")
            model_dir = root / "models"
            model_dir.mkdir()
            destination = model_dir / "weights.bin"
            destination.write_bytes(b"bad cache")
            expected = {
                "path": destination.name,
                "sha256": "0" * 64,
                "size_bytes": 999,
                "source": source.as_uri(),
            }

            with self.assertRaisesRegex(RuntimeError, "Unexpected size"):
                download_expected_file_atomic(model_dir, expected)

            self.assertEqual(destination.read_bytes(), b"bad cache")
            self.assertFalse((model_dir / "weights.bin.part").exists())


if __name__ == "__main__":
    unittest.main()
