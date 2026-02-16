from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.db.session import SessionLocal
from app.services.integration_happy_path import (
    default_output_path,
    parse_slot_host_map,
    persist_happy_path_report_for_run,
    resolve_preview_host,
    utcnow_iso,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TERMINAL_FAILURE_STATES = {"failed", "canceled", "expired"}


def _normalize_route(value: str) -> str:
    route = value.strip()
    if not route:
        return "/codex"
    if not route.startswith("/"):
        return f"/{route}"
    return route


def _resolve_output_path(raw_output: str) -> Path:
    output = Path(raw_output).expanduser()
    if output.is_absolute():
        return output.resolve()
    caller_cwd = os.getenv("INTEGRATION_HAPPY_PATH_CALLER_CWD")
    base = Path(caller_cwd).expanduser() if caller_cwd else Path.cwd()
    return (base / output).resolve()


def _api_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 15.0,
) -> Any:
    body_bytes = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, method=method.upper(), data=body_bytes, headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_error:{exc.code}:{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"url_error:{exc.reason}") from exc


def _run_command(command: list[str], *, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _poll_run_until(
    *,
    api_base_url: str,
    run_id: str,
    target_states: set[str],
    timeout_seconds: int,
    poll_interval_seconds: float,
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = _http_json(method="GET", url=_api_url(api_base_url, f"/api/runs/{run_id}"))
        status = str(run.get("status", ""))
        snapshot = {
            "observed_at": utcnow_iso(),
            "status": status,
            "slot_id": run.get("slot_id"),
            "commit_sha": run.get("commit_sha"),
            "branch_name": run.get("branch_name"),
        }
        if not timeline or timeline[-1].get("status") != status:
            timeline.append(snapshot)

        if status in target_states:
            return run
        if status in TERMINAL_FAILURE_STATES:
            raise RuntimeError(f"run_reached_failure_state:{status}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timeout_waiting_for_states:{sorted(target_states)}")
        time.sleep(poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate full host-only happy path from prompt to merged deploy")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--route", default="/codex")
    parser.add_argument("--changed-route", action="append", default=[])
    parser.add_argument("--prompt", default="MYO-42 integration happy path validation")
    parser.add_argument("--title", default="MYO-42 integration happy path validation")
    parser.add_argument("--reviewer-id", default="integration-harness")
    parser.add_argument(
        "--slot-host-map",
        default="preview-1=preview1.example.com,preview-2=preview2.example.com,preview-3=preview3.example.com",
    )
    parser.add_argument("--proxy-origin", default="http://127.0.0.1:8088")
    parser.add_argument("--wait-timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--health-check-command", default="./scripts/runtime-health-check.sh")
    parser.add_argument("--output", default=str(default_output_path()))
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--no-persist-evidence", action="store_true")
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    timeline: list[dict[str, Any]] = []
    run_id: str | None = None
    report: dict[str, Any] = {
        "harness": "integration_happy_path",
        "started_at": started_at.isoformat(),
        "mode": {
            "host_deployed": True,
            "container_assumptions": False,
        },
        "steps": {},
        "timeline": timeline,
        "summary": {"overall_status": "failed"},
    }

    try:
        route = _normalize_route(args.route)
        changed_routes = [_normalize_route(item) for item in args.changed_route] or [route]
        slot_host_map = parse_slot_host_map(args.slot_host_map)

        report["steps"]["api_health_precheck"] = _http_json(
            method="GET",
            url=_api_url(args.api_base_url, "/health"),
        )

        created = _http_json(
            method="POST",
            url=_api_url(args.api_base_url, "/api/runs"),
            payload={
                "title": args.title,
                "prompt": args.prompt,
                "route": route,
                "note": "MYO-42 integration validation",
                "metadata": {
                    "scenario": "integration_happy_path",
                    "issue": "MYO-42",
                },
            },
        )
        run_id = str(created["id"])
        report["run_id"] = run_id
        report["steps"]["run_created"] = created

        run_before_approval = _poll_run_until(
            api_base_url=args.api_base_url,
            run_id=run_id,
            target_states={"preview_ready", "needs_approval", "approved", "merging", "deploying", "merged"},
            timeout_seconds=args.wait_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            timeline=timeline,
        )
        report["steps"]["pre_approval_state"] = run_before_approval

        slot_id = run_before_approval.get("slot_id")
        preview_host = resolve_preview_host(slot_id if isinstance(slot_id, str) else None, slot_host_map)
        smoke_command = ["./scripts/preview-smoke-e2e.sh", "--preview-url", preview_host]
        if args.proxy_origin:
            smoke_command.extend(["--proxy-origin", args.proxy_origin])
        for changed_route in changed_routes:
            smoke_command.extend(["--changed-route", changed_route])
        smoke_command.extend(["--run-id", run_id, "--persist-validation"])

        smoke_result = _run_command(smoke_command, cwd=REPO_ROOT)
        report["steps"]["preview_smoke"] = smoke_result
        if int(smoke_result.get("exit_code", 1)) != 0:
            raise RuntimeError("preview_smoke_failed")

        if str(run_before_approval.get("status")) != "merged":
            approval_response = _http_json(
                method="POST",
                url=_api_url(args.api_base_url, f"/api/runs/{run_id}/approve"),
                payload={
                    "reviewer_id": args.reviewer_id,
                    "reason": "MYO-42 integration happy path",
                },
            )
            report["steps"]["approve"] = approval_response

        final_run = _poll_run_until(
            api_base_url=args.api_base_url,
            run_id=run_id,
            target_states={"merged"},
            timeout_seconds=args.wait_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            timeline=timeline,
        )
        report["steps"]["run_final"] = final_run

        if args.skip_health_check:
            report["post_deploy_health"] = {
                "status": "skipped",
                "command": args.health_check_command,
            }
        else:
            health_result = _run_command(
                ["bash", "-lc", args.health_check_command],
                cwd=REPO_ROOT,
            )
            report["post_deploy_health"] = {
                "status": "passed" if health_result["exit_code"] == 0 else "failed",
                **health_result,
            }
            if health_result["exit_code"] != 0:
                raise RuntimeError("post_deploy_health_failed")

        events = _http_json(
            method="GET",
            url=_api_url(args.api_base_url, f"/api/runs/{run_id}/events?order=asc&limit=500"),
        )
        report["events_count"] = len(events) if isinstance(events, list) else 0
        report["events"] = events
        report["summary"] = {
            "overall_status": "passed",
            "run_status": str(final_run.get("status")),
            "events_count": report["events_count"],
            "target_route": route,
            "changed_routes": changed_routes,
            "preview_host": preview_host,
        }
    except Exception as exc:  # pragma: no cover - exercised in host flow
        report["summary"] = {
            "overall_status": "failed",
            "error": str(exc),
            "run_id": run_id,
        }
        if run_id:
            try:
                run_snapshot = _http_json(
                    method="GET",
                    url=_api_url(args.api_base_url, f"/api/runs/{run_id}"),
                )
                report["steps"]["run_snapshot_on_error"] = run_snapshot
            except Exception:
                pass

    ended_at = datetime.now(timezone.utc)
    report["ended_at"] = ended_at.isoformat()
    report["duration_seconds"] = round((ended_at - started_at).total_seconds(), 3)

    output_path = _resolve_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json.dumps(report, indent=2, sort_keys=True)}\n", encoding="utf-8")

    run_id_for_persist = report.get("run_id")
    if run_id_for_persist and not args.no_persist_evidence:
        db = SessionLocal()
        try:
            persist_happy_path_report_for_run(
                db=db,
                run_id=str(run_id_for_persist),
                report=report,
                artifact_uri=output_path.as_uri(),
            )
        finally:
            db.close()

    print(
        json.dumps(
            {
                "status": report["summary"].get("overall_status", "failed"),
                "run_id": report.get("run_id"),
                "artifact_uri": output_path.as_uri(),
                "error": report["summary"].get("error"),
            }
        )
    )

    return 0 if report["summary"].get("overall_status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
