from __future__ import annotations

import fnmatch
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import time
from typing import Callable


@dataclass
class CommandExecutionResult:
    exit_code: int | None
    timed_out: bool
    canceled: bool
    lease_expired: bool
    duration_seconds: float
    output_path: Path
    output_excerpt: list[str]


class RunCanceledSignal(Exception):
    pass


class LeaseExpiredSignal(Exception):
    pass


def _csv_tokens(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _default_allowed_commands() -> list[str]:
    return [
        "codex",
        "python",
        "python*",
        "git",
        "npm",
        "node",
    ]


def _allowed_command_patterns() -> list[str]:
    raw = os.getenv("WORKER_ALLOWED_COMMANDS", "")
    if raw.strip():
        return _csv_tokens(raw)
    return _default_allowed_commands()


def _default_allowed_paths() -> list[Path]:
    roots: list[Path] = []
    configured_root = os.getenv("WORKER_WORKTREE_ROOT", "/srv/oroboros/worktrees").strip()
    if configured_root:
        roots.append(Path(configured_root).expanduser().resolve())
    return roots


def _allowed_path_roots() -> list[Path]:
    raw = os.getenv("WORKER_ALLOWED_PATHS", "")
    if raw.strip():
        return [Path(item).expanduser().resolve() for item in _csv_tokens(raw)]
    return _default_allowed_paths()


def _is_command_allowed(command: list[str]) -> tuple[bool, str]:
    if not command:
        return False, "empty_command"

    executable = Path(command[0]).name.strip()
    if not executable:
        return False, "empty_executable"
    if executable in {"bash", "sh", "zsh", "dash", "ksh", "fish"}:
        return False, executable

    for pattern in _allowed_command_patterns():
        if fnmatch.fnmatch(executable, pattern):
            return True, executable
    return False, executable


def _is_path_allowed(path: Path) -> tuple[bool, Path]:
    resolved = path.expanduser().resolve()
    for root in _allowed_path_roots():
        if resolved == root or root in resolved.parents:
            return True, root
    return False, resolved


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}

    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip()
    return parsed


def _build_subprocess_env(env_overlay: dict[str, str] | None) -> dict[str, str]:
    allowlist_raw = os.getenv(
        "WORKER_SUBPROCESS_ENV_ALLOWLIST",
        "PATH,HOME,LANG,LC_ALL,LC_CTYPE,PYTHONPATH,VIRTUAL_ENV,TMPDIR",
    )
    allowlist = set(_csv_tokens(allowlist_raw))

    env: dict[str, str] = {}
    for key in allowlist:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value

    preview_env_file = os.getenv("WORKER_PREVIEW_ENV_FILE", "").strip()
    if preview_env_file:
        env.update(_parse_env_file(Path(preview_env_file).expanduser()))

    if env_overlay:
        env.update(env_overlay)

    blocklist_raw = os.getenv(
        "WORKER_SUBPROCESS_ENV_BLOCKLIST",
        "DATABASE_URL,REDIS_URL,OPENAI_API_KEY,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY,"
        "GOOGLE_APPLICATION_CREDENTIALS",
    )
    for key in _csv_tokens(blocklist_raw):
        env.pop(key, None)

    return env


def _resolve_codex_binary() -> str:
    configured = os.getenv("WORKER_CODEX_BIN", "").strip()
    if configured:
        return configured

    discovered = shutil.which("codex")
    if discovered:
        return discovered

    common_paths = [
        "/Applications/Codex.app/Contents/Resources/codex",
    ]
    for raw in common_paths:
        candidate = Path(raw).expanduser()
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return "codex"


def build_codex_command(prompt: str, worktree_path: Path) -> list[str]:
    template = os.getenv("WORKER_CODEX_COMMAND_TEMPLATE")
    if template:
        rendered = template.format(
            prompt=shlex.quote(prompt),
            worktree_path=shlex.quote(str(worktree_path)),
        )
        command = shlex.split(rendered)
        if command:
            # Resolve bare "codex" in templates to an executable path so
            # worker subprocesses don't depend on inherited PATH contents.
            executable = command[0].strip()
            if executable and "/" not in executable and executable == "codex":
                command[0] = _resolve_codex_binary()
            return command

    binary = _resolve_codex_binary()
    args = shlex.split(os.getenv("WORKER_CODEX_ARGS", ""))
    if args:
        return [binary, *args, prompt]

    # Default to non-interactive Codex mode so worker runs do not require a TTY.
    return [binary, "exec", "--full-auto", "--skip-git-repo-check", "--cd", str(worktree_path), prompt]


def run_codex_command(
    *,
    command: list[str],
    worktree_path: Path,
    output_path: Path,
    timeout_seconds: int,
    poll_interval_seconds: float,
    should_cancel: Callable[[], bool] | None = None,
    on_tick: Callable[[], None] | None = None,
    env: dict[str, str] | None = None,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    time_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CommandExecutionResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = ""
    timed_out = False
    canceled = False
    lease_expired = False
    start = time_fn()

    command_allowed, executable = _is_command_allowed(command)
    if not command_allowed:
        output_text = f"Blocked by command allowlist: {executable}"
        output_path.write_text(output_text, encoding="utf-8")
        return CommandExecutionResult(
            exit_code=126,
            timed_out=False,
            canceled=False,
            lease_expired=False,
            duration_seconds=max(0.0, time_fn() - start),
            output_path=output_path,
            output_excerpt=[output_text],
        )

    path_allowed, blocked_value = _is_path_allowed(worktree_path)
    if not path_allowed:
        output_text = f"Blocked by path allowlist: {blocked_value}"
        output_path.write_text(output_text, encoding="utf-8")
        return CommandExecutionResult(
            exit_code=126,
            timed_out=False,
            canceled=False,
            lease_expired=False,
            duration_seconds=max(0.0, time_fn() - start),
            output_path=output_path,
            output_excerpt=[output_text],
        )

    try:
        process = popen_factory(
            command,
            cwd=str(worktree_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_build_subprocess_env(env),
        )
    except OSError as exc:
        output_text = f"Failed to start command: {exc}"
        output_path.write_text(output_text, encoding="utf-8")
        return CommandExecutionResult(
            exit_code=127,
            timed_out=False,
            canceled=False,
            lease_expired=False,
            duration_seconds=max(0.0, time_fn() - start),
            output_path=output_path,
            output_excerpt=[output_text],
        )

    try:
        while True:
            elapsed = time_fn() - start
            if elapsed >= timeout_seconds:
                timed_out = True
                process.kill()
                break

            if should_cancel and should_cancel():
                canceled = True
                process.terminate()
                break

            try:
                if on_tick:
                    on_tick()
            except RunCanceledSignal:
                canceled = True
                process.terminate()
                break
            except LeaseExpiredSignal:
                lease_expired = True
                process.terminate()
                break

            try:
                output_text, _ = process.communicate(timeout=poll_interval_seconds)
                break
            except subprocess.TimeoutExpired as exc:
                if isinstance(exc.output, str):
                    output_text = exc.output
                sleep_fn(0)
                continue

        if process.poll() is None:
            try:
                output_text, _ = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                output_text, _ = process.communicate()
    finally:
        output_path.write_text(output_text, encoding="utf-8")

    excerpt = output_text.strip().splitlines()[-20:]
    return CommandExecutionResult(
        exit_code=process.returncode,
        timed_out=timed_out,
        canceled=canceled,
        lease_expired=lease_expired,
        duration_seconds=max(0.0, time_fn() - start),
        output_path=output_path,
        output_excerpt=excerpt,
    )
