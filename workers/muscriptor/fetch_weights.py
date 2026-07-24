from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from huggingface_hub import hf_hub_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

WORKER_DIR = Path(__file__).resolve().parent
DEFAULT_PINS = WORKER_DIR / "pins.json"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_pins(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("schema_version") != 1:
        raise ValueError(f"Unsupported pins schema in {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch the pinned gated MuScriptor weights and record their hashes."
    )
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Ignored local provenance JSON to write after download and hashing.",
    )
    parser.add_argument(
        "--local-weight",
        type=Path,
        help="Register an already transferred pinned weight instead of downloading.",
    )
    parser.add_argument(
        "--local-config",
        type=Path,
        help="Register the config.json transferred with --local-weight.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pins = load_pins(args.pins.resolve())
    model = pins["model"]
    repository = model["repository"]
    revision = model["revision"]

    if (args.local_weight is None) != (args.local_config is None):
        print(
            "error: --local-weight and --local-config must be supplied together",
            file=sys.stderr,
        )
        return 2

    if args.local_weight is not None:
        weight_path = args.local_weight.expanduser().resolve()
        config_path = args.local_config.expanduser().resolve()
        if not weight_path.is_file() or not config_path.is_file():
            print("error: local weight/config file not found", file=sys.stderr)
            return 2
        if weight_path.parent != config_path.parent:
            print(
                "error: local weight and config must share a directory so "
                "MuScriptor can resolve the pinned architecture",
                file=sys.stderr,
            )
            return 2
    else:
        try:
            weight_path = Path(
                hf_hub_download(
                    repo_id=repository,
                    filename=model["weight_filename"],
                    revision=revision,
                )
            )
            config_path = Path(
                hf_hub_download(
                    repo_id=repository,
                    filename=model["config_filename"],
                    revision=revision,
                )
            )
        except (GatedRepoError, HfHubHTTPError) as exc:
            print(
                "error: MuScriptor weights are gated. Accept the model terms at "
                f"https://huggingface.co/{repository} and run `uvx hf auth login` "
                "on this machine. Do not paste the token into project files or chat.",
                file=sys.stderr,
            )
            print(f"detail: {type(exc).__name__}", file=sys.stderr)
            return 2

    provenance = {
        "schema_version": 1,
        "repository": repository,
        "revision": revision,
        "license": model["license"],
        "weight": {
            "filename": model["weight_filename"],
            "path": str(weight_path.resolve()),
            "sha256": sha256_file(weight_path),
            "size_bytes": weight_path.stat().st_size,
        },
        "config": {
            "filename": model["config_filename"],
            "path": str(config_path.resolve()),
            "sha256": sha256_file(config_path),
            "size_bytes": config_path.stat().st_size,
        },
    }
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
