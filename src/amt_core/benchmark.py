from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

BENCHMARK_SPEC_SCHEMA = "amt-benchmark-spec/v1"
BENCHMARK_MANIFEST_SCHEMA = "amt-benchmark-manifest/v1"
REQUIRED_COVERAGE_TARGETS = {
    "chorus_or_harmony",
    "dense_accompaniment",
    "instrumental_intro_or_interlude",
    "lead_vocal",
    "vibrato_or_glissando",
    "weak_notes",
}


class BenchmarkError(ValueError):
    """Raised when a benchmark definition violates the evaluation policy."""


def _finite_non_negative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise BenchmarkError(f"{label} must be finite and non-negative")
    return number


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class BenchmarkExcerpt:
    excerpt_id: str
    start_sec: float
    duration_sec: float
    coverage_targets: tuple[str, ...]
    selection_basis: str

    @classmethod
    def from_dict(cls, value: Any) -> BenchmarkExcerpt:
        if not isinstance(value, dict):
            raise BenchmarkError("benchmark excerpt must be an object")
        coverage = value.get("coverage_targets")
        if not isinstance(coverage, list):
            raise BenchmarkError("coverage_targets must be an array")
        excerpt = cls(
            excerpt_id=value.get("excerpt_id"),
            start_sec=_finite_non_negative(value.get("start_sec"), label="start_sec"),
            duration_sec=_finite_non_negative(value.get("duration_sec"), label="duration_sec"),
            coverage_targets=tuple(coverage),
            selection_basis=value.get("selection_basis"),
        )
        excerpt.validate()
        return excerpt

    def validate(self) -> None:
        if not isinstance(self.excerpt_id, str) or not self.excerpt_id:
            raise BenchmarkError("excerpt_id is required")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        if any(character not in allowed for character in self.excerpt_id):
            raise BenchmarkError("excerpt_id must use lowercase ASCII letters, digits, '-' or '_'")
        _finite_non_negative(self.start_sec, label="start_sec")
        duration = _finite_non_negative(self.duration_sec, label="duration_sec")
        if duration <= 0:
            raise BenchmarkError("duration_sec must be positive")
        if len(set(self.coverage_targets)) != len(self.coverage_targets):
            raise BenchmarkError("coverage_targets must be unique")
        unsupported = sorted(set(self.coverage_targets) - REQUIRED_COVERAGE_TARGETS)
        if unsupported:
            raise BenchmarkError(f"unsupported coverage_targets: {unsupported}")
        if not self.coverage_targets:
            raise BenchmarkError("at least one coverage target is required")
        if not isinstance(self.selection_basis, str) or not self.selection_basis:
            raise BenchmarkError("selection_basis is required")

    def freeze_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "excerpt_id": self.excerpt_id,
            "start_sec": self.start_sec,
            "duration_sec": self.duration_sec,
            "end_sec": self.start_sec + self.duration_sec,
            "coverage_targets": list(self.coverage_targets),
            "selection_basis": self.selection_basis,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    benchmark_id: str
    project_id: str
    split: str
    song_group_id: str
    artist_group_id: str
    prior_system_exposure: bool
    excerpts: tuple[BenchmarkExcerpt, ...]
    schema: str = BENCHMARK_SPEC_SCHEMA

    @classmethod
    def from_dict(cls, value: Any) -> BenchmarkSpec:
        if not isinstance(value, dict):
            raise BenchmarkError("benchmark spec must be an object")
        raw_excerpts = value.get("excerpts")
        if not isinstance(raw_excerpts, list):
            raise BenchmarkError("excerpts must be an array")
        spec = cls(
            schema=value.get("schema"),
            benchmark_id=value.get("benchmark_id"),
            project_id=value.get("project_id"),
            split=value.get("split"),
            song_group_id=value.get("song_group_id"),
            artist_group_id=value.get("artist_group_id"),
            prior_system_exposure=value.get("prior_system_exposure"),
            excerpts=tuple(BenchmarkExcerpt.from_dict(item) for item in raw_excerpts),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.schema != BENCHMARK_SPEC_SCHEMA:
            raise BenchmarkError(f"unsupported benchmark spec schema: {self.schema!r}")
        for label, value in (
            ("benchmark_id", self.benchmark_id),
            ("project_id", self.project_id),
            ("song_group_id", self.song_group_id),
            ("artist_group_id", self.artist_group_id),
        ):
            if not isinstance(value, str) or not value:
                raise BenchmarkError(f"{label} is required")
        if self.split not in {"train", "development", "blind_test"}:
            raise BenchmarkError("split must be train, development, or blind_test")
        if not isinstance(self.prior_system_exposure, bool):
            raise BenchmarkError("prior_system_exposure must be boolean")
        if self.split == "blind_test" and self.prior_system_exposure:
            raise BenchmarkError("blind_test cannot have prior_system_exposure")
        if not self.excerpts:
            raise BenchmarkError("at least one excerpt is required")
        identifiers = [excerpt.excerpt_id for excerpt in self.excerpts]
        if len(set(identifiers)) != len(identifiers):
            raise BenchmarkError("excerpt_id values must be unique")
        ordered = sorted(self.excerpts, key=lambda excerpt: excerpt.start_sec)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.start_sec + previous.duration_sec > current.start_sec:
                raise BenchmarkError(
                    f"evaluation excerpts overlap: {previous.excerpt_id}, {current.excerpt_id}"
                )
        covered = {
            target for excerpt in self.excerpts for target in excerpt.coverage_targets
        }
        missing = sorted(REQUIRED_COVERAGE_TARGETS - covered)
        if missing:
            raise BenchmarkError(f"benchmark is missing required coverage targets: {missing}")

    def freeze_dict(self, *, canonical_audio_sha256: str) -> dict[str, Any]:
        self.validate()
        if (
            not isinstance(canonical_audio_sha256, str)
            or len(canonical_audio_sha256) != 64
            or any(character not in "0123456789abcdef" for character in canonical_audio_sha256)
        ):
            raise BenchmarkError("canonical_audio_sha256 is invalid")
        return {
            "schema": BENCHMARK_MANIFEST_SCHEMA,
            "benchmark_id": self.benchmark_id,
            "project_id": self.project_id,
            "split": self.split,
            "song_group_id": self.song_group_id,
            "artist_group_id": self.artist_group_id,
            "prior_system_exposure": self.prior_system_exposure,
            "canonical_audio_sha256": canonical_audio_sha256,
            "excerpts": [excerpt.freeze_dict() for excerpt in self.excerpts],
            "split_policy": {
                "unit": "artist_then_song",
                "same_song_cross_split_allowed": False,
                "blind_test_requires_no_prior_system_exposure": True,
            },
        }
