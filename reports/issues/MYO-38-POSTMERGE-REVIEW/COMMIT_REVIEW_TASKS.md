# COMMIT REVIEW TASKS

Task identifier: `MYO-38-POSTMERGE-REVIEW`  
Mode: `review`  
Tracking mode: `linear`  
Review selector: `commits=1`  
Review range: `1b3a708..22d5932`  
Merged commit in scope: `22d5932` (MYO-38)

## Executive Summary
Review result: `review_blocked`.

One high-severity security gap was confirmed (`P1-38-01`), one medium-severity least-privilege regression risk was confirmed (`P2-38-01`), and one deployment-hardening verification item remains ambiguous (`P3-38-01`, `NEEDS_MANUAL_VERIFICATION`).

## Top Urgent Items
1. `P1-38-01` - Command allowlist can be bypassed via allowlisted shell executables (`bash`/`sh`) in default and host config.
2. `P2-38-01` - Path allowlist defaults are fail-open to temp directories when `WORKER_ALLOWED_PATHS` is missing.

## Findings By Priority (P0-P3)
### P0
None.

### P1
#### P1-38-01
Task: `MYO-38`  
Severity: `P1`  
Summary: The command allowlist can be bypassed by running arbitrary commands through allowlisted shells.

Evidence:
- `worker/worker/codex_runner.py:37` includes `bash` and `sh` in default allowlist patterns.
- `infra/systemd/env/worker.env:6` also allowlists `bash` and `sh` in host runtime config.
- Enforcement only validates the top-level executable (`worker/worker/codex_runner.py:73` and `worker/worker/codex_runner.py:81`), not shell payload commands.
- Repro (executed during review):
  - `run_codex_command(command=['bash','-lc','uname -s'], ...)` returned `exit=0` with output `Darwin`.
  - `uname` is not itself allowlisted, but executed successfully via allowlisted shell.

Impact:
- The introduced guardrail does not enforce command intent when shell wrappers are used.
- A compromised/misconfigured command template or check command can execute arbitrary host commands despite allowlist presence.

Verification steps:
1. Set runtime allowlist to defaults (`WORKER_ALLOWED_COMMANDS` unset or as in `infra/systemd/env/worker.env`).
2. Execute `run_codex_command` with `command=['bash','-lc','uname -s']` in an allowed worktree.
3. Confirm command succeeds even though `uname` is not directly allowlisted.

### P2
#### P2-38-01
Task: `MYO-38`  
Severity: `P2`  
Summary: Path allowlist defaults are fail-open to `/tmp` when explicit path policy is absent.

Evidence:
- `worker/worker/codex_runner.py:57` adds `WORKER_WORKTREE_ROOT` (or `/srv/oroboros/worktrees`) and unconditionally adds `tempfile.gettempdir()`.
- `worker/worker/codex_runner.py:66` uses these defaults whenever `WORKER_ALLOWED_PATHS` is empty.
- Repro (executed during review):
  - With `WORKER_ALLOWED_PATHS` unset, `run_codex_command(... worktree_path=<tempdir>)` returned `exit=0` and executed successfully from OS temp directory.

Impact:
- Least-privilege path control is weakened under misconfiguration.
- Worker execution can run from world-writable temp roots if explicit path policy is not present at runtime.

Verification steps:
1. Unset `WORKER_ALLOWED_PATHS` and `WORKER_WORKTREE_ROOT`.
2. Run `run_codex_command` with `worktree_path` under temp directory.
3. Confirm command executes instead of being blocked with exit code `126`.

### P3
#### P3-38-01 (NEEDS_MANUAL_VERIFICATION)
Task: `MYO-38`  
Severity: `P3`  
Summary: Service hardening/user migration is not host-validated in this review environment.

Evidence:
- Service user switched to `oroboros-worker` and hardening flags were added in `infra/systemd/ouroboros-worker.service:8` and `infra/systemd/ouroboros-worker.service:15`.
- Install script provisions user/group/env permissions in `scripts/systemd-install-runtime.sh:6` and `scripts/systemd-install-runtime.sh:33`.
- Automated checks in this review were static (`bash -n`) and unit tests only; no live `systemctl` startup test was possible here.

Impact:
- Runtime permission/startup regressions cannot be fully excluded without host-level validation.

Verification steps:
1. On a Linux target host, run `sudo ./scripts/systemd-install-runtime.sh`.
2. Run `sudo systemctl restart ouroboros-worker && sudo systemctl status ouroboros-worker --no-pager`.
3. Confirm process runs as `oroboros-worker`, starts successfully, and writes artifacts/worktrees only under intended paths.

## Findings Grouped By Task
- `MYO-38`: `P1-38-01`, `P2-38-01`, `P3-38-01`

## Duplicate Merge Notes
1. No duplicate-merge conflict pattern was observed in `1b3a708..22d5932`; scope is a single merge (`22d5932`).
2. No evidence of overlapping merged commits re-introducing reverted logic inside this review window.

## Per-Task Verdict
### MYO-38 Verdict
`FAIL` - security guardrails are present but not strict enough due shell-mediated command allowlist bypass (`P1-38-01`), with an additional fail-open path policy risk (`P2-38-01`).

## Review Checks Run
- `python3 -m compileall worker/worker backend/app` -> pass
- `python3 -m unittest discover -s worker/tests -p 'test_*.py'` -> pass (17/17)
- `python3 -m unittest discover -s backend/tests -p 'test_*.py'` -> pass (11/11)
- `bash -n scripts/systemd-install-runtime.sh` -> pass
- Ad-hoc repro for `P1-38-01` -> reproduced
- Ad-hoc repro for `P2-38-01` -> reproduced

## Decision
- Decision: `review_blocked`
- Handoff target: `developer`
