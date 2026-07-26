#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from amt_core.batch import BatchValidationError, load_batch_manifest
from amt_core.utils import atomic_write_json, sha256_file

PROFILES: dict[str, dict[str, Any]] = {
    "checkpoint-a40": {
        "account": "ckpt-stf",
        "partition": "ckpt",
        "qos": "ckpt-gpu",
        "cpus_per_task": 8,
        "mem": "64G",
        "time": "04:00:00",
        "gpus": "a40:1",
        "requeue": True,
    },
    "priority-l40s": {
        "account": "gpu-l40s-stf",
        "partition": "gpu-l40s",
        "qos": "normal",
        "cpus_per_task": 8,
        "mem": "64G",
        "time": "04:00:00",
        "gpus": "l40s:1",
        "requeue": False,
    },
    "cpu-smoke": {
        "account": "cpu-g2-stf",
        "partition": "cpu-g2",
        "qos": "normal",
        "cpus_per_task": 2,
        "mem": "8G",
        "time": "00:20:00",
        "gpus": None,
        "requeue": True,
    },
}


def _absolute(value: Path, *, label: str, must_exist: bool) -> Path:
    path = value.expanduser().resolve(strict=must_exist)
    if not path.is_absolute() or "," in str(path):
        raise BatchValidationError(f"{label} must be an absolute path without commas")
    return path


def build_array_command(
    *,
    manifest_path: Path,
    repo_root: Path,
    cache_root: Path,
    selected_root: Path,
    index_root: Path,
    profile_name: str,
    max_parallel: int,
    test_only: bool,
) -> list[str]:
    manifest = load_batch_manifest(manifest_path)
    profile = PROFILES[profile_name]
    last_index = len(manifest["rows"]) - 1
    array = f"0-{last_index}%{min(max_parallel, len(manifest['rows']))}"
    export = ",".join(
        [
            "ALL",
            f"AMT_BATCH_MANIFEST={manifest_path}",
            f"AMT_BATCH_CACHE_ROOT={cache_root}",
            f"AMT_BATCH_SELECTED_ROOT={selected_root}",
            f"AMT_BATCH_INDEX_ROOT={index_root}",
            f"AMT_REPO_ROOT={repo_root}",
        ]
    )
    command = [
        "sbatch",
        "--parsable",
        f"--job-name=amt-t008-{manifest['batch_id'][:40]}",
        f"--array={array}",
        f"--account={profile['account']}",
        f"--partition={profile['partition']}",
        f"--qos={profile['qos']}",
        "--nodes=1",
        "--ntasks=1",
        f"--cpus-per-task={profile['cpus_per_task']}",
        f"--mem={profile['mem']}",
        f"--time={profile['time']}",
        f"--export={export}",
        f"--output={repo_root.parent}/logs/%x-%A_%a.out",
        f"--error={repo_root.parent}/logs/%x-%A_%a.err",
    ]
    if profile["gpus"] is not None:
        command.append(f"--gpus={profile['gpus']}")
    if profile["requeue"]:
        command.extend(["--requeue", "--signal=B:TERM@120"])
    if test_only:
        command.append("--test-only")
    command.append(str(repo_root / "slurm/30_task008_batch_array.slurm"))
    return command


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a frozen Task008 Hyak batch manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--selected-root", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--test-only", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if os.environ.get("SLURM_JOB_ID") or shutil.which("sbatch") is None:
        raise SystemExit("submit_batch.py requires a non-compute host with sbatch available")
    if args.max_parallel < 1:
        raise SystemExit("--max-parallel must be positive")
    manifest_path = _absolute(args.manifest, label="manifest", must_exist=True)
    repo_root = _absolute(args.repo_root, label="repo root", must_exist=True)
    cache_root = _absolute(args.cache_root, label="cache root", must_exist=False)
    selected_root = _absolute(args.selected_root, label="selected root", must_exist=False)
    index_root = _absolute(args.index_root, label="index root", must_exist=False)
    for root in (cache_root, selected_root, index_root, repo_root.parent / "logs"):
        root.mkdir(parents=True, exist_ok=True)

    array_command = build_array_command(
        manifest_path=manifest_path,
        repo_root=repo_root,
        cache_root=cache_root,
        selected_root=selected_root,
        index_root=index_root,
        profile_name=args.profile,
        max_parallel=args.max_parallel,
        test_only=args.test_only,
    )
    array_result = subprocess.run(
        array_command,
        check=True,
        capture_output=True,
        text=True,
    )
    if args.test_only:
        print(array_result.stdout.strip() or array_result.stderr.strip())
        return 0

    array_job_id = array_result.stdout.strip().split(";", 1)[0]
    if not array_job_id.isdigit():
        raise SystemExit(f"sbatch returned an unexpected job ID: {array_result.stdout!r}")
    manifest = load_batch_manifest(manifest_path)
    submission_path = index_root / manifest["batch_id"] / f"submission-{array_job_id}.json"
    submission = {
        "schema_version": 1,
        "batch_id": manifest["batch_id"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "profile": args.profile,
        "row_count": len(manifest["rows"]),
        "max_parallel": min(args.max_parallel, len(manifest["rows"])),
        "array_job_id": array_job_id,
        "finalizer_job_id": None,
        "finalizer_status": "pending",
        "array_command": array_command,
        "finalizer_command": None,
    }
    atomic_write_json(submission_path, submission)
    export = ",".join(
        [
            "ALL",
            f"AMT_BATCH_MANIFEST={manifest_path}",
            f"AMT_BATCH_CACHE_ROOT={cache_root}",
            f"AMT_BATCH_SELECTED_ROOT={selected_root}",
            f"AMT_BATCH_INDEX_ROOT={index_root}",
            f"AMT_REPO_ROOT={repo_root}",
            f"AMT_BATCH_ARRAY_JOB_ID={array_job_id}",
        ]
    )
    finalizer_command = [
        "sbatch",
        "--parsable",
        f"--dependency=afterany:{array_job_id}",
        f"--job-name=amt-t008-final-{array_job_id}",
        "--account=cpu-g2-stf",
        "--partition=cpu-g2",
        "--qos=normal",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=2",
        "--mem=8G",
        "--time=00:20:00",
        f"--export={export}",
        f"--output={repo_root.parent}/logs/%x-%j.out",
        f"--error={repo_root.parent}/logs/%x-%j.err",
        str(repo_root / "slurm/31_task008_batch_finalize.slurm"),
    ]
    submission["finalizer_command"] = finalizer_command
    try:
        finalizer_result = subprocess.run(
            finalizer_command,
            check=True,
            capture_output=True,
            text=True,
        )
        finalizer_job_id = finalizer_result.stdout.strip().split(";", 1)[0]
        if not finalizer_job_id.isdigit():
            raise RuntimeError(
                f"finalizer sbatch returned an unexpected job ID: {finalizer_result.stdout!r}"
            )
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        submission["finalizer_status"] = "failed"
        submission["finalizer_error"] = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            submission["finalizer_stdout"] = exc.stdout
            submission["finalizer_stderr"] = exc.stderr
        atomic_write_json(submission_path, submission)
        raise
    submission["finalizer_job_id"] = finalizer_job_id
    submission["finalizer_status"] = "submitted"
    atomic_write_json(submission_path, submission)
    print(json.dumps(submission, sort_keys=True))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
