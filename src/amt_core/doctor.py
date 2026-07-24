from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run_doctor() -> list[Check]:
    checks = [
        Check("python", sys.version_info[:2] == (3, 12), sys.version.split()[0]),
        _tool("git", required=True),
        _tool("ffmpeg", required=True),
        _tool("ffprobe", required=True),
        _tool("uv", required=True),
        _tool("fluidsynth", required=False),
    ]
    checks.append(
        Check(
            "platform",
            True,
            f"{platform.system()} {platform.machine()} | {platform.platform()}",
            required=False,
        )
    )
    return checks


def checks_as_dict(checks: list[Check]) -> list[dict[str, object]]:
    return [asdict(check) for check in checks]


def required_checks_pass(checks: list[Check]) -> bool:
    return all(check.ok for check in checks if check.required)


def _tool(name: str, *, required: bool) -> Check:
    path = shutil.which(name)
    if path is None:
        return Check(name, False, "not found", required=required)
    try:
        version = subprocess.run(
            [path, "-version" if name in {"ffmpeg", "ffprobe"} else "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = (version.stdout or version.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        first_line = path
    return Check(name, True, first_line, required=required)
