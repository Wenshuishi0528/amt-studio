from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .audio import AudioToolError
from .project import ProjectError, initialize_project, load_project
from .utils import atomic_write_json, slugify

STATE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
HOST_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*"
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
JOB_STATUSES = TERMINAL_STATUSES | {"submitted", "running"}
COMPUTE_BACKENDS = {"hyak", "local"}
LOCAL_DEVICES = {"mps", "cpu"}
TASK_KINDS = {
    "full_transcription",
    "game_vocal_transcription",
    "targeted_gap_recovery",
}
RECOGNITION_MODES = {"multitrack", "game_vocal"}
DEFAULT_HYAK_TIME_LIMIT_HOURS = 1
MIN_HYAK_TIME_LIMIT_HOURS = 1
MAX_HYAK_TIME_LIMIT_HOURS = 24
GPU_TEST_START_PATTERN = re.compile(
    r"\bto start at (?P<start>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\b"
)
GPU_START_TIE_SECONDS = 5 * 60
GAME_PRODUCT_MODEL = "GAME-1.0-large"
GAME_UPSTREAM_COMMIT = "475a8ee781fe8cca980b3b12fbe6c80c768a813a"
CODE_SNAPSHOT_MARKER = ".amt-code-snapshot.json"
CODE_SYNC_TIMEOUT_SECONDS = 900
CODE_SYNC_EXCLUDES = (
    ".git/",
    ".venv/",
    ".uv-cache/",
    ".build/",
    "dist/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    "checkouts/",
    CODE_SNAPSHOT_MARKER,
    "data/private/",
    "projects/private/",
    "datasets/",
    "model-cache/",
    "weights/",
    "hyak-results/",
)


class PrivateBetaError(RuntimeError):
    """Raised when the bounded Mac-to-Hyak private beta workflow cannot proceed."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _slurm_time_limit(hours: int) -> str:
    if (
        not isinstance(hours, int)
        or isinstance(hours, bool)
        or not MIN_HYAK_TIME_LIMIT_HOURS <= hours <= MAX_HYAK_TIME_LIMIT_HOURS
    ):
        raise PrivateBetaError(
            "Hyak 运行时限必须是 "
            f"{MIN_HYAK_TIME_LIMIT_HOURS}–{MAX_HYAK_TIME_LIMIT_HOURS} 小时"
        )
    return f"{hours:02d}:00:00"


def _ensure_repository_imports(repo_root: Path) -> None:
    root = str(repo_root.expanduser().resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrivateBetaError(f"command failed to start: {argv[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PrivateBetaError(f"{argv[0]} failed: {detail}")
    return result


@dataclass(frozen=True)
class HyakConnection:
    host: str
    control_path: Path | None

    @classmethod
    def discover(cls, host: str) -> HyakConnection:
        override = os.environ.get("HYAK_CONTROL_PATH")
        candidates = [Path(override)] if override else []
        candidates.extend(sorted(Path("/tmp").glob("amt-hyak-control.*/socket")))
        for candidate in candidates:
            if not candidate.exists():
                continue
            result = subprocess.run(
                ["ssh", "-S", str(candidate), "-O", "check", host],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return cls(host=host, control_path=candidate)

        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                host,
                "true",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode == 0:
            return cls(host=host, control_path=None)
        raise PrivateBetaError(
            "Hyak 尚未登录。请先点应用里的“连接 Hyak”，在 Terminal 完成密码和 Duo；"
            "应用不会保存密码或验证码。"
        )

    def ssh_prefix(self) -> list[str]:
        command = ["ssh"]
        if self.control_path is not None:
            command.extend(["-S", str(self.control_path)])
        command.extend(
            [
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                self.host,
            ]
        )
        return command

    def remote(self, command: str, *, timeout: float | None = None) -> str:
        return _run([*self.ssh_prefix(), command], timeout=timeout).stdout.strip()

    def rsync_shell(self) -> str:
        command = ["ssh"]
        if self.control_path is not None:
            command.extend(["-S", str(self.control_path)])
        command.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"])
        return " ".join(shlex.quote(part) for part in command)


@dataclass(frozen=True)
class HyakGPUCandidate:
    gpu_type: str
    label: str
    account: str
    partition: str
    qos: str
    speed_rank: int
    preemptible: bool

    def submission_arguments(self, time_limit_hours: int) -> tuple[str, ...]:
        return (
            f"--account={self.account}",
            f"--partition={self.partition}",
            f"--qos={self.qos}",
            f"--gpus={self.gpu_type}:1",
            f"--time={_slurm_time_limit(time_limit_hours)}",
        )


@dataclass(frozen=True)
class HyakGPUProbe:
    candidate: HyakGPUCandidate
    estimated_start_at: str
    estimated_start_epoch: int


@dataclass(frozen=True)
class HyakGPUPlan:
    candidate: HyakGPUCandidate | None
    submission_arguments: tuple[str, ...]
    estimated_start_at: str | None
    estimated_wait_seconds: int | None
    reason: str
    probed_candidate_count: int

    def state_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "gpu_selection_policy": "auto_fastest",
            "slurm_gpu_type": (
                self.candidate.gpu_type if self.candidate is not None else "l40"
            ),
            "slurm_partition": (
                self.candidate.partition
                if self.candidate is not None
                else "gpu-l40"
            ),
            "gpu_preemptible": (
                self.candidate.preemptible
                if self.candidate is not None
                else False
            ),
            "gpu_selection_reason": self.reason,
            "gpu_probed_candidate_count": self.probed_candidate_count,
        }
        if self.candidate is not None:
            fields["slurm_account"] = self.candidate.account
            fields["slurm_qos"] = self.candidate.qos
        if self.estimated_start_at is not None:
            fields["gpu_estimated_start_at"] = self.estimated_start_at
        if self.estimated_wait_seconds is not None:
            fields["gpu_estimated_wait_seconds"] = self.estimated_wait_seconds
        return fields


def _gpu_candidates_from_associations(value: str) -> tuple[HyakGPUCandidate, ...]:
    normal_accounts: dict[str, set[str]] = {"l40": set(), "l40s": set()}
    checkpoint_accounts: set[str] = set()
    for line in value.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 3:
            continue
        account, _partition, qos_text = fields[:3]
        qos = {item for item in qos_text.split(",") if item}
        if "normal" in qos:
            for gpu_type in normal_accounts:
                if account.startswith(f"gpu-{gpu_type}-"):
                    normal_accounts[gpu_type].add(account)
        if account.startswith("ckpt-") and "ckpt-gpu" in qos:
            checkpoint_accounts.add(account)

    candidates: list[HyakGPUCandidate] = []
    for account in sorted(checkpoint_accounts):
        candidates.extend(
            (
                HyakGPUCandidate(
                    gpu_type="a100",
                    label="A100",
                    account=account,
                    partition="ckpt",
                    qos="ckpt-gpu",
                    speed_rank=0,
                    preemptible=True,
                ),
                HyakGPUCandidate(
                    gpu_type="a40",
                    label="A40",
                    account=account,
                    partition="ckpt",
                    qos="ckpt-gpu",
                    speed_rank=3,
                    preemptible=True,
                ),
            )
        )
    for gpu_type, label, rank in (("l40s", "L40S", 1), ("l40", "L40", 2)):
        for account in sorted(normal_accounts[gpu_type]):
            candidates.append(
                HyakGPUCandidate(
                    gpu_type=gpu_type,
                    label=label,
                    account=account,
                    partition=f"gpu-{gpu_type}",
                    qos="normal",
                    speed_rank=rank,
                    preemptible=False,
                )
            )
    return tuple(candidates)


def _select_gpu_probe(
    probes: Iterable[HyakGPUProbe],
    *,
    now_epoch: int,
) -> tuple[HyakGPUProbe, int]:
    available = tuple(probes)
    if not available:
        raise PrivateBetaError("Hyak 没有返回可用的兼容 GPU 计划")
    earliest = min(probe.estimated_start_epoch for probe in available)
    contenders = tuple(
        probe
        for probe in available
        if probe.estimated_start_epoch <= earliest + GPU_START_TIE_SECONDS
    )
    selected = min(
        contenders,
        key=lambda probe: (
            probe.candidate.speed_rank,
            probe.estimated_start_epoch,
            probe.candidate.account,
        ),
    )
    return selected, max(0, selected.estimated_start_epoch - now_epoch)


def _fallback_gpu_plan(
    candidates: tuple[HyakGPUCandidate, ...],
    *,
    time_limit_hours: int,
    reason: str,
) -> HyakGPUPlan:
    stable_l40 = next(
        (
            candidate
            for candidate in candidates
            if candidate.gpu_type == "l40" and not candidate.preemptible
        ),
        None,
    )
    arguments = (
        stable_l40.submission_arguments(time_limit_hours)
        if stable_l40 is not None
        else (f"--time={_slurm_time_limit(time_limit_hours)}",)
    )
    return HyakGPUPlan(
        candidate=stable_l40,
        submission_arguments=arguments,
        estimated_start_at=None,
        estimated_wait_seconds=None,
        reason=reason,
        probed_candidate_count=0,
    )


def _plan_hyak_gpu(
    connection: HyakConnection,
    *,
    time_limit_hours: int,
    allow_preemptible: bool = True,
) -> HyakGPUPlan:
    try:
        associations = connection.remote(
            'sacctmgr -nP show assoc user="$USER" format=Account,Partition,QOS',
            timeout=15,
        )
    except PrivateBetaError:
        return _fallback_gpu_plan(
            (),
            time_limit_hours=time_limit_hours,
            reason="GPU 自动探测失败，已回退稳定 L40",
        )
    candidates = _gpu_candidates_from_associations(associations)
    if not allow_preemptible:
        candidates = tuple(
            candidate for candidate in candidates if not candidate.preemptible
        )
    if not candidates:
        return _fallback_gpu_plan(
            candidates,
            time_limit_hours=time_limit_hours,
            reason="未发现已验证的 GPU 账号，已回退稳定 L40",
        )

    try:
        now_epoch = int(connection.remote("date +%s", timeout=10))
    except (PrivateBetaError, ValueError):
        return _fallback_gpu_plan(
            candidates,
            time_limit_hours=time_limit_hours,
            reason="无法读取 Hyak 调度时间，已回退稳定 L40",
        )

    probes: list[HyakGPUProbe] = []
    for candidate in candidates:
        probe_arguments = (
            "sbatch",
            "--test-only",
            "--nodes=1",
            "--ntasks=1",
            "--cpus-per-task=2",
            "--mem=64G",
            *candidate.submission_arguments(time_limit_hours),
            "--wrap=true",
        )
        try:
            output = connection.remote(
                f"{shlex.join(probe_arguments)} 2>&1",
                timeout=20,
            )
            match = GPU_TEST_START_PATTERN.search(output)
            if match is None:
                continue
            estimated_start_at = match.group("start")
            estimated_start_epoch = int(
                connection.remote(
                    shlex.join(("date", "-d", estimated_start_at, "+%s")),
                    timeout=10,
                )
            )
        except (PrivateBetaError, ValueError):
            continue
        probes.append(
            HyakGPUProbe(
                candidate=candidate,
                estimated_start_at=estimated_start_at,
                estimated_start_epoch=estimated_start_epoch,
            )
        )
    if not probes:
        return _fallback_gpu_plan(
            candidates,
            time_limit_hours=time_limit_hours,
            reason="兼容 GPU 均未返回预计开始时间，已回退稳定 L40",
        )

    selected, wait_seconds = _select_gpu_probe(probes, now_epoch=now_epoch)
    wait_label = (
        "预计立即开始"
        if wait_seconds < 60
        else f"预计等待约 {(wait_seconds + 59) // 60} 分钟"
    )
    preemptible_label = "；checkpoint 队列可能被抢占" if selected.candidate.preemptible else ""
    reason = (
        f"自动比较 {len(probes)} 个兼容 GPU 计划；"
        f"{selected.candidate.label} {wait_label}，"
        f"五分钟内按已验证性能顺序择优{preemptible_label}"
    )
    return HyakGPUPlan(
        candidate=selected.candidate,
        submission_arguments=selected.candidate.submission_arguments(
            time_limit_hours
        ),
        estimated_start_at=selected.estimated_start_at,
        estimated_wait_seconds=wait_seconds,
        reason=reason,
        probed_candidate_count=len(probes),
    )


def _state_path(project_dir: Path) -> Path:
    return project_dir / "app" / "private_beta_job.json"


def _safe_remote_root(value: str) -> str:
    if (
        not value
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or ":" in value
    ):
        raise PrivateBetaError("Hyak 远端根目录格式无效")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or value == "/":
        raise PrivateBetaError("Hyak 远端根目录必须是安全的绝对路径")
    return str(path)


def _safe_host(value: str) -> str:
    if HOST_PATTERN.fullmatch(value) is None:
        raise PrivateBetaError("Hyak 主机必须使用 user@host 格式")
    return value


def _require_safe_identifier(value: str, *, label: str) -> str:
    if STATE_IDENTIFIER.fullmatch(value) is None or ".." in value:
        raise PrivateBetaError(f"{label} 标识无效")
    return value


def _load_hyak_configuration(
    repo_root: Path,
    *,
    host: str | None,
    remote_root: str | None,
) -> tuple[str, str]:
    config_path = repo_root / "configs" / "local_hyak.json"
    config: dict[str, Any] = {}
    if config_path.exists():
        if config_path.is_symlink() or not config_path.is_file():
            raise PrivateBetaError(f"Hyak 配置必须是普通文件：{config_path}")
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivateBetaError(f"无法读取 Hyak 配置：{config_path}: {exc}") from exc
        if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
            raise PrivateBetaError("Hyak 配置文件格式无效")
        config = loaded

    resolved_host = host or os.environ.get("HYAK_HOST") or config.get("host")
    resolved_root = (
        remote_root
        or os.environ.get("HYAK_REMOTE_ROOT")
        or os.environ.get("HYAK_PERSIST_ROOT")
        or config.get("remote_root")
    )
    if not isinstance(resolved_host, str) or not isinstance(resolved_root, str):
        raise PrivateBetaError(
            "尚未配置 Hyak。请复制 configs/hyak.example.json 为 "
            "configs/local_hyak.json，并填写 host 与 remote_root。"
        )
    return _safe_host(resolved_host), _safe_remote_root(resolved_root)


def _require_state_string(
    state: dict[str, Any],
    key: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PrivateBetaError(f"任务状态字段 {key} 无效")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise PrivateBetaError(f"任务状态字段 {key} 无效")
    return value


def _canonical_filesystem_text(value: str) -> str:
    """Compare macOS paths and identifiers without changing their stored spelling."""
    return unicodedata.normalize("NFC", value)


def _validate_state(project_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "backend",
        "status",
        "submitted_at",
        "updated_at",
        "completed_at",
        "project_id",
        "local_project_dir",
        "remote_project_dir",
        "host",
        "remote_root",
        "job_id",
        "run_id",
        "bundle_id",
        "weight_provenance_path",
        "slurm_state",
        "slurm_exit_code",
        "code_commit",
        "pipeline_stage",
        "local_device",
        "local_pid",
        "local_log_path",
        "failure_reason",
        "task_kind",
        "source_bundle_id",
        "source_track_id",
        "recovery_request_path",
        "selected_gap_count",
        "recognition_mode",
        "separator_run_id",
        "separator_model_dir",
        "game_model_provenance_path",
        "gpu_selection_policy",
        "slurm_gpu_type",
        "slurm_account",
        "slurm_partition",
        "slurm_qos",
        "gpu_preemptible",
        "gpu_selection_reason",
        "gpu_probed_candidate_count",
        "gpu_estimated_start_at",
        "gpu_estimated_wait_seconds",
        "recovered_candidate_note_count",
    }
    if set(state) - allowed:
        raise PrivateBetaError("任务状态文件包含未知字段")

    project_id = _require_state_string(state, "project_id")
    if (
        _canonical_filesystem_text(project_id)
        != _canonical_filesystem_text(project_dir.name)
        or project_id in {".", ".."}
        or "/" in project_id
        or "\n" in project_id
        or "\r" in project_id
    ):
        raise PrivateBetaError("任务状态 project_id 与项目目录不匹配")
    local_project = Path(_require_state_string(state, "local_project_dir"))
    try:
        local_project_matches = local_project.expanduser().resolve().samefile(project_dir)
    except OSError:
        local_project_matches = False
    if not local_project_matches:
        raise PrivateBetaError("任务状态 local_project_dir 与项目目录不匹配")

    backend = state.get("backend", "hyak")
    if backend not in COMPUTE_BACKENDS:
        raise PrivateBetaError("任务状态 backend 无效")
    state["backend"] = backend
    task_kind = state.get("task_kind", "full_transcription")
    if task_kind not in TASK_KINDS:
        raise PrivateBetaError("任务状态 task_kind 无效")
    state["task_kind"] = task_kind
    recognition_mode = state.get("recognition_mode", "multitrack")
    if recognition_mode not in RECOGNITION_MODES:
        raise PrivateBetaError("任务状态 recognition_mode 无效")
    if (
        task_kind == "game_vocal_transcription"
        and recognition_mode != "game_vocal"
    ):
        raise PrivateBetaError("GAME 任务状态与识别模式不匹配")
    if recognition_mode == "game_vocal" and (
        task_kind != "game_vocal_transcription" or backend != "hyak"
    ):
        raise PrivateBetaError("GAME 识别模式只允许 Hyak GAME 单轨任务")
    state["recognition_mode"] = recognition_mode
    job_id = _require_state_string(state, "job_id")
    if backend == "hyak":
        host = _safe_host(_require_state_string(state, "host"))
        remote_root = _safe_remote_root(_require_state_string(state, "remote_root"))
        remote_project = _require_state_string(state, "remote_project_dir")
        expected_remote = f"{remote_root}/projects/private/{project_id}"
        if remote_project != expected_remote:
            raise PrivateBetaError("任务状态 remote_project_dir 与项目身份不匹配")
        if not job_id.isdigit():
            raise PrivateBetaError("任务状态 job_id 无效")
        state["host"] = host
        state["remote_root"] = remote_root
        for key in (
            "gpu_selection_policy",
            "slurm_gpu_type",
            "slurm_account",
            "slurm_partition",
            "slurm_qos",
            "gpu_selection_reason",
            "gpu_estimated_start_at",
        ):
            if key in state:
                _require_state_string(state, key)
        if "gpu_preemptible" in state and not isinstance(
            state["gpu_preemptible"], bool
        ):
            raise PrivateBetaError("任务状态 gpu_preemptible 无效")
        for key in ("gpu_probed_candidate_count", "gpu_estimated_wait_seconds"):
            if key in state and (
                not isinstance(state[key], int)
                or isinstance(state[key], bool)
                or state[key] < 0
            ):
                raise PrivateBetaError(f"任务状态字段 {key} 无效")
    else:
        if STATE_IDENTIFIER.fullmatch(job_id) is None or not job_id.startswith("local-"):
            raise PrivateBetaError("本机任务 job_id 无效")
        local_device = _require_state_string(state, "local_device")
        if local_device not in LOCAL_DEVICES:
            raise PrivateBetaError("本机任务 local_device 无效")
        local_pid = state.get("local_pid")
        if not isinstance(local_pid, int) or isinstance(local_pid, bool) or local_pid <= 1:
            raise PrivateBetaError("本机任务 local_pid 无效")
        log_path = Path(_require_state_string(state, "local_log_path"))
        expected_log_path = (project_dir / "logs/local-compute.log").resolve()
        if log_path.expanduser().resolve() != expected_log_path:
            raise PrivateBetaError("本机任务日志路径无效")
    run_id = _require_state_string(state, "run_id", pattern=STATE_IDENTIFIER)
    bundle_id = _require_state_string(state, "bundle_id", pattern=STATE_IDENTIFIER)
    if bundle_id != f"{run_id}-multitrack":
        raise PrivateBetaError("任务状态 bundle_id 与 run_id 不匹配")
    if task_kind == "targeted_gap_recovery":
        _require_state_string(
            state,
            "source_bundle_id",
            pattern=STATE_IDENTIFIER,
        )
        _require_state_string(
            state,
            "source_track_id",
            pattern=STATE_IDENTIFIER,
        )
        request = _require_state_string(state, "recovery_request_path")
        request_path = Path(request)
        try:
            resolved_request = request_path.expanduser().resolve(strict=True)
            requests_dir = (project_dir / "requests").resolve(strict=True)
            requests_dir.relative_to(project_dir)
            if (
                not requests_dir.is_dir()
                or not resolved_request.is_file()
                or not resolved_request.parent.samefile(requests_dir)
            ):
                raise OSError("request is not a direct file in the project requests dir")
        except (OSError, ValueError) as exc:
            raise PrivateBetaError("任务状态 recovery_request_path 无效") from exc
        selected_gap_count = state.get("selected_gap_count")
        if (
            not isinstance(selected_gap_count, int)
            or isinstance(selected_gap_count, bool)
            or not 1 <= selected_gap_count <= 16
        ):
            raise PrivateBetaError("任务状态 selected_gap_count 无效")
    recovered_count = state.get("recovered_candidate_note_count")
    if recovered_count is not None and (
        task_kind != "targeted_gap_recovery"
        or not isinstance(recovered_count, int)
        or isinstance(recovered_count, bool)
        or recovered_count < 0
    ):
        raise PrivateBetaError(
            "任务状态 recovered_candidate_note_count 无效"
        )
    if recognition_mode == "game_vocal":
        _require_state_string(
            state,
            "separator_run_id",
            pattern=STATE_IDENTIFIER,
        )
        separator_model_dir = PurePosixPath(
            _require_state_string(state, "separator_model_dir")
        )
        game_provenance = PurePosixPath(
            _require_state_string(state, "game_model_provenance_path")
        )
        for path, label in (
            (separator_model_dir, "separator_model_dir"),
            (game_provenance, "game_model_provenance_path"),
        ):
            if not path.is_absolute() or ".." in path.parts:
                raise PrivateBetaError(f"任务状态 {label} 无效")

    status = _require_state_string(state, "status")
    if status not in JOB_STATUSES:
        raise PrivateBetaError("任务状态 status 无效")
    slurm_state = _require_state_string(state, "slurm_state")
    if re.fullmatch(r"[A-Z_]+", slurm_state) is None:
        raise PrivateBetaError("任务状态 slurm_state 无效")
    pipeline_stage = state.get("pipeline_stage")
    if pipeline_stage is None:
        if status == "succeeded":
            pipeline_stage = "complete"
        elif status in {"failed", "cancelled"}:
            pipeline_stage = "failed"
        elif slurm_state == "RUNNING":
            pipeline_stage = "starting"
        else:
            pipeline_stage = "queued"
        state["pipeline_stage"] = pipeline_stage
    if not isinstance(pipeline_stage, str):
        raise PrivateBetaError("任务状态 pipeline_stage 无效")
    if pipeline_stage not in {
        "queued",
        "starting",
        "full_transcription",
        "rhythm_analysis",
        "gap_planning",
        "automatic_gap_recovery",
        "targeted_gap_recovery",
        "source_separation",
        "game_vocal_transcription",
        "packaging",
        "complete",
        "failed",
    }:
        raise PrivateBetaError("任务状态 pipeline_stage 无效")

    provenance = _require_state_string(state, "weight_provenance_path")
    provenance_path = PurePosixPath(provenance)
    if (
        not provenance_path.is_absolute()
        or ".." in provenance_path.parts
        or "\n" in provenance
        or "\r" in provenance
    ):
        raise PrivateBetaError("任务状态 weight_provenance_path 无效")
    for key in (
        "submitted_at",
        "updated_at",
        "completed_at",
        "slurm_exit_code",
        "failure_reason",
    ):
        if key in state and state[key] is not None and not isinstance(state[key], str):
            raise PrivateBetaError(f"任务状态字段 {key} 无效")
    if "code_commit" in state and state["code_commit"] is not None:
        _require_state_string(state, "code_commit", pattern=COMMIT_PATTERN)

    manifest_path = project_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateBetaError(f"无法验证项目清单：{manifest_path}: {exc}") from exc
    manifest_project_id = manifest.get("project_id") if isinstance(manifest, dict) else None
    if not isinstance(manifest_project_id, str) or _canonical_filesystem_text(
        manifest_project_id
    ) != _canonical_filesystem_text(project_id):
        raise PrivateBetaError("任务状态 project_id 与项目清单不匹配")
    return state


def _load_state(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    path = _state_path(project_dir)
    if path.parent.is_symlink() or path.is_symlink():
        raise PrivateBetaError("任务状态路径不能是符号链接")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateBetaError(f"无法读取任务状态：{path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PrivateBetaError("任务状态文件格式无效")
    return _validate_state(project_dir, value)


def _write_state(project_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    atomic_write_json(_state_path(project_dir), state)


def _archive_previous_state(project_dir: Path) -> None:
    path = _state_path(project_dir)
    if not path.exists():
        return
    state = _load_state(project_dir)
    if state["status"] not in TERMINAL_STATUSES:
        raise PrivateBetaError("当前项目已有计算任务，不能重复提交")
    history = project_dir / "app/job_history"
    history.mkdir(parents=True, exist_ok=True)
    destination = history / f"{state['job_id']}.json"
    if not destination.exists():
        atomic_write_json(destination, state)


def _unique_project_dir(local_root: Path, stem: str) -> Path:
    safe = slugify(stem, fallback="song")[:80]
    candidate = local_root / safe
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return local_root / f"{safe}-{stamp}-{uuid4().hex[:6]}"


def _local_weight_provenance(
    repo_root: Path,
    explicit: str | None,
) -> Path:
    candidate = Path(
        explicit
        or os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE")
        or repo_root / "weights/muscriptor/large-provenance.json"
    ).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_file() or candidate.is_symlink():
        raise PrivateBetaError(
            "本机尚未准备 MuScriptor 模型。请先登录 Hugging Face，并按 "
            "workers/muscriptor/README.md 下载约 5.5 GB 的固定版本模型。"
        )
    try:
        provenance = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateBetaError(f"本机模型来源文件无法读取：{candidate}") from exc
    if (
        not isinstance(provenance, dict)
        or provenance.get("repository") != "MuScriptor/muscriptor-large"
        or not isinstance(provenance.get("weight"), dict)
        or not isinstance(provenance.get("config"), dict)
    ):
        raise PrivateBetaError("本机 MuScriptor 模型来源文件无效")
    for label in ("weight", "config"):
        path_value = provenance[label].get("path")
        if not isinstance(path_value, str) or not Path(path_value).expanduser().is_file():
            raise PrivateBetaError(f"本机 MuScriptor {label} 文件不存在")
    return candidate


def local_readiness(
    repo_root: Path,
    *,
    device: str,
    weight_provenance: str | None = None,
    probe_device: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    if device not in LOCAL_DEVICES:
        raise PrivateBetaError("本机计算设备必须是 mps 或 cpu")
    worker_env = repo_root / "workers/muscriptor/.venv"
    worker_python = worker_env / "bin/python"
    muscriptor = worker_env / "bin/muscriptor"
    missing: list[str] = []
    if not worker_python.is_file() or not os.access(worker_python, os.X_OK):
        missing.append("MuScriptor Python 环境")
    if not muscriptor.is_file() or not os.access(muscriptor, os.X_OK):
        missing.append("MuScriptor 命令")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    provenance: Path | None = None
    try:
        provenance = _local_weight_provenance(repo_root, weight_provenance)
    except PrivateBetaError as exc:
        missing.append(str(exc))

    device_available = device == "cpu"
    if not missing and device == "mps" and probe_device:
        diagnostics = _run(
            [
                str(worker_python),
                "-c",
                (
                    "import json, torch; "
                    "print(json.dumps({'built': bool(torch.backends.mps.is_built()), "
                    "'available': bool(torch.backends.mps.is_available())}))"
                ),
            ],
            timeout=30,
        )
        try:
            payload = json.loads(diagnostics.stdout)
        except json.JSONDecodeError as exc:
            raise PrivateBetaError("无法读取本机 Apple GPU 状态") from exc
        device_available = payload.get("available") is True
        if not device_available:
            missing.append("Apple Metal/MPS 当前不可用")

    ready = not missing and device_available
    label = "Apple GPU（Metal/MPS）" if device == "mps" else "CPU"
    return {
        "schema_version": 1,
        "backend": "local",
        "local_device": device,
        "ready": ready,
        "readiness_message": (
            f"本机 {label} 已就绪；开始后会占用本机资源。"
            if ready
            else "；".join(missing)
        ),
        "weight_provenance_path": str(provenance) if provenance else None,
    }


def _local_worker_command(
    project_dir: Path,
    *,
    repo_root: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "amt_core.private_beta",
        "run-local-worker",
        str(project_dir),
        "--repo-root",
        str(repo_root),
    ]


def start_local_job(
    audio: Path,
    *,
    repo_root: Path,
    local_root: Path,
    device: str,
    weight_provenance: str | None,
) -> dict[str, Any]:
    audio = audio.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    local_root = local_root.expanduser().resolve()
    if not audio.is_file():
        raise PrivateBetaError(f"找不到音频文件：{audio}")
    readiness = local_readiness(
        repo_root,
        device=device,
        weight_provenance=weight_provenance,
    )
    if readiness["ready"] is not True:
        raise PrivateBetaError(str(readiness["readiness_message"]))
    project_dir = _unique_project_dir(local_root, audio.stem)
    manifest = initialize_project(audio, project_dir, title=audio.stem, copy_original=True)
    project_id = manifest["project_id"]
    run_id = (
        f"muscriptor-local-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid4().hex[:8]}"
    )
    bundle_id = f"{run_id}-multitrack"
    job_id = f"local-{uuid4().hex[:12]}"
    log_path = project_dir / "logs/local-compute.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    code_commit = _run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
    ).stdout.strip()
    state: dict[str, Any] = {
        "schema_version": 1,
        "backend": "local",
        "status": "submitted",
        "submitted_at": _utc_now(),
        "project_id": project_id,
        "local_project_dir": str(project_dir),
        "job_id": job_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "weight_provenance_path": readiness["weight_provenance_path"],
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "starting",
        "local_device": device,
        "local_log_path": str(log_path),
    }
    _write_state(project_dir, state)
    environment = os.environ.copy()
    background_threads = max(1, (os.cpu_count() or 2) // 2)
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": str(background_threads),
            "MKL_NUM_THREADS": str(background_threads),
        }
    )
    if device == "mps":
        environment["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    with log_path.open("a", encoding="utf-8") as log_handle:
        try:
            process = subprocess.Popen(
                _local_worker_command(project_dir, repo_root=repo_root),
                cwd=repo_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            state["status"] = "failed"
            state["slurm_state"] = "FAILED"
            state["pipeline_stage"] = "failed"
            state["completed_at"] = _utc_now()
            state["failure_reason"] = f"无法启动本机后台任务：{exc}"
            state["local_pid"] = 2
            _write_state(project_dir, state)
            raise PrivateBetaError(state["failure_reason"]) from exc
    state["local_pid"] = process.pid
    state["status"] = "running"
    state["slurm_state"] = "RUNNING"
    _write_state(project_dir, state)
    if process.stdin is not None:
        process.stdin.write("start\n")
        process.stdin.close()
    return state


def _sync_code(connection: HyakConnection, repo_root: Path, remote_root: str) -> str:
    remote_repo = f"{remote_root}/repo"
    connection.remote(f"mkdir -p {shlex.quote(remote_repo)}")
    commit = _run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
    ).stdout.strip()
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise PrivateBetaError("本地仓库没有可同步的 Git commit")
    if _remote_code_snapshot_matches(connection, remote_repo, commit):
        return commit
    with tempfile.TemporaryDirectory(prefix="amt-code-snapshot.") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "snapshot.tar"
        snapshot = temporary_root / "snapshot"
        snapshot.mkdir()
        _run(
            ["git", "archive", "--format=tar", f"--output={archive}", commit],
            cwd=repo_root,
        )
        _run(["tar", "-xf", str(archive), "-C", str(snapshot)])
        exclude_arguments = [
            argument
            for pattern in CODE_SYNC_EXCLUDES
            for argument in ("--exclude", pattern)
        ]
        _run(
            [
                "rsync",
                "-az",
                "--delete",
                *exclude_arguments,
                "-e",
                connection.rsync_shell(),
                f"{snapshot}/",
                f"{connection.host}:{remote_repo}/",
            ],
            timeout=CODE_SYNC_TIMEOUT_SECONDS,
        )
    _mark_remote_code_snapshot(connection, remote_repo, commit)
    return commit


def _remote_code_snapshot_matches(
    connection: HyakConnection,
    remote_repo: str,
    commit: str,
) -> bool:
    marker = f"{remote_repo}/{CODE_SNAPSHOT_MARKER}"
    try:
        raw = connection.remote(f"cat {shlex.quote(marker)}", timeout=15)
        payload = json.loads(raw)
    except (PrivateBetaError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("schema_version") == 1
        and payload.get("commit") == commit
        and payload.get("dirty") is False
        and payload.get("source") == "git_archive"
        and payload.get("sync_complete") is True
    )


def _mark_remote_code_snapshot(
    connection: HyakConnection,
    remote_repo: str,
    commit: str,
) -> None:
    marker = f"{remote_repo}/{CODE_SNAPSHOT_MARKER}"
    temporary = f"{marker}.tmp-{uuid4().hex}"
    payload = json.dumps(
        {
            "schema_version": 1,
            "commit": commit,
            "dirty": False,
            "source": "git_archive",
            "sync_complete": True,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    connection.remote(
        "umask 077; "
        f"printf %s {shlex.quote(payload + chr(10))} "
        f"> {shlex.quote(temporary)} && "
        f"mv {shlex.quote(temporary)} {shlex.quote(marker)}",
        timeout=30,
    )


def _sync_project_to_hyak(
    connection: HyakConnection,
    project_dir: Path,
    remote_project: str,
) -> None:
    connection.remote(f"mkdir -p {shlex.quote(remote_project)}")
    _run(
        [
            "rsync",
            "-az",
            "--partial",
            "--exclude",
            "runs/",
            "--exclude",
            "exports/",
            "--exclude",
            "annotations/",
            "--exclude",
            "app/",
            "-e",
            connection.rsync_shell(),
            f"{project_dir}/",
            f"{connection.host}:{remote_project}/",
        ],
        timeout=1800,
    )


def _sync_bundle_to_hyak(
    connection: HyakConnection,
    project_dir: Path,
    remote_project: str,
    bundle_id: str,
) -> None:
    bundle_id = _require_safe_identifier(bundle_id, label="source bundle")
    source = project_dir / "exports" / bundle_id
    if not (source / "bundle_manifest.json").is_file():
        raise PrivateBetaError(f"找不到源识别版本：{bundle_id}")
    remote_bundle = f"{remote_project}/exports/{bundle_id}"
    connection.remote(f"mkdir -p {shlex.quote(remote_bundle)}")
    _run(
        [
            "rsync",
            "-az",
            "--partial",
            "--delete",
            "-e",
            connection.rsync_shell(),
            f"{source}/",
            f"{connection.host}:{remote_bundle}/",
        ],
        timeout=1800,
    )


def _discover_weight_provenance(
    connection: HyakConnection,
    remote_root: str,
    explicit: str | None,
) -> str:
    if explicit:
        connection.remote(f"test -f {shlex.quote(explicit)}")
        return explicit
    command = (
        "find "
        f"{shlex.quote(remote_root + '/model-cache')} "
        f"{shlex.quote(remote_root + '/weights')} "
        f"{shlex.quote(remote_root + '/repo/weights')} "
        "-maxdepth 7 -type f "
        "\\( -name '*provenance*.json' -o -name 'provenance.json' \\) "
        "2>/dev/null | head -50"
    )
    candidates = [line for line in connection.remote(command).splitlines() if line]
    matches: list[str] = []
    for candidate in candidates:
        try:
            payload = json.loads(
                connection.remote(f"cat {shlex.quote(candidate)}", timeout=10)
            )
        except (PrivateBetaError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("repository") == "MuScriptor/muscriptor-large"
            and isinstance(payload.get("weight"), dict)
        ):
            matches.append(candidate)
    if len(matches) != 1:
        raise PrivateBetaError(
            "无法唯一定位 Hyak 上的 MuScriptor 权重来源文件；"
            "请设置 MUSCRIPTOR_WEIGHT_PROVENANCE 后重试。"
        )
    return matches[0]


def _discover_game_model_provenance(
    connection: HyakConnection,
    remote_root: str,
    explicit: str | None,
) -> str:
    if explicit:
        safe_explicit = _safe_remote_root(explicit)
        connection.remote(f"test -f {shlex.quote(safe_explicit)}")
        candidates = [safe_explicit]
    else:
        search_roots = (
            f"{remote_root}/amt-studio/models",
            f"{remote_root}/models",
            f"{remote_root}/model-cache",
            f"{remote_root}/weights",
            f"{remote_root}/repo/weights",
        )
        command = (
            "find "
            + " ".join(shlex.quote(root) for root in search_roots)
            + " "
            "-maxdepth 8 -type f "
            "\\( -name 'model-provenance.json' -o -name '*provenance*.json' \\) "
            "2>/dev/null | head -100"
        )
        candidates = [
            line for line in connection.remote(command).splitlines() if line
        ]
    matches: list[str] = []
    discovered_game_models: set[str] = set()
    for candidate in candidates:
        try:
            payload = json.loads(
                connection.remote(f"cat {shlex.quote(candidate)}", timeout=10)
            )
        except (PrivateBetaError, json.JSONDecodeError):
            continue
        model = payload.get("model") if isinstance(payload, dict) else None
        source = payload.get("source") if isinstance(payload, dict) else None
        if isinstance(model, dict) and isinstance(model.get("name"), str):
            model_name = model["name"]
            if model_name.startswith("GAME-"):
                discovered_game_models.add(model_name)
        if (
            isinstance(model, dict)
            and model.get("name") == GAME_PRODUCT_MODEL
            and isinstance(source, dict)
            and source.get("commit") == GAME_UPSTREAM_COMMIT
        ):
            matches.append(candidate)
    if not matches:
        available = (
            "；发现的其他 GAME 模型：" + "、".join(sorted(discovered_game_models))
            if discovered_game_models
            else ""
        )
        raise PrivateBetaError(
            f"Hyak 上尚未安装并校验产品所需的 {GAME_PRODUCT_MODEL}{available}。"
            "请先运行官方 large 权重安装任务，或设置 GAME_MODEL_PROVENANCE。"
        )
    if len(matches) > 1:
        raise PrivateBetaError(
            f"Hyak 上找到多个 {GAME_PRODUCT_MODEL} 权重来源文件；"
            "请设置 GAME_MODEL_PROVENANCE 明确选择一个。"
        )
    return matches[0]


def _discover_separator_model_dir(
    connection: HyakConnection,
    remote_root: str,
    explicit: str | None,
) -> str:
    if explicit:
        safe_explicit = _safe_remote_root(explicit)
        connection.remote(
            "test -f "
            + shlex.quote(
                f"{safe_explicit}/model_bs_roformer_ep_317_sdr_12.9755.ckpt"
            )
        )
        return safe_explicit
    search_roots = (
        f"{remote_root}/amt-studio/weights",
        f"{remote_root}/amt-studio/models",
        f"{remote_root}/model-cache",
        f"{remote_root}/weights",
        f"{remote_root}/repo/weights",
    )
    command = (
        "find "
        + " ".join(shlex.quote(root) for root in search_roots)
        + " "
        "-maxdepth 8 -type f "
        "-name 'model_bs_roformer_ep_317_sdr_12.9755.ckpt' "
        "2>/dev/null | head -20"
    )
    matches = [
        str(PurePosixPath(line).parent)
        for line in connection.remote(command).splitlines()
        if line
    ]
    unique_matches = sorted(set(matches))
    if len(unique_matches) != 1:
        raise PrivateBetaError(
            "无法唯一定位 Hyak 上的 BS-Roformer 分离模型目录；"
            "请设置 SEPARATOR_MODEL_DIR 后重试。"
        )
    return unique_matches[0]


def start_job(
    audio: Path,
    *,
    repo_root: Path,
    local_root: Path,
    host: str | None,
    remote_root: str | None,
    weight_provenance: str | None,
    recognition_mode: str = "multitrack",
    game_model_provenance: str | None = None,
    separator_model_dir: str | None = None,
    time_limit_hours: int = DEFAULT_HYAK_TIME_LIMIT_HOURS,
) -> dict[str, Any]:
    audio = audio.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    local_root = local_root.expanduser().resolve()
    if not audio.is_file():
        raise PrivateBetaError(f"找不到音频文件：{audio}")
    if recognition_mode not in RECOGNITION_MODES:
        raise PrivateBetaError("识别模式必须是 multitrack 或 game_vocal")
    host, remote_root = _load_hyak_configuration(
        repo_root,
        host=host,
        remote_root=remote_root,
    )
    connection = HyakConnection.discover(host)
    if recognition_mode == "game_vocal":
        provenance = _discover_game_model_provenance(
            connection,
            remote_root,
            game_model_provenance,
        )
        resolved_separator_model_dir = _discover_separator_model_dir(
            connection,
            remote_root,
            separator_model_dir,
        )
    else:
        provenance = _discover_weight_provenance(
            connection,
            remote_root,
            weight_provenance,
        )
        resolved_separator_model_dir = None
    project_dir = _unique_project_dir(local_root, audio.stem)
    manifest = initialize_project(audio, project_dir, title=audio.stem, copy_original=True)
    project_id = manifest["project_id"]
    remote_project = f"{remote_root}/projects/private/{project_id}"
    run_prefix = (
        "game-vocal-beta"
        if recognition_mode == "game_vocal"
        else "muscriptor-beta"
    )
    run_id = (
        f"{run_prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid4().hex[:8]}"
    )
    bundle_id = f"{run_id}-multitrack"
    separator_run_id = f"{run_id}-separator-vocal"

    code_commit = _sync_code(connection, repo_root, remote_root)
    _sync_project_to_hyak(connection, project_dir, remote_project)
    remote_repo = f"{remote_root}/repo"
    remote_logs = f"{remote_project}/logs"
    connection.remote(f"mkdir -p {shlex.quote(remote_logs)}")
    gpu_plan = _plan_hyak_gpu(
        connection,
        time_limit_hours=time_limit_hours,
        allow_preemptible=recognition_mode != "game_vocal",
    )
    if recognition_mode == "game_vocal":
        exports = {
            "AMT_REPO_ROOT": remote_repo,
            "PROJECT_DIR": remote_project,
            "SEPARATOR_MODEL_DIR": str(resolved_separator_model_dir),
            "GAME_MODEL_PROVENANCE": provenance,
            "SEPARATOR_VOCAL_RUN_ID": separator_run_id,
            "GAME_RUN_ID": run_id,
            "AMT_BUNDLE_ID": bundle_id,
        }
        slurm_script = "slurm/43_private_beta_game_vocal.slurm"
    else:
        exports = {
            "AMT_REPO_ROOT": remote_repo,
            "PROJECT_DIR": remote_project,
            "MUSCRIPTOR_WEIGHT_PROVENANCE": provenance,
            "MUSCRIPTOR_RUN_ID": run_id,
            "AMT_BUNDLE_ID": bundle_id,
        }
        slurm_script = "slurm/40_private_beta_muscriptor.slurm"
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in exports.items()
    )
    resource_arguments = " ".join(
        shlex.quote(value) for value in gpu_plan.submission_arguments
    )
    submit = (
        f"cd {shlex.quote(remote_repo)} && {env_prefix} "
        "sbatch --parsable "
        f"{resource_arguments} "
        f"--output={shlex.quote(remote_logs + '/slurm-%j.out')} "
        f"--error={shlex.quote(remote_logs + '/slurm-%j.err')} "
        f"{slurm_script}"
    )
    job_id = connection.remote(submit).split(";", 1)[0].strip()
    if not job_id.isdigit():
        raise PrivateBetaError(f"Hyak 返回了无效 job id：{job_id!r}")

    state: dict[str, Any] = {
        "schema_version": 1,
        "backend": "hyak",
        "status": "submitted",
        "submitted_at": _utc_now(),
        "project_id": project_id,
        "local_project_dir": str(project_dir),
        "remote_project_dir": remote_project,
        "host": host,
        "remote_root": remote_root,
        "job_id": job_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "weight_provenance_path": provenance,
        "recognition_mode": recognition_mode,
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "queued",
        **gpu_plan.state_fields(),
    }
    if recognition_mode == "game_vocal":
        state.update(
            {
                "task_kind": "game_vocal_transcription",
                "separator_run_id": separator_run_id,
                "separator_model_dir": str(resolved_separator_model_dir),
                "game_model_provenance_path": provenance,
            }
        )
    _write_state(project_dir, state)
    return state


def start_game_vocal_job(
    project_dir: Path,
    *,
    repo_root: Path,
    host: str | None,
    remote_root: str | None,
    game_model_provenance: str | None,
    separator_model_dir: str | None,
    time_limit_hours: int = DEFAULT_HYAK_TIME_LIMIT_HOURS,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    project = load_project(project_dir)
    project_id = project["project_id"]
    if _canonical_filesystem_text(project_dir.name) != _canonical_filesystem_text(
        project_id
    ):
        raise PrivateBetaError("项目目录与项目身份不匹配")
    _archive_previous_state(project_dir)
    host, remote_root = _load_hyak_configuration(
        repo_root,
        host=host,
        remote_root=remote_root,
    )
    connection = HyakConnection.discover(host)
    provenance = _discover_game_model_provenance(
        connection,
        remote_root,
        game_model_provenance,
    )
    resolved_separator_model_dir = _discover_separator_model_dir(
        connection,
        remote_root,
        separator_model_dir,
    )
    run_id = (
        f"game-vocal-beta-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid4().hex[:8]}"
    )
    separator_run_id = f"{run_id}-separator-vocal"
    bundle_id = f"{run_id}-multitrack"
    remote_project = f"{remote_root}/projects/private/{project_id}"
    code_commit = _sync_code(connection, repo_root, remote_root)
    _sync_project_to_hyak(connection, project_dir, remote_project)
    remote_repo = f"{remote_root}/repo"
    remote_logs = f"{remote_project}/logs"
    connection.remote(f"mkdir -p {shlex.quote(remote_logs)}")
    gpu_plan = _plan_hyak_gpu(
        connection,
        time_limit_hours=time_limit_hours,
        allow_preemptible=False,
    )
    exports = {
        "AMT_REPO_ROOT": remote_repo,
        "PROJECT_DIR": remote_project,
        "SEPARATOR_MODEL_DIR": resolved_separator_model_dir,
        "GAME_MODEL_PROVENANCE": provenance,
        "SEPARATOR_VOCAL_RUN_ID": separator_run_id,
        "GAME_RUN_ID": run_id,
        "AMT_BUNDLE_ID": bundle_id,
    }
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in exports.items()
    )
    resource_arguments = " ".join(
        shlex.quote(value) for value in gpu_plan.submission_arguments
    )
    submit = (
        f"cd {shlex.quote(remote_repo)} && {env_prefix} "
        "sbatch --parsable "
        f"{resource_arguments} "
        f"--output={shlex.quote(remote_logs + '/slurm-%j.out')} "
        f"--error={shlex.quote(remote_logs + '/slurm-%j.err')} "
        "slurm/43_private_beta_game_vocal.slurm"
    )
    job_id = connection.remote(submit).split(";", 1)[0].strip()
    if not job_id.isdigit():
        raise PrivateBetaError(f"Hyak 返回了无效 job id：{job_id!r}")
    state: dict[str, Any] = {
        "schema_version": 1,
        "task_kind": "game_vocal_transcription",
        "recognition_mode": "game_vocal",
        "backend": "hyak",
        "status": "submitted",
        "submitted_at": _utc_now(),
        "project_id": project_id,
        "local_project_dir": str(project_dir),
        "remote_project_dir": remote_project,
        "host": host,
        "remote_root": remote_root,
        "job_id": job_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "separator_run_id": separator_run_id,
        "separator_model_dir": resolved_separator_model_dir,
        "game_model_provenance_path": provenance,
        "weight_provenance_path": provenance,
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "queued",
        **gpu_plan.state_fields(),
    }
    _write_state(project_dir, state)
    return state


def _prepare_gap_recovery_request(
    project_dir: Path,
    *,
    repo_root: Path,
    run_id: str,
    source_bundle_id: str,
    source_track_id: str,
    intervals: list[tuple[float, float]],
) -> Path:
    _ensure_repository_imports(repo_root)
    try:
        from workers.muscriptor.gap_probe import spec_as_dict
        from workers.muscriptor.targeted_gap_recovery import plan_selected_gaps
    except ImportError as exc:
        raise PrivateBetaError(
            "无法加载空缺重算组件；请确认 App 与仓库来自同一版本"
        ) from exc

    project_dir = project_dir.expanduser().resolve()
    _require_safe_identifier(run_id, label="recovery run")
    _require_safe_identifier(source_bundle_id, label="source bundle")
    _require_safe_identifier(source_track_id, label="source track")
    try:
        spec = plan_selected_gaps(
            project_dir,
            probe_id=run_id,
            source_bundle_id=source_bundle_id,
            source_track_id=source_track_id,
            intervals=intervals,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise PrivateBetaError(str(exc)) from exc
    request_path = project_dir / "requests" / f"{run_id}.json"
    if request_path.exists() or request_path.is_symlink():
        raise PrivateBetaError("空缺重算请求标识发生冲突，请重试")
    request_path.parent.mkdir(parents=True, exist_ok=True)

    atomic_write_json(request_path, spec_as_dict(spec))
    return request_path


def start_gap_recovery_job(
    project_dir: Path,
    *,
    repo_root: Path,
    source_bundle_id: str,
    source_track_id: str,
    intervals: list[tuple[float, float]],
    host: str | None,
    remote_root: str | None,
    weight_provenance: str | None,
    time_limit_hours: int = DEFAULT_HYAK_TIME_LIMIT_HOURS,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    project = load_project(project_dir)
    project_id = project["project_id"]
    if _canonical_filesystem_text(project_dir.name) != _canonical_filesystem_text(
        project_id
    ):
        raise PrivateBetaError("项目目录与项目身份不匹配")
    _archive_previous_state(project_dir)
    host, remote_root = _load_hyak_configuration(
        repo_root,
        host=host,
        remote_root=remote_root,
    )
    connection = HyakConnection.discover(host)
    provenance = _discover_weight_provenance(
        connection,
        remote_root,
        weight_provenance,
    )
    run_id = (
        f"gap-recovery-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid4().hex[:8]}"
    )
    bundle_id = f"{run_id}-multitrack"
    request_path = _prepare_gap_recovery_request(
        project_dir,
        repo_root=repo_root,
        run_id=run_id,
        source_bundle_id=source_bundle_id,
        source_track_id=source_track_id,
        intervals=intervals,
    )
    remote_project = f"{remote_root}/projects/private/{project_id}"
    code_commit = _sync_code(connection, repo_root, remote_root)
    _sync_project_to_hyak(connection, project_dir, remote_project)
    _sync_bundle_to_hyak(
        connection,
        project_dir,
        remote_project,
        source_bundle_id,
    )
    remote_repo = f"{remote_root}/repo"
    remote_logs = f"{remote_project}/logs"
    remote_request = (
        f"{remote_project}/{request_path.relative_to(project_dir).as_posix()}"
    )
    connection.remote(f"mkdir -p {shlex.quote(remote_logs)}")
    gpu_plan = _plan_hyak_gpu(
        connection,
        time_limit_hours=time_limit_hours,
    )
    exports = {
        "AMT_REPO_ROOT": remote_repo,
        "PROJECT_DIR": remote_project,
        "MUSCRIPTOR_WEIGHT_PROVENANCE": provenance,
        "TARGETED_GAP_CONFIG": remote_request,
        "AMT_BUNDLE_ID": bundle_id,
    }
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in exports.items()
    )
    resource_arguments = " ".join(
        shlex.quote(value) for value in gpu_plan.submission_arguments
    )
    submit = (
        f"cd {shlex.quote(remote_repo)} && {env_prefix} "
        "sbatch --parsable "
        f"{resource_arguments} "
        f"--output={shlex.quote(remote_logs + '/slurm-%j.out')} "
        f"--error={shlex.quote(remote_logs + '/slurm-%j.err')} "
        "slurm/42_targeted_gap_recovery.slurm"
    )
    job_id = connection.remote(submit).split(";", 1)[0].strip()
    if not job_id.isdigit():
        raise PrivateBetaError(f"Hyak 返回了无效 job id：{job_id!r}")
    state: dict[str, Any] = {
        "schema_version": 1,
        "task_kind": "targeted_gap_recovery",
        "backend": "hyak",
        "status": "submitted",
        "submitted_at": _utc_now(),
        "project_id": project_id,
        "local_project_dir": str(project_dir),
        "remote_project_dir": remote_project,
        "host": host,
        "remote_root": remote_root,
        "job_id": job_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "source_bundle_id": source_bundle_id,
        "source_track_id": source_track_id,
        "recovery_request_path": str(request_path),
        "selected_gap_count": len(intervals),
        "weight_provenance_path": provenance,
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "queued",
        **gpu_plan.state_fields(),
    }
    _write_state(project_dir, state)
    return state


def start_local_gap_recovery_job(
    project_dir: Path,
    *,
    repo_root: Path,
    source_bundle_id: str,
    source_track_id: str,
    intervals: list[tuple[float, float]],
    device: str,
    weight_provenance: str | None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    project = load_project(project_dir)
    project_id = project["project_id"]
    if _canonical_filesystem_text(project_dir.name) != _canonical_filesystem_text(
        project_id
    ):
        raise PrivateBetaError("项目目录与项目身份不匹配")
    _archive_previous_state(project_dir)
    readiness = local_readiness(
        repo_root,
        device=device,
        weight_provenance=weight_provenance,
    )
    if readiness["ready"] is not True:
        raise PrivateBetaError(str(readiness["readiness_message"]))
    run_id = (
        f"gap-recovery-local-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid4().hex[:8]}"
    )
    bundle_id = f"{run_id}-multitrack"
    request_path = _prepare_gap_recovery_request(
        project_dir,
        repo_root=repo_root,
        run_id=run_id,
        source_bundle_id=source_bundle_id,
        source_track_id=source_track_id,
        intervals=intervals,
    )
    job_id = f"local-{uuid4().hex[:12]}"
    log_path = project_dir / "logs/local-compute.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    code_commit = _run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
    ).stdout.strip()
    state: dict[str, Any] = {
        "schema_version": 1,
        "task_kind": "targeted_gap_recovery",
        "backend": "local",
        "status": "submitted",
        "submitted_at": _utc_now(),
        "project_id": project_id,
        "local_project_dir": str(project_dir),
        "job_id": job_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "source_bundle_id": source_bundle_id,
        "source_track_id": source_track_id,
        "recovery_request_path": str(request_path),
        "selected_gap_count": len(intervals),
        "weight_provenance_path": readiness["weight_provenance_path"],
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "starting",
        "local_device": device,
        "local_log_path": str(log_path),
    }
    _write_state(project_dir, state)
    environment = os.environ.copy()
    background_threads = max(1, (os.cpu_count() or 2) // 2)
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": str(background_threads),
            "MKL_NUM_THREADS": str(background_threads),
        }
    )
    if device == "mps":
        environment["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    with log_path.open("a", encoding="utf-8") as log_handle:
        try:
            process = subprocess.Popen(
                _local_worker_command(project_dir, repo_root=repo_root),
                cwd=repo_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            state["status"] = "failed"
            state["slurm_state"] = "FAILED"
            state["pipeline_stage"] = "failed"
            state["completed_at"] = _utc_now()
            state["failure_reason"] = f"无法启动本机后台任务：{exc}"
            state["local_pid"] = 2
            _write_state(project_dir, state)
            raise PrivateBetaError(state["failure_reason"]) from exc
    state["local_pid"] = process.pid
    state["status"] = "running"
    state["slurm_state"] = "RUNNING"
    state["pipeline_stage"] = "targeted_gap_recovery"
    _write_state(project_dir, state)
    if process.stdin is not None:
        process.stdin.write("start\n")
        process.stdin.close()
    return state


def _run_local_gap_recovery_pipeline(
    project_dir: Path,
    *,
    repo_root: Path,
    state: dict[str, Any],
) -> int:
    from workers.muscriptor.targeted_gap_recovery import run_selected_recovery

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PrivateBetaError("本机找不到 ffmpeg")
    try:
        state["status"] = "running"
        state["slurm_state"] = "RUNNING"
        state["pipeline_stage"] = "targeted_gap_recovery"
        _write_state(project_dir, state)
        manifest = run_selected_recovery(
            project_dir,
            Path(state["recovery_request_path"]),
            output_bundle_id=state["bundle_id"],
            worker_env=repo_root / "workers/muscriptor/.venv",
            weight_provenance=Path(
                state["weight_provenance_path"]
            ).expanduser().resolve(),
            ffmpeg=ffmpeg,
            device=state["local_device"],
            require_slurm=False,
            execution_backend="local",
        )
        if manifest.get("status") != "succeeded":
            raise PrivateBetaError("本机所选空缺重算未成功")
        state["pipeline_stage"] = "packaging"
        _write_state(project_dir, state)
        if not (
            project_dir
            / "exports"
            / state["bundle_id"]
            / "bundle_manifest.json"
        ).is_file():
            raise PrivateBetaError("本机空缺重算没有生成最终版本")
        _record_result_summary(project_dir, state)
        state["status"] = "succeeded"
        state["slurm_state"] = "COMPLETED"
        state["pipeline_stage"] = "complete"
        state["completed_at"] = _utc_now()
        _write_state(project_dir, state)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        state["status"] = "failed"
        state["slurm_state"] = "FAILED"
        state["pipeline_stage"] = "failed"
        state["completed_at"] = _utc_now()
        state["failure_reason"] = str(exc)
        _write_state(project_dir, state)
        return 1


def _run_local_pipeline(project_dir: Path, *, repo_root: Path) -> int:
    repo_root = repo_root.expanduser().resolve()
    _ensure_repository_imports(repo_root)
    from .bundle import build_muscriptor_multitrack_bundle
    from workers.muscriptor import gap_probe, run_baseline

    project_dir = project_dir.expanduser().resolve()
    state = _load_state(project_dir)
    if state["backend"] != "local":
        raise PrivateBetaError("本机 worker 拒绝非本机任务状态")
    if state["local_pid"] != os.getpid():
        raise PrivateBetaError("本机 worker PID 与任务状态不匹配")
    try:
        os.nice(10)
    except OSError:
        pass
    if state.get("task_kind", "full_transcription") == "targeted_gap_recovery":
        return _run_local_gap_recovery_pipeline(
            project_dir,
            repo_root=repo_root,
            state=state,
        )

    run_dir = project_dir / "runs" / state["run_id"]
    raw_bundle = project_dir / "exports" / f"{state['bundle_id']}-raw"
    final_bundle = project_dir / "exports" / state["bundle_id"]
    worker_env = repo_root / "workers/muscriptor/.venv"
    provenance = Path(state["weight_provenance_path"]).expanduser().resolve()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PrivateBetaError("本机找不到 ffmpeg")

    try:
        state["status"] = "running"
        state["slurm_state"] = "RUNNING"
        state["pipeline_stage"] = "full_transcription"
        _write_state(project_dir, state)
        exit_code = run_baseline.main(
            [
                "--project",
                str(project_dir),
                "--worker-env",
                str(worker_env),
                "--weight-provenance",
                str(provenance),
                "--run-id",
                state["run_id"],
                "--beam-size",
                "4",
                "--device",
                state["local_device"],
                "--prelude-forcing",
                "--skip-midi",
            ]
        )
        if exit_code != 0:
            raise PrivateBetaError("本机 MuScriptor 整曲识别失败")

        build_muscriptor_multitrack_bundle(project_dir, run_dir, raw_bundle)
        state["pipeline_stage"] = "gap_planning"
        _write_state(project_dir, state)
        try:
            state["pipeline_stage"] = "automatic_gap_recovery"
            _write_state(project_dir, state)
            recovery = gap_probe.run_automatic_probe(
                project_dir,
                probe_id=f"{state['run_id']}-auto-gap",
                source_bundle_id=raw_bundle.name,
                output_bundle_id=state["bundle_id"],
                worker_env=worker_env,
                weight_provenance=provenance,
                ffmpeg=ffmpeg,
                source_voice_track_id="voice",
                device=state["local_device"],
                require_slurm=False,
                execution_backend="local",
            )
            if recovery.get("status") != "succeeded":
                raise PrivateBetaError("本机自动补漏未成功")
        except (OSError, RuntimeError, ValueError) as exc:
            if not final_bundle.exists():
                build_muscriptor_multitrack_bundle(
                    project_dir,
                    run_dir,
                    final_bundle,
                )
            state["failure_reason"] = f"自动补漏回退为原始多轨：{exc}"

        state["pipeline_stage"] = "packaging"
        _write_state(project_dir, state)
        if not (final_bundle / "bundle_manifest.json").is_file():
            raise PrivateBetaError("本机任务没有生成最终多轨包")
        state["status"] = "succeeded"
        state["slurm_state"] = "COMPLETED"
        state["pipeline_stage"] = "complete"
        state["completed_at"] = _utc_now()
        _write_state(project_dir, state)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        state["status"] = "failed"
        state["slurm_state"] = "FAILED"
        state["pipeline_stage"] = "failed"
        state["completed_at"] = _utc_now()
        state["failure_reason"] = str(exc)
        _write_state(project_dir, state)
        return 1


def _local_worker_matches(pid: int, project_dir: Path) -> bool:
    try:
        command = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (
        command.returncode == 0
        and "amt_core.private_beta run-local-worker" in command.stdout
        and str(project_dir) in command.stdout
    )


def _refresh_local_job(project_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("status") in TERMINAL_STATUSES:
        return state
    pid = int(state["local_pid"])
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        state["status"] = "failed"
        state["slurm_state"] = "FAILED"
        state["pipeline_stage"] = "failed"
        state["completed_at"] = _utc_now()
        state["failure_reason"] = "本机后台进程已退出，结果未完成"
        _write_state(project_dir, state)
    except PermissionError as exc:
        raise PrivateBetaError("无法确认本机后台进程状态") from exc
    else:
        if not _local_worker_matches(pid, project_dir):
            state["status"] = "failed"
            state["slurm_state"] = "FAILED"
            state["pipeline_stage"] = "failed"
            state["completed_at"] = _utc_now()
            state["failure_reason"] = "本机后台进程身份已失效，结果未完成"
            _write_state(project_dir, state)
            return state
        state["status"] = "running"
        state["slurm_state"] = "RUNNING"
        _write_state(project_dir, state)
    return state


def cancel_local_job(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    state = _load_state(project_dir)
    if state["backend"] != "local":
        raise PrivateBetaError("只能停止本机计算任务")
    if state["status"] in TERMINAL_STATUSES:
        return state
    pid = int(state["local_pid"])
    if not _local_worker_matches(pid, project_dir):
        raise PrivateBetaError("本机任务进程身份不匹配，拒绝停止")
    try:
        if os.getpgid(pid) != pid:
            raise PrivateBetaError("本机任务进程组身份不匹配，拒绝停止")
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    state["status"] = "cancelled"
    state["slurm_state"] = "CANCELLED"
    state["pipeline_stage"] = "failed"
    state["completed_at"] = _utc_now()
    state["failure_reason"] = "用户停止了本机计算"
    _write_state(project_dir, state)
    return state


def _fetch_results(
    connection: HyakConnection,
    project_dir: Path,
    state: dict[str, Any],
) -> None:
    remote_project = state["remote_project_dir"]
    for relative in (
        f"runs/{state['run_id']}",
        f"exports/{state['bundle_id']}",
        "logs",
    ):
        local_parent = project_dir / Path(relative).parent
        local_parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "rsync",
                "-az",
                "--partial",
                "-e",
                connection.rsync_shell(),
                f"{connection.host}:{remote_project}/{relative}/",
                f"{project_dir / relative}/",
            ],
            timeout=1800,
        )
    if state.get("recognition_mode", "multitrack") == "game_vocal":
        for run_id in (
            state["separator_run_id"],
            f"{state['run_id']}-rhythm",
        ):
            remote_path = f"{remote_project}/runs/{run_id}"
            if connection.remote(
                f"test -d {shlex.quote(remote_path)} && printf yes || true",
                timeout=10,
            ) != "yes":
                continue
            local_path = project_dir / "runs" / run_id
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    "rsync",
                    "-az",
                    "--partial",
                    "-e",
                    connection.rsync_shell(),
                    f"{connection.host}:{remote_path}/",
                    f"{local_path}/",
                ],
                timeout=1800,
            )
        return
    if state.get("task_kind", "full_transcription") == "targeted_gap_recovery":
        manifest_path = (
            project_dir / "runs" / state["run_id"] / "run_manifest.json"
        )
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                manifest = {}
            for child in manifest.get("child_runs", []):
                child_run_id = (
                    child.get("run_id") if isinstance(child, dict) else None
                )
                if (
                    not isinstance(child_run_id, str)
                    or STATE_IDENTIFIER.fullmatch(child_run_id) is None
                ):
                    continue
                remote_path = f"{remote_project}/runs/{child_run_id}"
                local_path = project_dir / "runs" / child_run_id
                local_path.parent.mkdir(parents=True, exist_ok=True)
                _run(
                    [
                        "rsync",
                        "-az",
                        "--partial",
                        "-e",
                        connection.rsync_shell(),
                        f"{connection.host}:{remote_path}/",
                        f"{local_path}/",
                    ],
                    timeout=1800,
                )
        return
    probe_id = f"{state['run_id']}-auto-gap"
    rhythm_run_id = f"{state['run_id']}-rhythm"
    for relative in (
        f"runs/{rhythm_run_id}",
        f"runs/{probe_id}",
        f"reports/{probe_id}",
    ):
        remote_path = f"{remote_project}/{relative}"
        if connection.remote(
            f"test -d {shlex.quote(remote_path)} && printf yes || true",
            timeout=10,
        ) != "yes":
            continue
        local_parent = project_dir / Path(relative).parent
        local_parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "rsync",
                "-az",
                "--partial",
                "-e",
                connection.rsync_shell(),
                f"{connection.host}:{remote_path}/",
                f"{project_dir / relative}/",
            ],
            timeout=1800,
        )


def _record_result_summary(
    project_dir: Path,
    state: dict[str, Any],
) -> None:
    if state.get("task_kind") != "targeted_gap_recovery":
        return
    manifest_path = (
        project_dir
        / "exports"
        / state["bundle_id"]
        / "bundle_manifest.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    claims = manifest.get("claims") if isinstance(manifest, dict) else None
    count = (
        claims.get("recovered_candidate_note_count")
        if isinstance(claims, dict)
        else None
    )
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        state["recovered_candidate_note_count"] = count


def _fetch_failure_artifacts(
    connection: HyakConnection,
    project_dir: Path,
    state: dict[str, Any],
) -> None:
    remote_project = state["remote_project_dir"]
    for relative in (f"runs/{state['run_id']}", "logs"):
        local_parent = project_dir / Path(relative).parent
        local_parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "rsync",
                "-az",
                "--partial",
                "-e",
                connection.rsync_shell(),
                f"{connection.host}:{remote_project}/{relative}/",
                f"{project_dir / relative}/",
            ],
            timeout=1800,
        )


def _record_failure_reason(
    project_dir: Path,
    state: dict[str, Any],
) -> None:
    manifest_path = (
        project_dir / "runs" / state["run_id"] / "run_manifest.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    error = manifest.get("error") if isinstance(manifest, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message.strip():
        state["failure_reason"] = message.strip()


def _pipeline_stage(
    connection: HyakConnection,
    state: dict[str, Any],
) -> str:
    remote_project = state["remote_project_dir"]
    run_id = state["run_id"]
    bundle_id = state["bundle_id"]
    if state.get("recognition_mode", "multitrack") == "game_vocal":
        rhythm_run_id = f"{run_id}-rhythm"
        checks = (
            (
                f"{remote_project}/exports/{bundle_id}/bundle_manifest.json",
                "packaging",
            ),
            (
                f"{remote_project}/runs/{rhythm_run_id}/run_manifest.json",
                "packaging",
            ),
            (
                f"{remote_project}/runs/{run_id}/run_manifest.json",
                "rhythm_analysis",
            ),
            (
                f"{remote_project}/runs/{state['separator_run_id']}/run_manifest.json",
                "game_vocal_transcription",
            ),
        )
        command = " ".join(
            ("if " if index == 0 else "elif ")
            + f"test -f {shlex.quote(path)}; then printf {shlex.quote(stage)};"
            for index, (path, stage) in enumerate(checks)
        )
        command += " else printf source_separation; fi"
        stage = connection.remote(command, timeout=15)
        return stage if stage else "source_separation"
    if state.get("task_kind", "full_transcription") == "targeted_gap_recovery":
        bundle_manifest = (
            f"{remote_project}/exports/{bundle_id}/bundle_manifest.json"
        )
        run_manifest = f"{remote_project}/runs/{run_id}/run_manifest.json"
        command = (
            f"if test -f {shlex.quote(bundle_manifest)}; "
            "then printf packaging; "
            f"elif test -f {shlex.quote(run_manifest)}; "
            "then printf targeted_gap_recovery; "
            "else printf starting; fi"
        )
        stage = connection.remote(command, timeout=15)
        return stage if stage else "starting"
    probe_id = f"{run_id}-auto-gap"
    rhythm_run_id = f"{run_id}-rhythm"
    raw_bundle_id = f"{bundle_id}-raw"
    checks = (
        (
            f"{remote_project}/exports/{bundle_id}/bundle_manifest.json",
            "packaging",
        ),
        (
            f"{remote_project}/runs/{probe_id}/run_manifest.json",
            "automatic_gap_recovery",
        ),
        (
            f"{remote_project}/reports/{probe_id}/plan.json",
            "gap_planning",
        ),
        (
            f"{remote_project}/exports/{raw_bundle_id}/bundle_manifest.json",
            "gap_planning",
        ),
        (
            f"{remote_project}/runs/{rhythm_run_id}/run_manifest.json",
            "rhythm_analysis",
        ),
        (
            f"{remote_project}/runs/{run_id}/run_manifest.json",
            "full_transcription",
        ),
    )
    command = " ".join(
        (
            "if "
            if index == 0
            else "elif "
        )
        + f"test -f {shlex.quote(path)}; then printf {shlex.quote(stage)};"
        for index, (path, stage) in enumerate(checks)
    )
    command += " else printf starting; fi"
    stage = connection.remote(command, timeout=15)
    return stage if stage else "starting"


def refresh_job(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    state = _load_state(project_dir)
    if state["backend"] == "local":
        return _refresh_local_job(project_dir, state)
    if state.get("status") in {"succeeded", "failed", "cancelled"}:
        if state.get("status") == "failed" and not state.get("failure_reason"):
            try:
                connection = HyakConnection.discover(state["host"])
                _fetch_failure_artifacts(connection, project_dir, state)
                _record_failure_reason(project_dir, state)
                _write_state(project_dir, state)
            except PrivateBetaError:
                pass
        return state
    connection = HyakConnection.discover(state["host"])
    job_id = str(state["job_id"])
    queue = connection.remote(
        f"squeue -h -j {shlex.quote(job_id)} -o %T",
        timeout=15,
    )
    if queue:
        slurm_state = queue.splitlines()[0].strip().upper()
    else:
        accounting = connection.remote(
            f"sacct -X -n -P -j {shlex.quote(job_id)} --format=JobIDRaw,State,ExitCode",
            timeout=20,
        )
        records = [line.split("|") for line in accounting.splitlines() if line.strip()]
        exact = next((record for record in records if record[0] == job_id), None)
        slurm_state = exact[1].split("+", 1)[0].upper() if exact and len(exact) > 1 else "UNKNOWN"
        if exact and len(exact) > 2:
            state["slurm_exit_code"] = exact[2]

    state["slurm_state"] = slurm_state
    if slurm_state == "COMPLETED":
        _fetch_results(connection, project_dir, state)
        _record_result_summary(project_dir, state)
        state["status"] = "succeeded"
        state["pipeline_stage"] = "complete"
        state["completed_at"] = _utc_now()
    elif slurm_state in {
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "PREEMPTED",
        "BOOT_FAIL",
        "DEADLINE",
    }:
        try:
            _fetch_failure_artifacts(connection, project_dir, state)
            _record_failure_reason(project_dir, state)
        except PrivateBetaError:
            pass
        state["status"] = "failed"
        state["pipeline_stage"] = "failed"
        state["completed_at"] = _utc_now()
    else:
        state["status"] = "running" if slurm_state == "RUNNING" else "submitted"
        state["pipeline_stage"] = (
            _pipeline_stage(connection, state)
            if slurm_state == "RUNNING"
            else "queued"
        )
    _write_state(project_dir, state)
    return state


def connection_status(host: str) -> dict[str, Any]:
    connection = HyakConnection.discover(host)
    hostname = connection.remote("hostname && id -un", timeout=15).splitlines()
    return {
        "schema_version": 1,
        "status": "connected",
        "host": hostname[0] if hostname else host,
        "user": hostname[1] if len(hostname) > 1 else None,
        "control_path": str(connection.control_path) if connection.control_path else None,
    }


def _gap_interval_argument(value: str) -> tuple[float, float]:
    try:
        start_text, end_text = value.split(":", 1)
        start = float(start_text)
        end = float(end_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "gap must use start_seconds:end_seconds"
        ) from exc
    if (
        not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise argparse.ArgumentTypeError("gap interval is invalid")
    return start, end


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amt-private-beta")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("audio", type=Path)
    start.add_argument("--repo-root", type=Path, required=True)
    start.add_argument("--local-root", type=Path, required=True)
    start.add_argument("--host")
    start.add_argument("--remote-root")
    start.add_argument(
        "--time-limit-hours",
        type=int,
        choices=range(MIN_HYAK_TIME_LIMIT_HOURS, MAX_HYAK_TIME_LIMIT_HOURS + 1),
        default=DEFAULT_HYAK_TIME_LIMIT_HOURS,
    )
    start.add_argument(
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )
    start.add_argument(
        "--recognition-mode",
        choices=sorted(RECOGNITION_MODES),
        default="multitrack",
    )
    start.add_argument(
        "--game-model-provenance",
        default=os.environ.get("GAME_MODEL_PROVENANCE"),
    )
    start.add_argument(
        "--separator-model-dir",
        default=os.environ.get("SEPARATOR_MODEL_DIR"),
    )

    start_local = subparsers.add_parser("start-local")
    start_local.add_argument("audio", type=Path)
    start_local.add_argument("--repo-root", type=Path, required=True)
    start_local.add_argument("--local-root", type=Path, required=True)
    start_local.add_argument("--device", choices=sorted(LOCAL_DEVICES), required=True)
    start_local.add_argument(
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )

    recover = subparsers.add_parser("start-gap-recovery")
    recover.add_argument("project", type=Path)
    recover.add_argument("--repo-root", type=Path, required=True)
    recover.add_argument("--source-bundle", required=True)
    recover.add_argument("--source-track", required=True)
    recover.add_argument(
        "--gap",
        action="append",
        type=_gap_interval_argument,
        required=True,
    )
    recover.add_argument("--host")
    recover.add_argument("--remote-root")
    recover.add_argument(
        "--time-limit-hours",
        type=int,
        choices=range(MIN_HYAK_TIME_LIMIT_HOURS, MAX_HYAK_TIME_LIMIT_HOURS + 1),
        default=DEFAULT_HYAK_TIME_LIMIT_HOURS,
    )
    recover.add_argument(
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )

    recover_local = subparsers.add_parser("start-local-gap-recovery")
    recover_local.add_argument("project", type=Path)
    recover_local.add_argument("--repo-root", type=Path, required=True)
    recover_local.add_argument("--source-bundle", required=True)
    recover_local.add_argument("--source-track", required=True)
    recover_local.add_argument(
        "--gap",
        action="append",
        type=_gap_interval_argument,
        required=True,
    )
    recover_local.add_argument(
        "--device",
        choices=sorted(LOCAL_DEVICES),
        required=True,
    )
    recover_local.add_argument(
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )

    game_vocal = subparsers.add_parser("start-game-vocal")
    game_vocal.add_argument("project", type=Path)
    game_vocal.add_argument("--repo-root", type=Path, required=True)
    game_vocal.add_argument("--host")
    game_vocal.add_argument("--remote-root")
    game_vocal.add_argument(
        "--time-limit-hours",
        type=int,
        choices=range(MIN_HYAK_TIME_LIMIT_HOURS, MAX_HYAK_TIME_LIMIT_HOURS + 1),
        default=DEFAULT_HYAK_TIME_LIMIT_HOURS,
    )
    game_vocal.add_argument(
        "--game-model-provenance",
        default=os.environ.get("GAME_MODEL_PROVENANCE"),
    )
    game_vocal.add_argument(
        "--separator-model-dir",
        default=os.environ.get("SEPARATOR_MODEL_DIR"),
    )

    status = subparsers.add_parser("status")
    status.add_argument("project", type=Path)

    cancel_local = subparsers.add_parser("cancel-local")
    cancel_local.add_argument("project", type=Path)

    readiness = subparsers.add_parser("local-readiness")
    readiness.add_argument("--repo-root", type=Path, required=True)
    readiness.add_argument("--device", choices=sorted(LOCAL_DEVICES), required=True)
    readiness.add_argument(
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )

    local_worker = subparsers.add_parser("run-local-worker")
    local_worker.add_argument("project", type=Path)
    local_worker.add_argument("--repo-root", type=Path, required=True)

    connection = subparsers.add_parser("connection")
    connection.add_argument("--repo-root", type=Path, default=Path.cwd())
    connection.add_argument("--host")
    connection.add_argument("--remote-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_job(
                args.audio,
                repo_root=args.repo_root,
                local_root=args.local_root,
                host=args.host,
                remote_root=args.remote_root,
                weight_provenance=args.weight_provenance,
                recognition_mode=args.recognition_mode,
                game_model_provenance=args.game_model_provenance,
                separator_model_dir=args.separator_model_dir,
                time_limit_hours=args.time_limit_hours,
            )
        elif args.command == "start-local":
            result = start_local_job(
                args.audio,
                repo_root=args.repo_root,
                local_root=args.local_root,
                device=args.device,
                weight_provenance=args.weight_provenance,
            )
        elif args.command == "start-gap-recovery":
            result = start_gap_recovery_job(
                args.project,
                repo_root=args.repo_root,
                source_bundle_id=args.source_bundle,
                source_track_id=args.source_track,
                intervals=args.gap,
                host=args.host,
                remote_root=args.remote_root,
                weight_provenance=args.weight_provenance,
                time_limit_hours=args.time_limit_hours,
            )
        elif args.command == "start-local-gap-recovery":
            result = start_local_gap_recovery_job(
                args.project,
                repo_root=args.repo_root,
                source_bundle_id=args.source_bundle,
                source_track_id=args.source_track,
                intervals=args.gap,
                device=args.device,
                weight_provenance=args.weight_provenance,
            )
        elif args.command == "start-game-vocal":
            result = start_game_vocal_job(
                args.project,
                repo_root=args.repo_root,
                host=args.host,
                remote_root=args.remote_root,
                game_model_provenance=args.game_model_provenance,
                separator_model_dir=args.separator_model_dir,
                time_limit_hours=args.time_limit_hours,
            )
        elif args.command == "status":
            result = refresh_job(args.project)
        elif args.command == "cancel-local":
            result = cancel_local_job(args.project)
        elif args.command == "local-readiness":
            result = local_readiness(
                args.repo_root,
                device=args.device,
                weight_provenance=args.weight_provenance,
            )
        elif args.command == "run-local-worker":
            sys.stdin.readline()
            return _run_local_pipeline(
                args.project,
                repo_root=args.repo_root,
            )
        elif args.command == "connection":
            host, _remote_root = _load_hyak_configuration(
                args.repo_root.expanduser().resolve(),
                host=args.host,
                remote_root=args.remote_root,
            )
            result = connection_status(host)
        else:
            raise AssertionError(args.command)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
        return 0
    except (PrivateBetaError, AudioToolError, ProjectError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "needs_hyak_login": "Hyak 尚未登录" in str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
