# Task 003: Source-separation candidate benchmark

Status: blocked by Task 002

## Objective

Produce authorized vocal, drum, bass, and residual stem candidates while measuring their effect on downstream transcription.

## Requirements

- Isolate the separator environment.
- List available models and select at least two justified candidates: a vocal-quality model and a multi-stem model.
- Pin package/model versions and hashes.
- Preserve each stem set separately. Never overwrite one model with another.
- Create objective checks: sum/reconstruction error where applicable, clipping, duration drift, loudness, and silence.
- Create subjective listening notes on representative passages.
- Run at least one downstream AMT worker on the vocal stems to test whether separation helps or hurts.

## Acceptance criteria

- Two reproducible stem sets with manifests.
- No timeline drift relative to canonical audio beyond documented tolerance.
- Downstream candidate note statistics are compared.
- Separation deletion/leakage examples are time-stamped.
- A default and fallback separator preset are selected based on evidence.

## Evidence

Codex: append evidence here.
