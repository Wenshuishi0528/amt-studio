from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkerCommand:
    name: str
    argv: list[str]
    notes: list[str]


def muscriptor_baseline_command(project_dir: Path, *, model: str = "large") -> WorkerCommand:
    project_dir = project_dir.expanduser().resolve()
    audio = project_dir / "audio" / "canonical" / "mix.flac"
    run_dir = project_dir / "runs" / "MANUAL_RUN_ID_muscriptor"
    events = run_dir / "raw" / "muscriptor.jsonl"
    midi = run_dir / "raw" / "muscriptor.mid"
    return WorkerCommand(
        name="muscriptor",
        argv=[
            "muscriptor",
            "transcribe",
            str(audio),
            "--model",
            model,
            "--beam-size",
            "4",
            "--format",
            "jsonl",
            "-o",
            str(events),
        ],
        notes=[
            f"Create the run directory first: {run_dir}",
            "This command emits native JSONL. Run a second deterministic command for MIDI if the CLI cannot emit both in one invocation.",
            f"Suggested MIDI output: {midi}",
            "Replace MANUAL_RUN_ID with a generated stable run ID and capture a run manifest.",
        ],
    )
