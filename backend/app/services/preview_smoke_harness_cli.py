from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.preview_smoke_harness import (
    DEFAULT_CORE_ROUTES,
    persist_smoke_report_for_run,
    run_preview_smoke_suite,
    write_smoke_report,
)


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/tmp/preview-smoke-e2e-{timestamp}.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run host-preview smoke/E2E harness for preview URLs")
    parser.add_argument("--preview-url", action="append", required=True, help="Preview URL target (repeatable)")
    parser.add_argument(
        "--changed-route",
        action="append",
        default=[],
        help="Changed route to include in smoke pass (repeatable)",
    )
    parser.add_argument(
        "--core-route",
        action="append",
        default=[],
        help=f"Core route to include (repeatable, default: {', '.join(DEFAULT_CORE_ROUTES)})",
    )
    parser.add_argument("--proxy-origin", default=None, help="Optional proxy origin (e.g. http://127.0.0.1:8088)")
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--output", default=str(_default_output_path()))
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--persist-validation",
        action="store_true",
        help="Persist ValidationCheck + RunArtifact + RunEvent for --run-id",
    )
    args = parser.parse_args()

    report = run_preview_smoke_suite(
        preview_urls=args.preview_url,
        changed_routes=args.changed_route,
        core_routes=args.core_route or DEFAULT_CORE_ROUTES,
        timeout_seconds=args.timeout_seconds,
        proxy_origin=args.proxy_origin,
    )

    output_path = write_smoke_report(report, Path(args.output).expanduser().resolve())
    artifact_uri = output_path.as_uri()

    if args.persist_validation:
        if not args.run_id:
            raise SystemExit("--persist-validation requires --run-id")
        db = SessionLocal()
        try:
            persist_smoke_report_for_run(
                db=db,
                run_id=args.run_id,
                report=report,
                artifact_uri=artifact_uri,
            )
        finally:
            db.close()

    payload = {
        "status": report["summary"]["overall_status"],
        "artifact_uri": artifact_uri,
        "failed_checks": report["summary"]["failed_checks"],
        "total_checks": report["summary"]["total_checks"],
    }
    print(json.dumps(payload))

    return 0 if report["summary"]["overall_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
