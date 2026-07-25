# Task 008: Hyak batch experiment system

Status: ready after Task 007

## Objective

Scale reproducible baseline, ablation, and parameter experiments across authorized songs and excerpts.

## Requirements

- Implement idempotent run caching by input/config/model hashes.
- Add Slurm arrays from a manifest, not hard-coded paths.
- Support priority GPU and resumable checkpoint partitions.
- Trap interruptions and resume safe stages.
- Write central experiment indexes and sync selected results to Mac.
- Add resource use and failure-rate summaries.

## Acceptance criteria

- A failed/interrupted array can resume without duplicating completed runs.
- No heavy computation occurs on login nodes.
- Every output is traceable to a manifest row.
- Storage growth is bounded by retention rules.
- Important results survive scrubbed cleanup.

## Evidence

Codex: append evidence here.
