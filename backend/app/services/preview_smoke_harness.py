from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.models import Run, RunArtifact, RunEvent, ValidationCheck


DEFAULT_CORE_ROUTES = ["/health", "/"]


@dataclass
class SmokeCheckResult:
    preview_url: str
    route: str
    request_url: str
    status_code: int | None
    passed: bool
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_url": self.preview_url,
            "route": self.route,
            "request_url": self.request_url,
            "status_code": self.status_code,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _normalize_preview_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("preview_url_empty")
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid_preview_url:{value}")
    return raw.rstrip("/")


def _normalize_route(value: str) -> str:
    route = value.strip()
    if not route:
        raise ValueError("route_empty")
    if not route.startswith("/"):
        route = f"/{route}"
    return route


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _request_target(
    *,
    preview_url: str,
    route: str,
    timeout_seconds: float,
    proxy_origin: str | None,
) -> SmokeCheckResult:
    preview_parsed = urlparse(preview_url)
    headers: dict[str, str] = {}

    if proxy_origin:
        proxy_base = _normalize_preview_url(proxy_origin)
        request_url = urljoin(f"{proxy_base}/", route.lstrip("/"))
        headers["Host"] = preview_parsed.netloc
    else:
        request_url = urljoin(f"{preview_url}/", route.lstrip("/"))

    request = Request(request_url, method="GET", headers=headers)
    start = time.perf_counter()
    status_code: int | None = None
    error: str | None = None

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            passed = 200 <= status_code < 400
    except HTTPError as exc:
        status_code = int(exc.code)
        passed = False
        error = f"http_error:{exc.code}"
    except URLError as exc:
        passed = False
        error = f"url_error:{exc.reason}"
    except Exception as exc:  # pragma: no cover - defensive
        passed = False
        error = str(exc)

    latency_ms = (time.perf_counter() - start) * 1000
    return SmokeCheckResult(
        preview_url=preview_url,
        route=route,
        request_url=request_url,
        status_code=status_code,
        passed=passed,
        latency_ms=latency_ms,
        error=error,
    )


def run_preview_smoke_suite(
    *,
    preview_urls: list[str],
    changed_routes: list[str] | None = None,
    core_routes: list[str] | None = None,
    timeout_seconds: float = 8.0,
    proxy_origin: str | None = None,
) -> dict[str, Any]:
    if not preview_urls:
        raise ValueError("preview_urls_required")

    started_at = _utcnow()
    normalized_preview_urls = [_normalize_preview_url(item) for item in preview_urls]
    normalized_core_routes = [_normalize_route(item) for item in (core_routes or DEFAULT_CORE_ROUTES)]
    normalized_changed_routes = [_normalize_route(item) for item in (changed_routes or [])]

    target_routes = _dedupe(normalized_core_routes + normalized_changed_routes)
    checks: list[SmokeCheckResult] = []
    target_results: list[dict[str, Any]] = []

    for preview_url in normalized_preview_urls:
        parsed = urlparse(preview_url)
        target_checks = [
            _request_target(
                preview_url=preview_url,
                route=route,
                timeout_seconds=timeout_seconds,
                proxy_origin=proxy_origin,
            )
            for route in target_routes
        ]
        checks.extend(target_checks)
        target_results.append(
            {
                "preview_url": preview_url,
                "host": parsed.netloc,
                "passed": all(item.passed for item in target_checks),
                "checks": [item.to_dict() for item in target_checks],
            }
        )

    total_checks = len(checks)
    passed_checks = sum(1 for item in checks if item.passed)
    failed_checks = total_checks - passed_checks
    ended_at = _utcnow()

    return {
        "harness": "preview_smoke_e2e",
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "duration_ms": round((ended_at - started_at).total_seconds() * 1000, 2),
        "mode": {
            "host_deployed": True,
            "proxy_origin": proxy_origin,
            "container_assumptions": False,
        },
        "routes": {
            "core_routes": normalized_core_routes,
            "changed_routes": normalized_changed_routes,
        },
        "targets": target_results,
        "summary": {
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "overall_status": "passed" if failed_checks == 0 else "failed",
        },
    }


def write_smoke_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json.dumps(report, indent=2, sort_keys=True)}\n", encoding="utf-8")
    return output_path


def persist_smoke_report_for_run(
    *,
    db: Session,
    run_id: str,
    report: dict[str, Any],
    artifact_uri: str,
) -> None:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError("run_not_found")

    summary = report.get("summary", {})
    overall_status = str(summary.get("overall_status", "failed"))
    started_at = datetime.fromisoformat(str(report["started_at"]))
    ended_at = datetime.fromisoformat(str(report["ended_at"]))

    db.add(
        ValidationCheck(
            run_id=run_id,
            check_name="preview_smoke_e2e",
            status=overall_status,
            started_at=started_at,
            ended_at=ended_at,
            artifact_uri=artifact_uri,
        )
    )
    db.add(
        RunArtifact(
            run_id=run_id,
            artifact_type="preview_smoke_e2e_report",
            artifact_uri=artifact_uri,
            metadata_json={
                "overall_status": overall_status,
                "failed_checks": int(summary.get("failed_checks", 0)),
                "total_checks": int(summary.get("total_checks", 0)),
            },
        )
    )
    db.add(
        RunEvent(
            run_id=run_id,
            event_type="preview_smoke_e2e_completed",
            status_from=run.status,
            status_to=run.status,
            payload={
                "overall_status": overall_status,
                "artifact_uri": artifact_uri,
                "failed_checks": int(summary.get("failed_checks", 0)),
                "total_checks": int(summary.get("total_checks", 0)),
            },
        )
    )
    db.commit()
