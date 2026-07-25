from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .events import NoteEvent

FUSION_SCHEMA = "amt-deterministic-fusion/v1"
CALIBRATION_SCHEMA = "amt-isotonic-calibration/v1"


class FusionError(ValueError):
    """Raised when candidate fusion inputs or configuration are invalid."""


def _unit_interval(value: float, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FusionError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise FusionError(f"{label} must be finite and in [0, 1]")
    return number


def _positive(value: float, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FusionError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise FusionError(f"{label} must be finite and positive")
    return number


def _safe_identifier(value: str, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise FusionError(f"{label} is missing or unsafe")
    return value


@dataclass(frozen=True, slots=True)
class SourceProfile:
    label: str
    reliability: float
    stem_quality: float
    instrument_presence: float

    def validate(self) -> None:
        _safe_identifier(self.label, label="source label")
        _unit_interval(self.reliability, label=f"{self.label} reliability")
        _unit_interval(self.stem_quality, label=f"{self.label} stem_quality")
        _unit_interval(
            self.instrument_presence,
            label=f"{self.label} instrument_presence",
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "label": self.label,
            "reliability": self.reliability,
            "stem_quality": self.stem_quality,
            "instrument_presence": self.instrument_presence,
        }

    @classmethod
    def from_dict(cls, value: Any) -> SourceProfile:
        if not isinstance(value, dict):
            raise FusionError("source profile must be an object")
        profile = cls(
            label=value.get("label"),
            reliability=value.get("reliability"),
            stem_quality=value.get("stem_quality"),
            instrument_presence=value.get("instrument_presence"),
        )
        profile.validate()
        return profile


DEFAULT_FEATURE_WEIGHTS = {
    "source_agreement": 0.35,
    "worker_reliability": 0.25,
    "stem_quality": 0.10,
    "beat_phase": 0.05,
    "duration": 0.05,
    "local_continuity": 0.10,
    "register": 0.05,
    "instrument_presence": 0.05,
}


@dataclass(frozen=True, slots=True)
class FusionConfig:
    onset_tolerance_sec: float = 0.06
    pitch_tolerance_semitones: float = 0.5
    duration_tolerance_sec: float = 0.35
    duration_tolerance_ratio: float = 1.0
    beat_tolerance_sec: float = 0.08
    plausible_duration_min_sec: float = 0.12
    plausible_duration_max_sec: float = 2.5
    continuity_gap_sec: float = 2.0
    continuity_pitch_span_semitones: float = 12.0
    register_low_midi: float = 36.0
    register_high_midi: float = 84.0
    register_taper_semitones: float = 12.0
    minimum_raw_score: float = 0.45
    competing_onset_tolerance_sec: float = 0.06
    minimum_final_duration_sec: float = 0.04
    target_instrument: str = "voice"
    feature_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_FEATURE_WEIGHTS))

    def validate(self) -> None:
        for label, value in (
            ("onset_tolerance_sec", self.onset_tolerance_sec),
            ("pitch_tolerance_semitones", self.pitch_tolerance_semitones),
            ("duration_tolerance_sec", self.duration_tolerance_sec),
            ("duration_tolerance_ratio", self.duration_tolerance_ratio),
            ("beat_tolerance_sec", self.beat_tolerance_sec),
            ("plausible_duration_min_sec", self.plausible_duration_min_sec),
            ("plausible_duration_max_sec", self.plausible_duration_max_sec),
            ("continuity_gap_sec", self.continuity_gap_sec),
            (
                "continuity_pitch_span_semitones",
                self.continuity_pitch_span_semitones,
            ),
            ("register_taper_semitones", self.register_taper_semitones),
            (
                "competing_onset_tolerance_sec",
                self.competing_onset_tolerance_sec,
            ),
            ("minimum_final_duration_sec", self.minimum_final_duration_sec),
        ):
            _positive(value, label=label)
        if not 0 <= self.register_low_midi < self.register_high_midi <= 127:
            raise FusionError("register bounds must be ordered inside [0, 127]")
        if self.plausible_duration_max_sec <= self.plausible_duration_min_sec:
            raise FusionError("plausible duration bounds must be increasing")
        _unit_interval(self.minimum_raw_score, label="minimum_raw_score")
        if not isinstance(self.target_instrument, str) or not self.target_instrument:
            raise FusionError("target_instrument is required")
        if set(self.feature_weights) != set(DEFAULT_FEATURE_WEIGHTS):
            raise FusionError(
                f"feature_weights must contain exactly {sorted(DEFAULT_FEATURE_WEIGHTS)}"
            )
        for label, weight in self.feature_weights.items():
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or weight < 0
            ):
                raise FusionError(f"feature weight {label} must be non-negative")
        if not any(self.feature_weights.values()):
            raise FusionError("at least one feature weight must be positive")

    def without_feature(self, feature: str) -> FusionConfig:
        if feature not in self.feature_weights:
            raise FusionError(f"unknown feature: {feature}")
        weights = dict(self.feature_weights)
        weights[feature] = 0.0
        if not any(weights.values()):
            raise FusionError("cannot disable every feature")
        return replace(self, feature_weights=weights)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "onset_tolerance_sec": self.onset_tolerance_sec,
            "pitch_tolerance_semitones": self.pitch_tolerance_semitones,
            "duration_tolerance_sec": self.duration_tolerance_sec,
            "duration_tolerance_ratio": self.duration_tolerance_ratio,
            "beat_tolerance_sec": self.beat_tolerance_sec,
            "plausible_duration_min_sec": self.plausible_duration_min_sec,
            "plausible_duration_max_sec": self.plausible_duration_max_sec,
            "continuity_gap_sec": self.continuity_gap_sec,
            "continuity_pitch_span_semitones": (self.continuity_pitch_span_semitones),
            "register_low_midi": self.register_low_midi,
            "register_high_midi": self.register_high_midi,
            "register_taper_semitones": self.register_taper_semitones,
            "minimum_raw_score": self.minimum_raw_score,
            "competing_onset_tolerance_sec": (self.competing_onset_tolerance_sec),
            "minimum_final_duration_sec": self.minimum_final_duration_sec,
            "target_instrument": self.target_instrument,
            "feature_weights": dict(sorted(self.feature_weights.items())),
        }

    @classmethod
    def from_dict(cls, value: Any) -> FusionConfig:
        if not isinstance(value, dict):
            raise FusionError("fusion config must be an object")
        expected = {
            "onset_tolerance_sec",
            "pitch_tolerance_semitones",
            "duration_tolerance_sec",
            "duration_tolerance_ratio",
            "beat_tolerance_sec",
            "plausible_duration_min_sec",
            "plausible_duration_max_sec",
            "continuity_gap_sec",
            "continuity_pitch_span_semitones",
            "register_low_midi",
            "register_high_midi",
            "register_taper_semitones",
            "minimum_raw_score",
            "competing_onset_tolerance_sec",
            "minimum_final_duration_sec",
            "target_instrument",
            "feature_weights",
        }
        unknown = set(value) - expected
        if unknown:
            raise FusionError(f"fusion config contains unknown fields: {sorted(unknown)}")
        config = cls(**value)
        config.validate()
        return config


@dataclass(frozen=True, slots=True)
class CalibrationProvenance:
    calibration_id: str
    split: str
    benchmark_sha256: str
    candidate_sha256: tuple[str, ...]
    feature_model_sha256: str

    def validate(self) -> None:
        _safe_identifier(self.calibration_id, label="calibration_id")
        if self.split != "development":
            raise FusionError("confidence calibration is allowed on development only")
        hashes = (
            self.benchmark_sha256,
            *self.candidate_sha256,
            self.feature_model_sha256,
        )
        if not self.candidate_sha256:
            raise FusionError("calibration provenance requires candidate hashes")
        for value in hashes:
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise FusionError("calibration provenance contains an invalid SHA-256")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "calibration_id": self.calibration_id,
            "split": self.split,
            "benchmark_sha256": self.benchmark_sha256,
            "candidate_sha256": list(self.candidate_sha256),
            "feature_model_sha256": self.feature_model_sha256,
        }


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    provenance: CalibrationProvenance
    upper_bounds: tuple[float, ...]
    probabilities: tuple[float, ...]
    sample_count: int
    positive_count: int
    schema: str = CALIBRATION_SCHEMA

    def validate(self) -> None:
        if self.schema != CALIBRATION_SCHEMA:
            raise FusionError(f"unsupported calibration schema: {self.schema!r}")
        self.provenance.validate()
        if (
            not self.upper_bounds
            or len(self.upper_bounds) != len(self.probabilities)
            or tuple(sorted(self.upper_bounds)) != self.upper_bounds
            or len(set(self.upper_bounds)) != len(self.upper_bounds)
        ):
            raise FusionError("calibration bounds must be non-empty and increasing")
        for value in self.upper_bounds:
            _unit_interval(value, label="calibration upper bound")
        for value in self.probabilities:
            _unit_interval(value, label="calibration probability")
        if tuple(sorted(self.probabilities)) != self.probabilities:
            raise FusionError("calibration probabilities must be non-decreasing")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count <= 0
            or isinstance(self.positive_count, bool)
            or not isinstance(self.positive_count, int)
            or not 0 <= self.positive_count <= self.sample_count
        ):
            raise FusionError("calibration sample counts are invalid")

    def predict(self, raw_score: float) -> float:
        self.validate()
        score = _unit_interval(raw_score, label="raw_score")
        index = bisect.bisect_left(self.upper_bounds, score)
        if index == len(self.upper_bounds):
            index -= 1
        return self.probabilities[index]

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "provenance": self.provenance.to_dict(),
            "upper_bounds": list(self.upper_bounds),
            "probabilities": list(self.probabilities),
            "sample_count": self.sample_count,
            "positive_count": self.positive_count,
        }

    @classmethod
    def from_dict(cls, value: Any) -> IsotonicCalibrator:
        if not isinstance(value, dict):
            raise FusionError("calibration must be an object")
        raw_provenance = value.get("provenance")
        if not isinstance(raw_provenance, dict):
            raise FusionError("calibration provenance must be an object")
        calibrator = cls(
            schema=value.get("schema"),
            provenance=CalibrationProvenance(
                calibration_id=raw_provenance.get("calibration_id"),
                split=raw_provenance.get("split"),
                benchmark_sha256=raw_provenance.get("benchmark_sha256"),
                candidate_sha256=tuple(raw_provenance.get("candidate_sha256", [])),
                feature_model_sha256=raw_provenance.get("feature_model_sha256"),
            ),
            upper_bounds=tuple(value.get("upper_bounds", [])),
            probabilities=tuple(value.get("probabilities", [])),
            sample_count=value.get("sample_count"),
            positive_count=value.get("positive_count"),
        )
        calibrator.validate()
        return calibrator


def fusion_feature_model_sha256(
    config: FusionConfig,
    profiles: Mapping[str, SourceProfile],
) -> str:
    """Fingerprint every input that can change clustering or raw scores."""

    config.validate()
    if not profiles:
        raise FusionError("feature model requires source profiles")
    for label, profile in profiles.items():
        profile.validate()
        if label != profile.label:
            raise FusionError("source profile key must match profile label")
    score_config = config.to_dict()
    score_config["minimum_raw_score"] = None
    payload = {
        "schema": "amt-fusion-feature-model/v1",
        "score_config": score_config,
        "profiles": [profiles[label].to_dict() for label in sorted(profiles)],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def fit_isotonic_calibrator(
    raw_scores: Sequence[float],
    outcomes: Sequence[bool],
    provenance: CalibrationProvenance,
) -> IsotonicCalibrator:
    """Fit deterministic pool-adjacent-violators calibration on development."""

    provenance.validate()
    if len(raw_scores) != len(outcomes) or not raw_scores:
        raise FusionError("calibration scores and outcomes must have equal non-zero length")
    records = sorted(
        (
            _unit_interval(score, label="calibration raw score"),
            bool(outcome),
        )
        for score, outcome in zip(raw_scores, outcomes, strict=True)
    )
    grouped: list[dict[str, float]] = []
    for score, outcome in records:
        if grouped and grouped[-1]["upper"] == score:
            grouped[-1]["count"] += 1
            grouped[-1]["positive"] += int(outcome)
        else:
            grouped.append(
                {
                    "upper": score,
                    "count": 1,
                    "positive": int(outcome),
                }
            )

    blocks: list[dict[str, float]] = []
    for group in grouped:
        blocks.append(dict(group))
        while len(blocks) >= 2:
            previous = blocks[-2]
            current = blocks[-1]
            previous_rate = previous["positive"] / previous["count"]
            current_rate = current["positive"] / current["count"]
            if previous_rate <= current_rate:
                break
            blocks[-2:] = [
                {
                    "upper": current["upper"],
                    "count": previous["count"] + current["count"],
                    "positive": previous["positive"] + current["positive"],
                }
            ]

    calibrator = IsotonicCalibrator(
        provenance=provenance,
        upper_bounds=tuple(float(block["upper"]) for block in blocks),
        probabilities=tuple(float(block["positive"] / block["count"]) for block in blocks),
        sample_count=len(records),
        positive_count=sum(outcome for _score, outcome in records),
    )
    calibrator.validate()
    return calibrator


@dataclass(frozen=True, slots=True)
class CandidateMember:
    source_label: str
    event: NoteEvent

    @property
    def duration_sec(self) -> float:
        return self.event.offset_sec - self.event.onset_sec


@dataclass(slots=True)
class CandidateCluster:
    cluster_id: str
    members: list[CandidateMember]
    onset_sec: float = 0.0
    offset_sec: float = 0.0
    pitch_midi: float = 0.0
    features: dict[str, float | None] = field(default_factory=dict)
    raw_score: float = 0.0

    def source_labels(self) -> tuple[str, ...]:
        return tuple(sorted(member.source_label for member in self.members))

    def source_event_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(f"{member.source_label}:{member.event.event_id}" for member in self.members)
        )


@dataclass(frozen=True, slots=True)
class FusionResult:
    final_events: tuple[NoteEvent, ...]
    clusters: tuple[dict[str, Any], ...]
    rejected: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _weighted_median(values: Sequence[tuple[float, float]]) -> float:
    ordered = sorted(values)
    total = sum(weight for _value, weight in ordered)
    threshold = total / 2
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return float(value)
    return float(ordered[-1][0])


def _member_weight(member: CandidateMember, profile: SourceProfile) -> float:
    return max(1e-9, 0.7 * profile.reliability + 0.3 * profile.stem_quality)


def _refresh_representative(
    cluster: CandidateCluster,
    profiles: Mapping[str, SourceProfile],
) -> None:
    weighted = [
        (member, _member_weight(member, profiles[member.source_label]))
        for member in cluster.members
    ]
    cluster.onset_sec = _weighted_median(
        [(member.event.onset_sec, weight) for member, weight in weighted]
    )
    duration = _weighted_median([(member.duration_sec, weight) for member, weight in weighted])
    cluster.offset_sec = cluster.onset_sec + duration
    cluster.pitch_midi = _weighted_median(
        [(member.event.pitch_midi, weight) for member, weight in weighted]
    )


def _compatible(
    cluster: CandidateCluster,
    member: CandidateMember,
    config: FusionConfig,
) -> bool:
    if member.source_label in cluster.source_labels():
        return False
    for existing in cluster.members:
        duration_tolerance = max(
            config.duration_tolerance_sec,
            config.duration_tolerance_ratio * min(member.duration_sec, existing.duration_sec),
        )
        if (
            abs(member.event.onset_sec - existing.event.onset_sec) > config.onset_tolerance_sec
            or abs(member.event.pitch_midi - existing.event.pitch_midi)
            > config.pitch_tolerance_semitones
            or abs(member.duration_sec - existing.duration_sec) > duration_tolerance
        ):
            return False
    return True


def cluster_candidates(
    candidates: Mapping[str, Iterable[NoteEvent]],
    profiles: Mapping[str, SourceProfile],
    config: FusionConfig | None = None,
) -> list[CandidateCluster]:
    config = config or FusionConfig()
    config.validate()
    if not candidates:
        raise FusionError("at least one candidate source is required")
    if set(candidates) != set(profiles):
        raise FusionError("candidate and source-profile labels must match exactly")
    for label, profile in profiles.items():
        profile.validate()
        if label != profile.label:
            raise FusionError("source profile key must match profile label")

    members: list[CandidateMember] = []
    event_ids: set[tuple[str, str]] = set()
    for label, events in candidates.items():
        for event in events:
            event.validate()
            identity = (label, event.event_id)
            if identity in event_ids:
                raise FusionError(f"duplicate candidate event identity: {identity}")
            event_ids.add(identity)
            members.append(CandidateMember(label, event))
    members.sort(
        key=lambda member: (
            member.event.onset_sec,
            member.event.pitch_midi,
            member.event.offset_sec,
            member.source_label,
            member.event.event_id,
        )
    )

    clusters: list[CandidateCluster] = []
    for member in members:
        compatible = [cluster for cluster in clusters if _compatible(cluster, member, config)]
        if compatible:
            cluster = min(
                compatible,
                key=lambda item: (
                    abs(item.onset_sec - member.event.onset_sec) / config.onset_tolerance_sec
                    + abs(item.pitch_midi - member.event.pitch_midi)
                    / config.pitch_tolerance_semitones
                    + abs((item.offset_sec - item.onset_sec) - member.duration_sec)
                    / config.duration_tolerance_sec,
                    item.cluster_id,
                ),
            )
            cluster.members.append(member)
            _refresh_representative(cluster, profiles)
        else:
            cluster = CandidateCluster(
                cluster_id=f"cluster-{len(clusters) + 1:06d}",
                members=[member],
            )
            _refresh_representative(cluster, profiles)
            clusters.append(cluster)
    return clusters


def _nearest_beat_score(
    onset_sec: float,
    beat_times_sec: Sequence[float],
    tolerance_sec: float,
) -> float | None:
    if not beat_times_sec:
        return None
    index = bisect.bisect_left(beat_times_sec, onset_sec)
    nearby = []
    if index < len(beat_times_sec):
        nearby.append(abs(beat_times_sec[index] - onset_sec))
    if index:
        nearby.append(abs(beat_times_sec[index - 1] - onset_sec))
    distance = min(nearby)
    return max(0.0, 1.0 - distance / tolerance_sec)


def _duration_score(duration_sec: float, config: FusionConfig) -> float:
    short = min(1.0, duration_sec / config.plausible_duration_min_sec)
    long = min(1.0, config.plausible_duration_max_sec / duration_sec)
    return short * long


def _register_score(pitch_midi: float, config: FusionConfig) -> float:
    if config.register_low_midi <= pitch_midi <= config.register_high_midi:
        return 1.0
    distance = (
        config.register_low_midi - pitch_midi
        if pitch_midi < config.register_low_midi
        else pitch_midi - config.register_high_midi
    )
    return max(0.0, 1.0 - distance / config.register_taper_semitones)


def score_clusters(
    clusters: Sequence[CandidateCluster],
    profiles: Mapping[str, SourceProfile],
    config: FusionConfig | None = None,
    *,
    beat_times_sec: Iterable[float] = (),
) -> None:
    config = config or FusionConfig()
    config.validate()
    beats = sorted(float(value) for value in beat_times_sec)
    if any(not math.isfinite(value) or value < 0 for value in beats) or any(
        current <= previous for previous, current in zip(beats, beats[1:], strict=False)
    ):
        raise FusionError("beat times must be finite, non-negative, and increasing")
    ordered = sorted(clusters, key=lambda cluster: (cluster.onset_sec, cluster.cluster_id))
    onset_groups: list[list[CandidateCluster]] = []
    for cluster in ordered:
        if (
            onset_groups
            and cluster.onset_sec - onset_groups[-1][0].onset_sec
            <= config.competing_onset_tolerance_sec
        ):
            onset_groups[-1].append(cluster)
        else:
            onset_groups.append([cluster])

    previous_group: list[CandidateCluster] = []
    for group in onset_groups:
        for cluster in group:
            weighted_profiles = [
                (
                    profiles[member.source_label],
                    _member_weight(member, profiles[member.source_label]),
                )
                for member in sorted(
                    cluster.members,
                    key=lambda item: item.source_label,
                )
            ]
            reliability_weights = [weight for _profile, weight in weighted_profiles]
            weight_total = sum(reliability_weights)
            reliability = (
                sum(profile.reliability * weight for profile, weight in weighted_profiles)
                / weight_total
            )
            stem_quality = (
                sum(profile.stem_quality * weight for profile, weight in weighted_profiles)
                / weight_total
            )
            instrument_presence = (
                sum(profile.instrument_presence * weight for profile, weight in weighted_profiles)
                / weight_total
            )
            instrument_match_fraction = sum(
                member.event.instrument == config.target_instrument for member in cluster.members
            ) / len(cluster.members)
            continuity = 0.5
            eligible_previous = [
                previous
                for previous in previous_group
                if cluster.onset_sec - previous.onset_sec <= config.continuity_gap_sec
            ]
            if eligible_previous:
                continuity = max(
                    max(
                        0.0,
                        1.0
                        - abs(cluster.pitch_midi - previous.pitch_midi)
                        / config.continuity_pitch_span_semitones,
                    )
                    for previous in eligible_previous
                )
            features: dict[str, float | None] = {
                "source_agreement": len(cluster.source_labels()) / len(profiles),
                "worker_reliability": reliability,
                "stem_quality": stem_quality,
                "beat_phase": _nearest_beat_score(
                    cluster.onset_sec,
                    beats,
                    config.beat_tolerance_sec,
                ),
                "duration": _duration_score(
                    cluster.offset_sec - cluster.onset_sec,
                    config,
                ),
                "local_continuity": continuity,
                "register": _register_score(cluster.pitch_midi, config),
                "instrument_presence": (instrument_presence * instrument_match_fraction),
            }
            available_weight = sum(
                config.feature_weights[name]
                for name, value in features.items()
                if value is not None
            )
            if available_weight <= 0:
                raise FusionError("no weighted feature is available for a cluster")
            cluster.features = features
            cluster.raw_score = (
                sum(
                    config.feature_weights[name] * value
                    for name, value in features.items()
                    if value is not None
                )
                / available_weight
            )
        previous_group = group


def _cluster_record(
    cluster: CandidateCluster,
    *,
    calibrated_confidence: float | None,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id,
        "onset_sec": cluster.onset_sec,
        "offset_sec": cluster.offset_sec,
        "pitch_midi": cluster.pitch_midi,
        "source_labels": list(cluster.source_labels()),
        "source_event_ids": list(cluster.source_event_ids()),
        "features": cluster.features,
        "raw_score": cluster.raw_score,
        "calibrated_confidence": calibrated_confidence,
        "status": status,
        "reason": reason,
    }


def fuse_main_melody(
    candidates: Mapping[str, Iterable[NoteEvent]],
    profiles: Mapping[str, SourceProfile],
    *,
    fusion_run_id: str,
    config: FusionConfig | None = None,
    calibrator: IsotonicCalibrator | None = None,
    beat_times_sec: Iterable[float] = (),
) -> FusionResult:
    """Fuse note candidates into one deterministic, provenance-rich melody."""

    _safe_identifier(fusion_run_id, label="fusion_run_id")
    config = config or FusionConfig()
    config.validate()
    if calibrator is not None:
        calibrator.validate()
        if calibrator.provenance.feature_model_sha256 != fusion_feature_model_sha256(
            config,
            profiles,
        ):
            raise FusionError("calibration does not match the fusion config and source profiles")
    materialized = {label: list(events) for label, events in candidates.items()}
    clusters = cluster_candidates(materialized, profiles, config)
    score_clusters(clusters, profiles, config, beat_times_sec=beat_times_sec)
    rejected: dict[str, tuple[str, float | None]] = {}
    eligible: list[CandidateCluster] = []
    confidences: dict[str, float | None] = {}
    for cluster in clusters:
        confidence = calibrator.predict(cluster.raw_score) if calibrator is not None else None
        confidences[cluster.cluster_id] = confidence
        if cluster.raw_score < config.minimum_raw_score:
            rejected[cluster.cluster_id] = ("below_minimum_raw_score", confidence)
        else:
            eligible.append(cluster)

    onset_groups: list[list[CandidateCluster]] = []
    for cluster in sorted(
        eligible,
        key=lambda item: (item.onset_sec, item.cluster_id),
    ):
        if (
            onset_groups
            and cluster.onset_sec - onset_groups[-1][0].onset_sec
            <= config.competing_onset_tolerance_sec
        ):
            onset_groups[-1].append(cluster)
        else:
            onset_groups.append([cluster])

    selected: list[CandidateCluster] = []
    for group in onset_groups:
        winner = max(
            group,
            key=lambda item: (
                item.raw_score,
                len(item.source_labels()),
                -item.onset_sec,
                -item.pitch_midi,
                item.cluster_id,
            ),
        )
        selected.append(winner)
        for cluster in group:
            if cluster is not winner:
                rejected[cluster.cluster_id] = (
                    f"competing_onset_lost_to:{winner.cluster_id}",
                    confidences[cluster.cluster_id],
                )

    selected.sort(key=lambda item: (item.onset_sec, item.cluster_id))
    surviving_reversed: list[CandidateCluster] = []
    next_survivor: CandidateCluster | None = None
    for cluster in reversed(selected):
        proposed_offset = cluster.offset_sec
        if next_survivor is not None and proposed_offset > next_survivor.onset_sec:
            proposed_offset = next_survivor.onset_sec
        if proposed_offset - cluster.onset_sec < config.minimum_final_duration_sec:
            rejected[cluster.cluster_id] = (
                "overlap_would_create_too_short_final_note",
                confidences[cluster.cluster_id],
            )
            continue
        surviving_reversed.append(cluster)
        next_survivor = cluster
    selected = list(reversed(surviving_reversed))

    final_events: list[NoteEvent] = []
    for index, cluster in enumerate(selected):
        offset = cluster.offset_sec
        offset_clipped = False
        if index + 1 < len(selected) and offset > selected[index + 1].onset_sec:
            offset = selected[index + 1].onset_sec
            offset_clipped = True
        confidence = confidences[cluster.cluster_id]
        tags = ["final", "main-melody", "deterministic-fusion-v1"]
        tags.append("confidence-calibrated" if confidence is not None else "confidence-unavailable")
        if offset_clipped:
            tags.append("offset-clipped-at-next-onset")
        final_events.append(
            NoteEvent(
                event_id=f"{fusion_run_id}:fusion:{len(final_events):06d}",
                track_id=f"{fusion_run_id}:main-melody",
                onset_sec=cluster.onset_sec,
                offset_sec=offset,
                pitch_midi=cluster.pitch_midi,
                quantized_pitch_midi=round(cluster.pitch_midi),
                confidence=confidence,
                instrument=config.target_instrument,
                is_main_melody_candidate=True,
                source_run_id=fusion_run_id,
                source_model="amt-studio/deterministic-fusion-v1",
                source_event_ids=list(cluster.source_event_ids()),
                tags=tags,
                extra={
                    "fusion_schema": FUSION_SCHEMA,
                    "cluster_id": cluster.cluster_id,
                    "source_labels": list(cluster.source_labels()),
                    "features": cluster.features,
                    "raw_score": cluster.raw_score,
                    "calibration_id": (
                        calibrator.provenance.calibration_id if calibrator is not None else None
                    ),
                    "representative": "profile-weighted-median",
                    "offset_clipped_at_next_onset": offset_clipped,
                },
            )
        )

    selected_ids = {event.extra["cluster_id"] for event in final_events}
    cluster_records = tuple(
        _cluster_record(
            cluster,
            calibrated_confidence=confidences[cluster.cluster_id],
            status=("selected" if cluster.cluster_id in selected_ids else "rejected"),
            reason=(
                None if cluster.cluster_id in selected_ids else rejected[cluster.cluster_id][0]
            ),
        )
        for cluster in clusters
    )
    rejected_records = tuple(record for record in cluster_records if record["status"] == "rejected")
    input_event_count = sum(len(events) for events in materialized.values())
    represented_event_ids = {
        source_event_id
        for record in cluster_records
        for source_event_id in record["source_event_ids"]
    }
    if len(represented_event_ids) != input_event_count:
        raise FusionError("candidate provenance is incomplete or duplicated")
    manifest_base = {
        "schema": FUSION_SCHEMA,
        "fusion_run_id": fusion_run_id,
        "mode": "main_melody",
        "config": config.to_dict(),
        "sources": [profiles[label].to_dict() for label in sorted(profiles)],
        "calibration": (calibrator.to_dict() if calibrator is not None else None),
        "input_event_count": input_event_count,
        "cluster_count": len(clusters),
        "selected_event_count": len(final_events),
        "rejected_cluster_count": len(rejected_records),
        "all_eligible_candidates_preserved": True,
        "final_note_provenance_complete": all(event.source_event_ids for event in final_events),
        "missing_feature_policy": "renormalize_available_feature_weights",
    }
    manifest_hash = hashlib.sha256(
        json.dumps(
            manifest_base,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest = {**manifest_base, "manifest_payload_sha256": manifest_hash}
    return FusionResult(
        final_events=tuple(final_events),
        clusters=cluster_records,
        rejected=rejected_records,
        manifest=manifest,
    )
