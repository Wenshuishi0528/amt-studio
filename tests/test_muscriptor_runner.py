from __future__ import annotations

import contextlib
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workers.muscriptor import run_baseline

from amt_core.events import read_jsonl
from amt_core.utils import sha256_file

FAKE_MUSCRIPTOR = """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
if args == ["list-instruments"]:
    print("acoustic_piano")
    raise SystemExit(0)
if not args or args == ["--help"] or args == ["transcribe", "--help"]:
    print("fake muscriptor help")
    raise SystemExit(0)
if args[0] != "transcribe":
    raise SystemExit(2)
output = pathlib.Path(args[args.index("--output") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
format_name = args[args.index("--format") + 1]
if format_name == "jsonl":
    values = [
        {
            "type": "start",
            "pitch": 60,
            "start_time": 0.1,
            "index": 0,
            "instrument": "acoustic_piano",
        },
        {"type": "end", "end_time": 0.8, "start_event_index": 0},
    ]
    output.write_text(
        "".join(json.dumps(value) + "\\n" for value in values),
        encoding="utf-8",
    )
elif format_name == "midi":
    output.write_bytes(b"MThdFAKE")
else:
    raise SystemExit(2)
"""


class MuScriptorRunnerTests(unittest.TestCase):
    def test_complete_fake_run_and_refuse_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project 日本語"
            audio = project / "audio" / "canonical" / "mix.flac"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"fake flac")

            worker_env = root / "worker env"
            bin_dir = worker_env / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").symlink_to(Path(sys.executable))
            fake_cli = bin_dir / "muscriptor"
            fake_cli.write_text(FAKE_MUSCRIPTOR, encoding="utf-8")
            fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IXUSR)

            model_dir = root / "model"
            model_dir.mkdir()
            weight = model_dir / "model.safetensors"
            config = model_dir / "config.json"
            weight.write_bytes(b"fake weights")
            config.write_text("{}\n", encoding="utf-8")

            pins = json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8"))
            provenance = {
                "schema_version": 1,
                "repository": pins["model"]["repository"],
                "revision": pins["model"]["revision"],
                "license": pins["model"]["license"],
                "weight": {
                    "filename": weight.name,
                    "path": str(weight),
                    "sha256": sha256_file(weight),
                    "size_bytes": weight.stat().st_size,
                },
                "config": {
                    "filename": config.name,
                    "path": str(config),
                    "sha256": sha256_file(config),
                    "size_bytes": config.stat().st_size,
                },
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(
                json.dumps(provenance),
                encoding="utf-8",
            )

            diagnostics = {
                "python": "test",
                "platform": "test",
                "machine": "arm64",
                "muscriptor": pins["package"]["version"],
                "torch": "test",
                "mps_built": True,
                "mps_available": True,
                "cuda_available": False,
                "cuda_version": None,
                "cuda_device_count": 0,
            }
            argv = [
                "--project",
                str(project),
                "--worker-env",
                str(worker_env),
                "--weight-provenance",
                str(provenance_path),
                "--run-id",
                "fixture-run",
                "--beam-size",
                "1",
                "--device",
                "mps",
            ]
            with mock.patch.object(
                run_baseline,
                "worker_diagnostics",
                return_value=diagnostics,
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_baseline.main(argv)

            self.assertEqual(exit_code, 0)
            run_dir = project / "runs" / "fixture-run"
            manifest = json.loads(
                (run_dir / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["decoding"]["beam_size"], 1)
            self.assertTrue((run_dir / "raw" / "events.native.jsonl").is_file())
            self.assertEqual(
                (run_dir / "raw" / "full.native.mid").read_bytes(),
                b"MThdFAKE",
            )
            events = read_jsonl(run_dir / "normalized" / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].instrument, "acoustic_piano")
            self.assertGreater(len(manifest["outputs"]), 0)

            with self.assertRaisesRegex(RuntimeError, "immutable run directory"):
                run_baseline.main(argv)


if __name__ == "__main__":
    unittest.main()
