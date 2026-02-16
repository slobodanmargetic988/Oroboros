from __future__ import annotations

import os
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


def build_codex_command(prompt: str, worktree_path: Path) -> list[str]:
    template = os.getenv("WORKER_CODEX_COMMAND_TEMPLATE")
    if template:
        rendered = template.format(
            prompt=shlex.quote(prompt),
            worktree_path=shlex.quote(str(worktree_path)),
        )
        command = shlex.split(rendered)
        if command:
            return command

    binary = os.getenv("WORKER_CODEX_BIN", "codex")
    args = shlex.split(os.getenv("WORKER_CODEX_ARGS", ""))
    return [binary, *args, prompt]


def run_codex_command(
    *,
    command: list[str],
    worktree_path: Path,
    output_path: Path,
    timeout_seconds: int,
    poll_interval_seconds: float,
    should_cancel: Callable[[], bool] | None = None,
    on_tick: Callable[[], None] | None = None,
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

    process = popen_factory(
        command,
        cwd=str(worktree_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
