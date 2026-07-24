from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amt_core.utils import atomic_write_json, load_json, sha256_file, slugify


class UtilsTests(unittest.TestCase):
    def test_slugify_preserves_unicode_and_spaces(self) -> None:
        self.assertEqual(slugify("姫乃樹リカ - 硝子のキッス"), "姫乃樹リカ-硝子のキッス")

    def test_atomic_json_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "清单.json"
            atomic_write_json(path, {"a": 1, "标题": "测试"})
            self.assertEqual(load_json(path)["标题"], "测试")
            self.assertEqual(len(sha256_file(path)), 64)


if __name__ == "__main__":
    unittest.main()
