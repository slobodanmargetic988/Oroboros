from __future__ import annotations

import argparse
from datetime import datetime
import json

from app.db.session import SessionLocal
from app.services.release_registry import get_release_by_id, list_releases, upsert_release


def _to_payload(item) -> dict[str, str | int | None]:
    return {
        "id": item.id,
        "release_id": item.release_id,
        "commit_sha": item.commit_sha,
        "migration_marker": item.migration_marker,
        "status": item.status,
        "deployed_at": item.deployed_at.isoformat() if item.deployed_at else None,
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage release registry records in control-plane DB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upsert_parser = subparsers.add_parser("upsert")
    upsert_parser.add_argument("--release-id", required=True)
    upsert_parser.add_argument("--commit-sha", required=True)
    upsert_parser.add_argument("--status", required=True)
    upsert_parser.add_argument("--migration-marker", default=None)
    upsert_parser.add_argument("--deployed-at", default=None)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--release-id", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--status", default=None)

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.command == "upsert":
            release = upsert_release(
                db=db,
                release_id=args.release_id,
                commit_sha=args.commit_sha,
                status=args.status,
                migration_marker=args.migration_marker,
                deployed_at=_parse_datetime(args.deployed_at),
            )
            print(json.dumps(_to_payload(release)))
            return 0

        if args.command == "get":
            release = get_release_by_id(db=db, release_id=args.release_id)
            if release is None:
                print(json.dumps({"error": "release_not_found", "release_id": args.release_id}))
                return 2
            print(json.dumps(_to_payload(release)))
            return 0

        if args.command == "list":
            records = list_releases(db=db, limit=args.limit, status=args.status)
            print(json.dumps([_to_payload(item) for item in records]))
            return 0

        print(json.dumps({"error": "unsupported_command"}))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
