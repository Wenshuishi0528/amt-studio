from __future__ import annotations

import argparse
import array
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from amt_core.audio import probe_audio
from amt_core.utils import atomic_write_json, sha256_file

SAMPLE_RATE = 44_100
CHANNELS = 2
SILENCE_THRESHOLD = 1e-4
CLIPPING_THRESHOLD = 0.999
WINDOW_SECONDS = 1.0
ENDPOINT_TOLERANCE_FRAMES = 1
ALIGNMENT_SAMPLE_RATE = 500
ALIGNMENT_MAX_LAG_SECONDS = 0.1
ALIGNMENT_TOLERANCE_SECONDS = 0.01
ALIGNMENT_WINDOW_SECONDS = 12.0
ALIGNMENT_MIN_FRAMES = 100
ALIGNMENT_MIN_CORRELATION = 0.2


class AudioMetricError(RuntimeError):
    """Raised when an audio metric subprocess or contract fails."""


def _float_stream(command: list[str]) -> tuple[dict[str, Any], list[float]]:
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        if process.stdout is None:
            raise AudioMetricError("ffmpeg stdout pipe was not created")

        scalar_count = 0
        sum_squares = 0.0
        peak = 0.0
        clipping_count = 0
        silent_count = 0
        window_size = int(SAMPLE_RATE * CHANNELS * WINDOW_SECONDS)
        window_count = 0
        window_sum_squares = 0.0
        window_rms: list[float] = []

        while chunk := process.stdout.read(1024 * 1024):
            if len(chunk) % 4:
                process.kill()
                raise AudioMetricError("ffmpeg produced an incomplete float32 sample")
            values = array.array("f")
            values.frombytes(chunk)
            if sys.byteorder != "little":
                values.byteswap()

            position = 0
            while position < len(values):
                take = min(window_size - window_count, len(values) - position)
                segment = values[position : position + take]
                for value in segment:
                    absolute = abs(value)
                    sum_squares += value * value
                    window_sum_squares += value * value
                    peak = max(peak, absolute)
                    clipping_count += int(absolute >= CLIPPING_THRESHOLD)
                    silent_count += int(absolute <= SILENCE_THRESHOLD)
                scalar_count += take
                window_count += take
                position += take
                if window_count == window_size:
                    window_rms.append(math.sqrt(window_sum_squares / window_count))
                    window_count = 0
                    window_sum_squares = 0.0

        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code != 0:
            raise AudioMetricError(
                f"ffmpeg metric command failed ({return_code}): {stderr.strip()}"
            )
        if scalar_count == 0:
            raise AudioMetricError("ffmpeg metric command produced no audio samples")
        if window_count:
            window_rms.append(math.sqrt(window_sum_squares / window_count))

        rms = math.sqrt(sum_squares / scalar_count)
        decoded_frames = scalar_count // CHANNELS
        stats = {
            "sample_rate_hz": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_frames": decoded_frames,
            "duration_sec": scalar_count / (SAMPLE_RATE * CHANNELS),
            "rms": rms,
            "rms_dbfs": 20 * math.log10(rms) if rms > 0 else None,
            "rms_loudness_proxy_dbfs": 20 * math.log10(rms) if rms > 0 else None,
            "peak": peak,
            "clipping_fraction": clipping_count / scalar_count,
            "near_silent_fraction": silent_count / scalar_count,
            "decoded": {
                "sample_format": "float32le",
                "sample_rate_hz": SAMPLE_RATE,
                "channels": CHANNELS,
                "sample_frames": decoded_frames,
                "scalar_samples": scalar_count,
            },
            "thresholds": {
                "clipping_abs_amplitude": CLIPPING_THRESHOLD,
                "near_silent_abs_amplitude": SILENCE_THRESHOLD,
            },
        }
        return stats, window_rms


def _decode_command(path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-f",
        "f32le",
        "pipe:1",
    ]


def _parse_ebur128_value(value: str) -> float | None:
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def loudness_stats(path: Path) -> dict[str, Any]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-nostats",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-filter:a",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return {
            "method": "ffmpeg ebur128=peak=true",
            "available": False,
            "integrated_lufs": None,
            "true_peak_dbfs": None,
            "error": completed.stderr.strip()[-1000:] or "ffmpeg ebur128 failed",
        }

    integrated = re.search(
        r"Integrated loudness:\s*I:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)|[-+]?inf)\s+LUFS",
        completed.stderr,
        flags=re.IGNORECASE,
    )
    true_peak = re.search(
        r"True peak:\s*Peak:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)|[-+]?inf)\s+dBFS",
        completed.stderr,
        flags=re.IGNORECASE,
    )
    integrated_lufs = _parse_ebur128_value(integrated.group(1)) if integrated is not None else None
    true_peak_dbfs = _parse_ebur128_value(true_peak.group(1)) if true_peak is not None else None
    available = integrated is not None and true_peak is not None
    result: dict[str, Any] = {
        "method": "ffmpeg ebur128=peak=true",
        "available": available,
        "integrated_lufs": integrated_lufs,
        "true_peak_dbfs": true_peak_dbfs,
    }
    if not available:
        result["error"] = "ffmpeg completed but the EBU R128 summary could not be parsed"
    return result


def audio_stats(path: Path) -> tuple[dict[str, Any], list[float]]:
    stats, windows = _float_stream(_decode_command(path))
    stats["path"] = str(path)
    stats["sha256"] = sha256_file(path)
    stats["probe"] = probe_audio(path)
    stats["loudness"] = loudness_stats(path)
    return stats, windows


def reconstruction_stats(
    mix_path: Path,
    stem_paths: list[Path],
) -> tuple[dict[str, Any], list[float]]:
    if not stem_paths:
        raise ValueError("At least one stem is required for reconstruction")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    for path in (mix_path, *stem_paths):
        command.extend(["-i", str(path)])
    stem_inputs = "".join(f"[{index}:a]" for index in range(1, len(stem_paths) + 1))
    filter_graph = (
        f"{stem_inputs}amix=inputs={len(stem_paths)}:"
        "normalize=0:duration=longest:dropout_transition=0[stem_sum];"
        f"[stem_sum]aformat=sample_fmts=flt:sample_rates={SAMPLE_RATE}:"
        "channel_layouts=stereo[sum_stereo];"
        f"[0:a]aformat=sample_fmts=flt:sample_rates={SAMPLE_RATE}:"
        "channel_layouts=stereo[mix_stereo];"
        "[sum_stereo][mix_stereo]amerge=inputs=2[merged];"
        "[merged]pan=stereo|c0=c0-c2|c1=c1-c3[diff]"
    )
    command.extend(
        [
            "-filter_complex",
            filter_graph,
            "-map",
            "[diff]",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    return _float_stream(command)


def _mono_float_stream(command: list[str]) -> array.array[float]:
    completed = subprocess.run(command, check=False, capture_output=True)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise AudioMetricError(
            f"ffmpeg alignment command failed ({completed.returncode}): {stderr.strip()}"
        )
    if not completed.stdout or len(completed.stdout) % 4:
        raise AudioMetricError("ffmpeg alignment command produced invalid float32 audio")
    values = array.array("f")
    values.frombytes(completed.stdout)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def _mono_decode_command(path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ar",
        str(ALIGNMENT_SAMPLE_RATE),
        "-ac",
        "1",
        "-f",
        "f32le",
        "pipe:1",
    ]


def _stem_sum_mono_decode_command(stem_paths: list[Path]) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    for path in stem_paths:
        command.extend(["-i", str(path)])
    stem_inputs = "".join(f"[{index}:a]" for index in range(len(stem_paths)))
    command.extend(
        [
            "-filter_complex",
            (
                f"{stem_inputs}amix=inputs={len(stem_paths)}:"
                "normalize=0:duration=longest:dropout_transition=0[stem_sum]"
            ),
            "-map",
            "[stem_sum]",
            "-ar",
            str(ALIGNMENT_SAMPLE_RATE),
            "-ac",
            "1",
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    return command


def _correlation_at_lag(
    reference: array.array[float],
    candidate: array.array[float],
    *,
    reference_start: int,
    reference_end: int,
    lag_frames: int,
) -> tuple[float, int] | None:
    start = max(reference_start, -lag_frames)
    end = min(reference_end, len(reference), len(candidate) - lag_frames)
    count = end - start
    if count < ALIGNMENT_MIN_FRAMES:
        return None

    reference_sum = 0.0
    candidate_sum = 0.0
    reference_square_sum = 0.0
    candidate_square_sum = 0.0
    product_sum = 0.0
    for reference_index in range(start, end):
        reference_value = reference[reference_index]
        candidate_value = candidate[reference_index + lag_frames]
        reference_sum += reference_value
        candidate_sum += candidate_value
        reference_square_sum += reference_value * reference_value
        candidate_square_sum += candidate_value * candidate_value
        product_sum += reference_value * candidate_value

    reference_energy = reference_square_sum - (reference_sum * reference_sum / count)
    candidate_energy = candidate_square_sum - (candidate_sum * candidate_sum / count)
    if reference_energy <= 1e-12 * count or candidate_energy <= 1e-12 * count:
        return None
    covariance = product_sum - (reference_sum * candidate_sum / count)
    correlation = covariance / math.sqrt(reference_energy * candidate_energy)
    return max(-1.0, min(1.0, correlation)), count


def _estimate_lag(
    reference: array.array[float],
    candidate: array.array[float],
    *,
    reference_start: int,
    reference_end: int,
) -> dict[str, Any]:
    max_lag_frames = round(ALIGNMENT_MAX_LAG_SECONDS * ALIGNMENT_SAMPLE_RATE)
    best: tuple[float, int, int] | None = None
    for lag_frames in range(-max_lag_frames, max_lag_frames + 1):
        measured = _correlation_at_lag(
            reference,
            candidate,
            reference_start=reference_start,
            reference_end=reference_end,
            lag_frames=lag_frames,
        )
        if measured is None:
            continue
        correlation, compared_frames = measured
        if best is None:
            best = (correlation, lag_frames, compared_frames)
            continue
        best_correlation, best_lag, _ = best
        if correlation > best_correlation + 1e-12 or (
            abs(correlation - best_correlation) <= 1e-12 and abs(lag_frames) < abs(best_lag)
        ):
            best = (correlation, lag_frames, compared_frames)

    segment = {
        "reference_start_sec": reference_start / ALIGNMENT_SAMPLE_RATE,
        "reference_end_sec": reference_end / ALIGNMENT_SAMPLE_RATE,
    }
    if best is None:
        return {
            **segment,
            "measurable": False,
            "reliable": False,
            "estimate_status": "unavailable",
            "lag_frames": None,
            "lag_sec": None,
            "correlation": None,
            "compared_frames": 0,
            "within_tolerance": None,
            "reason": "insufficient non-silent signal for correlation",
        }

    correlation, lag_frames, compared_frames = best
    lag_sec = lag_frames / ALIGNMENT_SAMPLE_RATE
    reliable = correlation >= ALIGNMENT_MIN_CORRELATION
    return {
        **segment,
        "measurable": True,
        "reliable": reliable,
        "estimate_status": (
            "candidate_diagnostic" if reliable else "candidate_diagnostic_unreliable"
        ),
        "lag_frames": lag_frames,
        "lag_sec": lag_sec,
        "correlation": correlation,
        "compared_frames": compared_frames,
        "within_tolerance": (abs(lag_sec) <= ALIGNMENT_TOLERANCE_SECONDS if reliable else None),
        **(
            {}
            if reliable
            else {
                "reason": (
                    "Peak correlation is below the minimum reliability "
                    "threshold; lag remains an unconfirmed diagnostic candidate."
                )
            }
        ),
    }


def alignment_stats(mix_path: Path, stem_paths: list[Path]) -> dict[str, Any]:
    if not stem_paths:
        raise ValueError("At least one stem is required for alignment")
    mix = _mono_float_stream(_mono_decode_command(mix_path))
    stem_sum = _mono_float_stream(_stem_sum_mono_decode_command(stem_paths))
    window_frames = min(
        len(mix),
        round(ALIGNMENT_WINDOW_SECONDS * ALIGNMENT_SAMPLE_RATE),
    )
    middle_start = max(0, (len(mix) - window_frames) // 2)
    windows = [
        ("beginning", 0, window_frames),
        ("middle", middle_start, middle_start + window_frames),
        ("end", max(0, len(mix) - window_frames), len(mix)),
    ]
    global_lag = _estimate_lag(
        mix,
        stem_sum,
        reference_start=0,
        reference_end=len(mix),
    )
    window_lags = [
        {
            "name": name,
            **_estimate_lag(
                mix,
                stem_sum,
                reference_start=start,
                reference_end=end,
            ),
        }
        for name, start, end in windows
    ]

    segments = [global_lag, *window_lags]
    reliable = [item for item in segments if item["reliable"] and item["lag_sec"] is not None]
    max_abs_lag_sec = max(abs(item["lag_sec"]) for item in reliable) if reliable else None
    all_segments_reliable = len(reliable) == len(segments)
    return {
        "status": "diagnostic_only",
        "method": (
            "Normalized cross-correlation between ffmpeg-decoded mono mix and "
            "the linear sum of stems."
        ),
        "sample_rate_hz": ALIGNMENT_SAMPLE_RATE,
        "resolution_sec": 1 / ALIGNMENT_SAMPLE_RATE,
        "search_range_sec": {
            "minimum": -ALIGNMENT_MAX_LAG_SECONDS,
            "maximum": ALIGNMENT_MAX_LAG_SECONDS,
        },
        "tolerance_sec": ALIGNMENT_TOLERANCE_SECONDS,
        "minimum_reliable_correlation": ALIGNMENT_MIN_CORRELATION,
        "lag_sign_convention": ("Positive lag means the summed stems trail the canonical mix."),
        "decoded_frames": {
            "mix": len(mix),
            "stem_sum": len(stem_sum),
            "frame_drift": len(stem_sum) - len(mix),
            "endpoint_drift_sec": (len(stem_sum) - len(mix)) / ALIGNMENT_SAMPLE_RATE,
        },
        "global": global_lag,
        "windows": window_lags,
        "maximum_absolute_lag_sec": max_abs_lag_sec,
        "all_segments_reliable": all_segments_reliable,
        "within_tolerance": (
            all(bool(item["within_tolerance"]) for item in reliable)
            if all_segments_reliable
            else None
        ),
        "interpretation": (
            "Alignment diagnostic candidates only. A candidate is not described as "
            "within tolerance unless every segment clears the correlation threshold; "
            "correlation and lag are not source-separation quality or "
            "transcription-accuracy measurements."
        ),
    }


def _endpoint_drift(
    reference_stats: dict[str, Any],
    candidate_stats: dict[str, Any],
) -> dict[str, Any]:
    reference_frames = int(reference_stats["decoded"]["sample_frames"])
    candidate_frames = int(candidate_stats["decoded"]["sample_frames"])
    frame_drift = candidate_frames - reference_frames
    probe_reference = reference_stats["probe"]["duration_sec"]
    probe_candidate = candidate_stats["probe"]["duration_sec"]
    return {
        "method": "difference in ffmpeg-decoded 44.1 kHz stereo sample frames",
        "reference_frames": reference_frames,
        "candidate_frames": candidate_frames,
        "frame_drift": frame_drift,
        "endpoint_drift_sec": frame_drift / SAMPLE_RATE,
        "probe_duration_drift_sec": (
            probe_candidate - probe_reference
            if probe_reference is not None and probe_candidate is not None
            else None
        ),
        "tolerance_frames": ENDPOINT_TOLERANCE_FRAMES,
        "tolerance_sec": ENDPOINT_TOLERANCE_FRAMES / SAMPLE_RATE,
        "within_tolerance": abs(frame_drift) <= ENDPOINT_TOLERANCE_FRAMES,
    }


def _rank_reconstruction_windows(
    mix_windows: list[float],
    difference_windows: list[float],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, (mix_rms, difference_rms) in enumerate(
        zip(mix_windows, difference_windows, strict=False)
    ):
        if mix_rms <= 1e-8:
            continue
        relative = difference_rms / mix_rms
        candidates.append(
            {
                "start_sec": index * WINDOW_SECONDS,
                "end_sec": (index + 1) * WINDOW_SECONDS,
                "mix_rms": mix_rms,
                "difference_rms": difference_rms,
                "difference_to_mix_db": 20 * math.log10(max(relative, 1e-12)),
                "interpretation": (
                    "High reconstruction discrepancy; review for deletion, "
                    "leakage, scaling, or separator artifacts."
                ),
                "status": "candidate_unconfirmed",
                "confirmed_by_listening": False,
            }
        )
    return sorted(
        candidates,
        key=lambda item: item["difference_to_mix_db"],
        reverse=True,
    )[:limit]


def _rank_vocal_balance_windows(
    vocal_windows: list[float],
    other_windows: list[float],
    mix_windows: list[float],
    *,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    low_vocal: list[dict[str, Any]] = []
    high_vocal: list[dict[str, Any]] = []
    for index, (vocal_rms, other_rms, mix_rms) in enumerate(
        zip(vocal_windows, other_windows, mix_windows, strict=False)
    ):
        if mix_rms <= 0.01:
            continue
        ratio_db = 20 * math.log10(max(vocal_rms, 1e-12) / max(other_rms, 1e-12))
        item = {
            "start_sec": index * WINDOW_SECONDS,
            "end_sec": (index + 1) * WINDOW_SECONDS,
            "vocal_to_other_db": ratio_db,
            "interpretation": (
                "Energy-ratio candidate only; listen before labeling leakage or deletion."
            ),
            "status": "candidate_unconfirmed",
            "confirmed_by_listening": False,
        }
        low_vocal.append(item)
        high_vocal.append(item)
    return {
        "possible_vocal_deletion_or_instrumental_section": sorted(
            low_vocal,
            key=lambda item: item["vocal_to_other_db"],
        )[:limit],
        "possible_instrument_leakage_or_vocal_dominant_section": sorted(
            high_vocal,
            key=lambda item: item["vocal_to_other_db"],
            reverse=True,
        )[:limit],
    }


def analyze_stem_set(
    mix_path: Path,
    stems: dict[str, Path],
) -> dict[str, Any]:
    if not stems:
        raise ValueError("At least one stem is required")
    mix_stats, mix_windows = audio_stats(mix_path)
    stem_stats: dict[str, Any] = {}
    stem_windows: dict[str, list[float]] = {}
    for name, path in sorted(stems.items()):
        stats, windows = audio_stats(path)
        endpoint_drift = _endpoint_drift(mix_stats, stats)
        stats["duration_drift_sec"] = endpoint_drift["probe_duration_drift_sec"]
        stats["decoded_frame_drift"] = endpoint_drift["frame_drift"]
        stats["decoded_endpoint_drift_sec"] = endpoint_drift["endpoint_drift_sec"]
        stats["endpoint_drift"] = endpoint_drift
        stem_stats[name] = stats
        stem_windows[name] = windows

    stem_names = sorted(stems)
    stem_paths = [stems[name] for name in stem_names]
    difference, difference_windows = reconstruction_stats(
        mix_path,
        stem_paths,
    )
    input_rms = mix_stats["rms"]
    difference_rms = difference["rms"]
    difference_frame_drift = (
        difference["decoded"]["sample_frames"] - mix_stats["decoded"]["sample_frames"]
    )
    reconstruction = {
        **difference,
        "relative_l2": difference_rms / input_rms if input_rms > 0 else None,
        "snr_db": (
            20 * math.log10(input_rms / difference_rms)
            if input_rms > 0 and difference_rms > 0
            else None
        ),
        "stem_order": stem_names,
        "decoded_frame_drift": difference_frame_drift,
        "decoded_endpoint_drift_sec": difference_frame_drift / SAMPLE_RATE,
    }
    alignment = alignment_stats(mix_path, stem_paths)
    frame_drifts = [int(stem_stats[name]["endpoint_drift"]["frame_drift"]) for name in stem_names]
    timeline = {
        "decoded_reference": {
            "sample_rate_hz": mix_stats["decoded"]["sample_rate_hz"],
            "channels": mix_stats["decoded"]["channels"],
            "sample_frames": mix_stats["decoded"]["sample_frames"],
        },
        "endpoint_tolerance": {
            "frames": ENDPOINT_TOLERANCE_FRAMES,
            "seconds": ENDPOINT_TOLERANCE_FRAMES / SAMPLE_RATE,
        },
        "maximum_absolute_stem_frame_drift": max(abs(frame_drift) for frame_drift in frame_drifts),
        "all_stems_within_endpoint_tolerance": all(
            bool(stem_stats[name]["endpoint_drift"]["within_tolerance"]) for name in stem_names
        ),
        "sum_alignment_within_tolerance": alignment["within_tolerance"],
    }

    vocal_windows = stem_windows.get("vocals")
    non_vocal_names = [name for name in sorted(stems) if name != "vocals"]
    review_candidates: dict[str, Any] = {
        "reconstruction_discrepancy": _rank_reconstruction_windows(
            mix_windows,
            difference_windows,
        )
    }
    if vocal_windows is not None and non_vocal_names:
        other_windows = [
            math.sqrt(
                sum(
                    stem_windows[name][index] ** 2
                    for name in non_vocal_names
                    if index < len(stem_windows[name])
                )
            )
            for index in range(len(vocal_windows))
        ]
        review_candidates.update(
            _rank_vocal_balance_windows(
                vocal_windows,
                other_windows,
                mix_windows,
            )
        )

    return {
        "schema_version": 2,
        "mix": mix_stats,
        "stems": stem_stats,
        "timeline": timeline,
        "alignment": alignment,
        "reconstruction": reconstruction,
        "review_candidates": review_candidates,
        "limitations": [
            "No isolated ground-truth stems are available.",
            (
                "Energy and reconstruction windows are review candidates, not "
                "confirmed leakage/deletion labels."
            ),
            (
                "EBU R128 integrated LUFS and true peak are measured when ffmpeg "
                "exposes them; RMS dBFS is retained only as a loudness proxy."
            ),
            (
                "Cross-correlation lag is an alignment diagnostic, not a source-"
                "separation or transcription-accuracy score."
            ),
            "Subjective listening notes must be added separately.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a separator stem set.")
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument(
        "--stem",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Stem name and path; repeat for every stem.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stems: dict[str, Path] = {}
    for value in args.stem:
        if "=" not in value:
            raise ValueError(f"Invalid --stem value: {value}")
        name, path = value.split("=", 1)
        stems[name] = Path(path).expanduser().resolve()
    result = analyze_stem_set(args.mix.expanduser().resolve(), stems)
    atomic_write_json(args.output.expanduser().resolve(), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
