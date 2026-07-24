from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.events import NoteEvent, read_jsonl
from amt_core.utils import atomic_write_json, sha256_file

REQUIRED_PATHS = ("direct", "vocal_a", "vocal_b")
REQUIRED_SEPARATOR_PRESETS = frozenset({"vocal_quality_a", "multistem_quality_a"})
ONSET_TOLERANCE_SEC = 0.05
OFFSET_TOLERANCE_SEC = 0.10


class ComparisonError(ValueError):
    """Raised when AMT runs do not form a valid controlled comparison."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ComparisonError(f"Unsupported JSON object in {path}")
    return value


def parse_named_runs(values: list[str]) -> dict[str, Path]:
    aliases = {
        "direct": "direct",
        "vocala": "vocal_a",
        "vocal_a": "vocal_a",
        "vocalb": "vocal_b",
        "vocal_b": "vocal_b",
    }
    runs: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ComparisonError(f"Invalid --run value (expected NAME=RUN_DIR): {value}")
        raw_name, raw_path = value.split("=", 1)
        normalized_name = raw_name.strip().lower().replace("-", "_")
        name = aliases.get(normalized_name)
        if name is None:
            raise ComparisonError(
                f"Unknown comparison path {raw_name!r}; use direct, vocal_a, or vocal_b"
            )
        if name in runs:
            raise ComparisonError(f"Duplicate comparison path: {name}")
        if not raw_path.strip():
            raise ComparisonError(f"Empty run directory for path: {name}")
        runs[name] = Path(raw_path).expanduser().resolve()

    missing = [name for name in REQUIRED_PATHS if name not in runs]
    if missing:
        raise ComparisonError(f"Missing comparison path(s): {', '.join(missing)}")
    return {name: runs[name] for name in REQUIRED_PATHS}


def _output_record(
    manifest: dict[str, Any],
    *,
    relative_path: str,
) -> dict[str, Any]:
    matches = [
        record
        for record in manifest.get("outputs", [])
        if isinstance(record, dict) and record.get("path") == relative_path
    ]
    if len(matches) != 1:
        raise ComparisonError(
            f"Manifest must contain exactly one output record for {relative_path}"
        )
    return matches[0]


def _verify_artifact(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    relative_path: str,
) -> Path:
    path = run_dir / relative_path
    if not path.is_file():
        raise ComparisonError(f"Required run artifact is missing: {path}")
    record = _output_record(manifest, relative_path=relative_path)
    actual_hash = sha256_file(path)
    if record.get("sha256") != actual_hash:
        raise ComparisonError(
            f"Artifact hash mismatch for {path}: {actual_hash} != {record.get('sha256')}"
        )
    return path


def _canonical_instruments(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        names = [name.strip().lower() for name in value.split(",") if name.strip()]
    elif isinstance(value, list) and all(isinstance(name, str) for name in value):
        names = [name.strip().lower() for name in value]
    else:
        raise ComparisonError(f"Invalid decoding instruments value: {value!r}")
    if not names or any(not name for name in names):
        raise ComparisonError(f"Invalid decoding instruments value: {value!r}")
    return names


def _configuration_signature(manifest: dict[str, Any]) -> dict[str, Any]:
    provenance = manifest.get("model_provenance")
    decoding = manifest.get("decoding")
    if not isinstance(provenance, dict) or not isinstance(decoding, dict):
        raise ComparisonError("MuScriptor manifest lacks model or decoding provenance")
    package = provenance.get("package")
    if not isinstance(package, dict):
        raise ComparisonError("MuScriptor manifest lacks package provenance")
    return {
        "model": manifest.get("model"),
        "repository": provenance.get("repository"),
        "revision": provenance.get("revision"),
        "weight_sha256": provenance.get("weight_sha256"),
        "config_sha256": provenance.get("config_sha256"),
        "package": {
            "name": package.get("name"),
            "version": package.get("version"),
        },
        "beam_size": decoding.get("beam_size"),
        "instruments": _canonical_instruments(decoding.get("instruments")),
        "dtype": decoding.get("dtype"),
        "device": decoding.get("device"),
        "skip_midi": decoding.get("skip_midi"),
        "prelude_forcing": decoding.get("prelude_forcing"),
        "sampling": decoding.get("sampling"),
        "cfg_coef": decoding.get("cfg_coef"),
    }


def _event_summary(events: list[NoteEvent]) -> dict[str, Any]:
    durations = [event.offset_sec - event.onset_sec for event in events]
    instruments = Counter(event.instrument for event in events)
    return {
        "event_count": len(events),
        "instrument_counts": {
            str(name): count
            for name, count in sorted(instruments.items(), key=lambda item: str(item[0]))
        },
        "note_duration_sec": _distribution(durations),
        "timeline_sec": {
            "first_onset": min((event.onset_sec for event in events), default=None),
            "last_offset": max((event.offset_sec for event in events), default=None),
        },
        "pitch_midi": {
            "minimum": min((event.pitch_midi for event in events), default=None),
            "maximum": max((event.pitch_midi for event in events), default=None),
        },
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "mean": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "minimum": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "maximum": max(values),
    }


def _load_run(name: str, run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = load_object(manifest_path)
    if manifest.get("worker") != "muscriptor" or manifest.get("status") != "succeeded":
        raise ComparisonError(f"{name} is not a succeeded MuScriptor run: {run_dir}")
    if not isinstance(manifest.get("run_id"), str):
        raise ComparisonError(f"{name} manifest has no run_id")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise ComparisonError(f"{name} manifest must record exactly one audio input")
    input_record = inputs[0]
    if not isinstance(input_record, dict) or not isinstance(input_record.get("sha256"), str):
        raise ComparisonError(f"{name} manifest input has no SHA-256")

    summary_path = _verify_artifact(
        run_dir,
        manifest,
        relative_path="normalized/summary.json",
    )
    events_path = _verify_artifact(
        run_dir,
        manifest,
        relative_path="normalized/events.jsonl",
    )
    summary = load_object(summary_path)
    events = read_jsonl(events_path)
    run_id = manifest["run_id"]
    if summary.get("run_id") != run_id:
        raise ComparisonError(f"{name} normalized summary run_id does not match manifest")
    if summary.get("event_count") != len(events):
        raise ComparisonError(f"{name} normalized summary event_count does not match events.jsonl")
    if any(event.source_run_id != run_id for event in events):
        raise ComparisonError(f"{name} contains events attributed to another run")

    computed = _event_summary(events)
    if summary.get("instrument_counts") != computed["instrument_counts"]:
        raise ComparisonError(
            f"{name} normalized summary instrument_counts do not match events.jsonl"
        )
    for field in ("pitch_midi", "timeline_sec"):
        if summary.get(field) != computed[field]:
            raise ComparisonError(f"{name} normalized summary {field} does not match events.jsonl")

    embedded_summary = manifest.get("metrics", {}).get("descriptive_event_summary")
    if embedded_summary is not None and embedded_summary != summary:
        raise ComparisonError(
            f"{name} manifest descriptive summary differs from normalized/summary.json"
        )

    lineage = manifest.get("input_lineage")
    if not isinstance(lineage, dict):
        raise ComparisonError(f"{name} manifest lacks input_lineage; rerun with the Task003 runner")
    return {
        "name": name,
        "run_dir": run_dir,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "summary": summary,
        "summary_sha256": sha256_file(summary_path),
        "events": events,
        "events_sha256": sha256_file(events_path),
        "input": input_record,
        "lineage": lineage,
        "configuration": _configuration_signature(manifest),
        "computed_summary": computed,
    }


def _locate_parent_manifest(run: dict[str, Any]) -> Path:
    lineage = run["lineage"]
    parent_run_id = lineage.get("parent_separator_run_id")
    if not isinstance(parent_run_id, str):
        raise ComparisonError(f"{run['name']} lineage has no parent separator run_id")
    project_dir = run["run_dir"].parent.parent
    local_candidate = project_dir / "runs" / parent_run_id / "run_manifest.json"
    recorded = lineage.get("parent_manifest_path")
    recorded_candidate = Path(recorded) if isinstance(recorded, str) else None
    for path in (local_candidate, recorded_candidate):
        if path is not None and path.is_file():
            return path.resolve()
    raise ComparisonError(
        f"Cannot locate parent separator manifest for {run['name']}: {parent_run_id}"
    )


def _validate_lineage(run: dict[str, Any]) -> dict[str, Any]:
    name = run["name"]
    input_hash = run["input"]["sha256"]
    lineage = run["lineage"]
    if name == "direct":
        if lineage.get("kind") != "direct_canonical_mix":
            raise ComparisonError("direct path must use the canonical mix")
        if lineage.get("canonical_mix_sha256") != input_hash:
            raise ComparisonError("direct input hash differs from its canonical lineage")
        canonical_path = run["run_dir"].parent.parent / "audio" / "canonical" / "mix.flac"
        if not canonical_path.is_file() or sha256_file(canonical_path) != input_hash:
            raise ComparisonError("direct canonical mix is missing or has changed")
        return {
            "kind": "direct_canonical_mix",
            "input_sha256": input_hash,
            "canonical_mix_sha256": input_hash,
        }

    if lineage.get("kind") != "separator_stem":
        raise ComparisonError(f"{name} path must use a separator stem")
    if lineage.get("parent_stem_name") != "vocals":
        raise ComparisonError(f"{name} path must use a vocals stem")
    if lineage.get("parent_stem_sha256") != input_hash:
        raise ComparisonError(f"{name} input hash differs from parent stem lineage")

    parent_manifest_path = _locate_parent_manifest(run)
    recorded_parent_hash = lineage.get("parent_manifest_sha256")
    actual_parent_hash = sha256_file(parent_manifest_path)
    if recorded_parent_hash != actual_parent_hash:
        raise ComparisonError(f"{name} parent separator manifest hash has changed")
    parent = load_object(parent_manifest_path)
    if parent.get("worker") != "separator" or parent.get("status") != "succeeded":
        raise ComparisonError(f"{name} parent is not a succeeded separator run")

    output_path = lineage.get("parent_output_path")
    if not isinstance(output_path, str):
        raise ComparisonError(f"{name} lineage has no parent stem output path")
    parent_output = _output_record(parent, relative_path=output_path)
    if parent_output.get("sha256") != input_hash:
        raise ComparisonError(f"{name} parent manifest stem hash differs from AMT input")
    stem_path = parent_manifest_path.parent / output_path
    if not stem_path.is_file() or sha256_file(stem_path) != input_hash:
        raise ComparisonError(f"{name} parent stem is missing or has changed")

    parent_inputs = parent.get("inputs")
    if not isinstance(parent_inputs, list) or len(parent_inputs) != 1:
        raise ComparisonError(f"{name} parent separator must have exactly one mix input")
    parent_mix = parent_inputs[0]
    canonical_hash = lineage.get("canonical_mix_sha256")
    if not isinstance(parent_mix, dict) or parent_mix.get("sha256") != canonical_hash:
        raise ComparisonError(f"{name} parent mix hash differs from recorded lineage")

    audio_metrics = parent.get("metrics", {}).get("audio", {})
    mix_metrics = audio_metrics.get("mix", {}) if isinstance(audio_metrics, dict) else {}
    stem_name = lineage["parent_stem_name"]
    stem_metrics = (
        audio_metrics.get("stems", {}).get(stem_name, {}) if isinstance(audio_metrics, dict) else {}
    )
    return {
        "kind": "separator_stem",
        "input_sha256": input_hash,
        "canonical_mix_sha256": canonical_hash,
        "parent_separator_run_id": parent.get("run_id"),
        "parent_separator_preset": parent.get("preset"),
        "parent_manifest_sha256": actual_parent_hash,
        "parent_stem_name": stem_name,
        "parent_stem_sha256": input_hash,
        "timeline": {
            "mix_duration_sec": mix_metrics.get("duration_sec"),
            "stem_duration_sec": stem_metrics.get("duration_sec"),
            "stem_duration_drift_sec": stem_metrics.get("duration_drift_sec"),
        },
    }


def _event_key(event: NoteEvent) -> tuple[str | None, float]:
    pitch = (
        float(event.quantized_pitch_midi)
        if event.quantized_pitch_midi is not None
        else event.pitch_midi
    )
    return event.instrument, pitch


def _path_agreement(
    left_name: str,
    left: list[NoteEvent],
    right_name: str,
    right: list[NoteEvent],
) -> dict[str, Any]:
    right_groups: dict[tuple[str | None, float], list[tuple[int, NoteEvent]]] = defaultdict(list)
    for index, event in enumerate(right):
        right_groups[_event_key(event)].append((index, event))

    used_right: set[int] = set()
    matched: list[tuple[NoteEvent, NoteEvent]] = []
    for left_event in sorted(
        left,
        key=lambda event: (event.onset_sec, event.offset_sec, event.event_id),
    ):
        candidates = [
            (index, right_event)
            for index, right_event in right_groups.get(_event_key(left_event), [])
            if index not in used_right
            and abs(left_event.onset_sec - right_event.onset_sec) <= ONSET_TOLERANCE_SEC
        ]
        if not candidates:
            continue
        right_index, right_event = min(
            candidates,
            key=lambda item: (
                abs(left_event.onset_sec - item[1].onset_sec),
                abs(left_event.offset_sec - item[1].offset_sec),
                item[0],
            ),
        )
        used_right.add(right_index)
        matched.append((left_event, right_event))

    onset_deltas = [
        abs(left_event.onset_sec - right_event.onset_sec) for left_event, right_event in matched
    ]
    offset_deltas = [
        abs(left_event.offset_sec - right_event.offset_sec) for left_event, right_event in matched
    ]
    onset_and_offset = sum(delta <= OFFSET_TOLERANCE_SEC for delta in offset_deltas)
    match_count = len(matched)
    return {
        "left_path": left_name,
        "right_path": right_name,
        "definition": {
            "same_instrument": True,
            "same_midi_pitch": True,
            "onset_tolerance_sec": ONSET_TOLERANCE_SEC,
            "offset_tolerance_sec": OFFSET_TOLERANCE_SEC,
            "matching": "deterministic one-to-one nearest-onset pairing",
        },
        "left_event_count": len(left),
        "right_event_count": len(right),
        "onset_partner_count": match_count,
        "onset_and_offset_partner_count": onset_and_offset,
        "left_fraction_with_onset_partner": (match_count / len(left) if left else None),
        "right_fraction_with_onset_partner": (match_count / len(right) if right else None),
        "absolute_onset_delta_sec": _distribution(onset_deltas),
        "absolute_offset_delta_sec_for_onset_partners": _distribution(offset_deltas),
    }


def compare_runs(named_runs: dict[str, Path]) -> dict[str, Any]:
    if set(named_runs) != set(REQUIRED_PATHS):
        raise ComparisonError(f"Expected paths {REQUIRED_PATHS}, got {tuple(named_runs)}")
    runs = {name: _load_run(name, named_runs[name]) for name in REQUIRED_PATHS}

    shared_configuration = runs["direct"]["configuration"]
    for name in ("vocal_a", "vocal_b"):
        if runs[name]["configuration"] != shared_configuration:
            raise ComparisonError(f"{name} model/decoding configuration differs from direct")
    if shared_configuration["instruments"] != ["voice"]:
        raise ComparisonError(
            "Task003 controlled comparison requires --instruments voice for all paths"
        )

    lineages = {name: _validate_lineage(runs[name]) for name in REQUIRED_PATHS}
    canonical_hashes = {lineage["canonical_mix_sha256"] for lineage in lineages.values()}
    if len(canonical_hashes) != 1:
        raise ComparisonError("AMT paths do not share one canonical mix timeline")
    canonical_mix_hash = canonical_hashes.pop()

    parent_ids = {lineages[name].get("parent_separator_run_id") for name in ("vocal_a", "vocal_b")}
    if len(parent_ids) != 2:
        raise ComparisonError("vocal_a and vocal_b must come from separate separator runs")
    parent_presets = {
        lineages[name].get("parent_separator_preset") for name in ("vocal_a", "vocal_b")
    }
    if parent_presets != REQUIRED_SEPARATOR_PRESETS:
        raise ComparisonError(
            "Task003 requires separator preset set "
            f"{sorted(REQUIRED_SEPARATOR_PRESETS)}, got "
            f"{sorted(str(value) for value in parent_presets)}"
        )

    pairs = (
        ("direct", "vocal_a"),
        ("direct", "vocal_b"),
        ("vocal_a", "vocal_b"),
    )
    path_agreement = [
        _path_agreement(
            left_name,
            runs[left_name]["events"],
            right_name,
            runs[right_name]["events"],
        )
        for left_name, right_name in pairs
    ]
    public_runs = {
        name: {
            "run_id": runs[name]["manifest"]["run_id"],
            "run_dir": str(runs[name]["run_dir"]),
            "manifest_sha256": runs[name]["manifest_sha256"],
            "normalized_summary_sha256": runs[name]["summary_sha256"],
            "normalized_events_sha256": runs[name]["events_sha256"],
            "input": runs[name]["input"],
            "lineage": lineages[name],
            "descriptive_event_summary": runs[name]["computed_summary"],
            "instrument_constraint_violation_count": sum(
                event.instrument != "voice" for event in runs[name]["events"]
            ),
        }
        for name in REQUIRED_PATHS
    }
    return {
        "schema_version": 1,
        "comparison_type": "descriptive_amt_path_agreement",
        "generated_at": utc_now(),
        "claims": {
            "accuracy_claimed": False,
            "human_reference_annotations_used": False,
            "selection_or_ranking_claimed": False,
        },
        "controlled_configuration": shared_configuration,
        "timeline_validation": {
            "shared_canonical_mix_sha256": canonical_mix_hash,
            "all_paths_share_canonical_mix": True,
            "parent_stem_hashes_verified": True,
            "parent_separator_presets": sorted(parent_presets),
        },
        "runs": public_runs,
        "path_agreement": path_agreement,
        "limitations": [
            "These are descriptive candidate-event counts and cross-path agreement only.",
            (
                "Agreement can represent shared errors and disagreement does not "
                "identify which path is correct."
            ),
            (
                "No precision, recall, F1, or separator benefit claim is valid until "
                "Task006 human references exist."
            ),
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Compare controlled direct/vocal MuScriptor runs without claiming accuracy.")
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="NAME=RUN_DIR",
        help="Repeat for direct, vocal_a, and vocal_b.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_runs(parse_named_runs(args.run))
    output = args.output.expanduser().resolve()
    atomic_write_json(output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
