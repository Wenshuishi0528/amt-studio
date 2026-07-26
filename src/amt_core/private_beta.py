from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .project import initialize_project
from .utils import atomic_write_json, slugify

STATE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
HOST_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*"
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
JOB_STATUSES = TERMINAL_STATUSES | {"submitted", "running"}


class PrivateBetaError(RuntimeError):
    """Raised when the bounded Mac-to-Hyak private beta workflow cannot proceed."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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

    host = _safe_host(_require_state_string(state, "host"))
    remote_root = _safe_remote_root(_require_state_string(state, "remote_root"))
    remote_project = _require_state_string(state, "remote_project_dir")
    expected_remote = f"{remote_root}/projects/private/{project_id}"
    if remote_project != expected_remote:
        raise PrivateBetaError("任务状态 remote_project_dir 与项目身份不匹配")

    job_id = _require_state_string(state, "job_id")
    if not job_id.isdigit():
        raise PrivateBetaError("任务状态 job_id 无效")
    run_id = _require_state_string(state, "run_id", pattern=STATE_IDENTIFIER)
    bundle_id = _require_state_string(state, "bundle_id", pattern=STATE_IDENTIFIER)
    if bundle_id != f"{run_id}-multitrack":
        raise PrivateBetaError("任务状态 bundle_id 与 run_id 不匹配")

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
        "gap_planning",
        "automatic_gap_recovery",
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
    for key in ("submitted_at", "updated_at", "completed_at", "slurm_exit_code"):
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
    state["host"] = host
    state["remote_root"] = remote_root
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


def _unique_project_dir(local_root: Path, stem: str) -> Path:
    safe = slugify(stem, fallback="song")[:80]
    candidate = local_root / safe
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return local_root / f"{safe}-{stamp}-{uuid4().hex[:6]}"


def _sync_code(connection: HyakConnection, repo_root: Path, remote_root: str) -> str:
    remote_repo = f"{remote_root}/repo"
    connection.remote(f"mkdir -p {shlex.quote(remote_repo)}")
    commit = _run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
    ).stdout.strip()
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise PrivateBetaError("本地仓库没有可同步的 Git commit")
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
        atomic_write_json(
            snapshot / ".amt-code-snapshot.json",
            {
                "schema_version": 1,
                "commit": commit,
                "dirty": False,
                "source": "git_archive",
            },
        )
        _run(
            [
                "rsync",
                "-az",
                "--delete",
                "--exclude",
                ".git/",
                "--exclude",
                ".venv/",
                "--exclude",
                ".build/",
                "--exclude",
                "dist/",
                "--exclude",
                "__pycache__/",
                "--exclude",
                ".pytest_cache/",
                "--exclude",
                ".ruff_cache/",
                "--exclude",
                "data/private/",
                "--exclude",
                "projects/private/",
                "--exclude",
                "datasets/",
                "--exclude",
                "model-cache/",
                "--exclude",
                "weights/",
                "--exclude",
                "hyak-results/",
                "-e",
                connection.rsync_shell(),
                f"{snapshot}/",
                f"{connection.host}:{remote_repo}/",
            ],
            timeout=180,
        )
    return commit


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


def start_job(
    audio: Path,
    *,
    repo_root: Path,
    local_root: Path,
    host: str | None,
    remote_root: str | None,
    weight_provenance: str | None,
) -> dict[str, Any]:
    audio = audio.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    local_root = local_root.expanduser().resolve()
    if not audio.is_file():
        raise PrivateBetaError(f"找不到音频文件：{audio}")
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
    project_dir = _unique_project_dir(local_root, audio.stem)
    manifest = initialize_project(audio, project_dir, title=audio.stem, copy_original=True)
    project_id = manifest["project_id"]
    remote_project = f"{remote_root}/projects/private/{project_id}"
    run_id = f"muscriptor-beta-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    bundle_id = f"{run_id}-multitrack"

    code_commit = _sync_code(connection, repo_root, remote_root)
    _sync_project_to_hyak(connection, project_dir, remote_project)
    remote_repo = f"{remote_root}/repo"
    remote_logs = f"{remote_project}/logs"
    connection.remote(f"mkdir -p {shlex.quote(remote_logs)}")
    exports = {
        "AMT_REPO_ROOT": remote_repo,
        "PROJECT_DIR": remote_project,
        "MUSCRIPTOR_WEIGHT_PROVENANCE": provenance,
        "MUSCRIPTOR_RUN_ID": run_id,
        "AMT_BUNDLE_ID": bundle_id,
    }
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in exports.items()
    )
    submit = (
        f"cd {shlex.quote(remote_repo)} && {env_prefix} "
        "sbatch --parsable "
        f"--output={shlex.quote(remote_logs + '/slurm-%j.out')} "
        f"--error={shlex.quote(remote_logs + '/slurm-%j.err')} "
        "slurm/40_private_beta_muscriptor.slurm"
    )
    job_id = connection.remote(submit).split(";", 1)[0].strip()
    if not job_id.isdigit():
        raise PrivateBetaError(f"Hyak 返回了无效 job id：{job_id!r}")

    state: dict[str, Any] = {
        "schema_version": 1,
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
        "code_commit": code_commit,
        "slurm_state": "PENDING",
        "pipeline_stage": "queued",
    }
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
    probe_id = f"{state['run_id']}-auto-gap"
    for relative in (f"runs/{probe_id}", f"reports/{probe_id}"):
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


def _pipeline_stage(
    connection: HyakConnection,
    state: dict[str, Any],
) -> str:
    remote_project = state["remote_project_dir"]
    run_id = state["run_id"]
    bundle_id = state["bundle_id"]
    probe_id = f"{run_id}-auto-gap"
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
    if state.get("status") in {"succeeded", "failed", "cancelled"}:
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
        "--weight-provenance",
        default=os.environ.get("MUSCRIPTOR_WEIGHT_PROVENANCE"),
    )

    status = subparsers.add_parser("status")
    status.add_argument("project", type=Path)

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
            )
        elif args.command == "status":
            result = refresh_job(args.project)
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
    except PrivateBetaError as exc:
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
