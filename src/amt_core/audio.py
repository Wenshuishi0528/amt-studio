from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class AudioToolError(RuntimeError):
    """Raised when ffmpeg/ffprobe fails."""


def require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise AudioToolError(f"Required executable not found on PATH: {name}")
    return resolved


def probe_audio(path: Path) -> dict[str, Any]:
    ffprobe = require_tool("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index,codec_name,sample_rate,channels,channel_layout,bit_rate,duration",
        "-show_entries",
        "format=format_name,duration,size,bit_rate",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AudioToolError(
            f"ffprobe failed for {path}: {completed.stderr.strip() or 'unknown error'}"
        )
    data = json.loads(completed.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise AudioToolError(f"No audio stream found in {path}")
    stream = streams[0]
    fmt = data.get("format") or {}
    return {
        "codec": stream.get("codec_name"),
        "sample_rate_hz": _to_int(stream.get("sample_rate")),
        "channels": _to_int(stream.get("channels")),
        "channel_layout": stream.get("channel_layout"),
        "duration_sec": _first_float(stream.get("duration"), fmt.get("duration")),
        "stream_bitrate_bps": _to_int(stream.get("bit_rate")),
        "container_bitrate_bps": _to_int(fmt.get("bit_rate")),
        "file_size_bytes": _to_int(fmt.get("size")),
        "format_name": fmt.get("format_name"),
    }


def canonicalize_audio(source: Path, destination: Path) -> list[str]:
    ffmpeg = require_tool("ffmpeg")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "flac",
        "-compression_level",
        "8",
        str(destination),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        raise AudioToolError(
            f"ffmpeg canonicalization failed: {completed.stderr.strip() or 'unknown error'}"
        )
    return command


def _to_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    return int(value)


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value not in (None, "", "N/A"):
            return float(value)
    return None
