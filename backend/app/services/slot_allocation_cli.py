from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.slot_allocation import SlotUnavailableError, allocate_slot_for_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Allocate preview slot and run deterministic DB reset/seed flow")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed-version", default="v1")
    parser.add_argument("--strategy", choices=["seed", "snapshot"], default="seed")
    parser.add_argument("--snapshot-version", default=None)
    parser.add_argument("--lease-ttl-minutes", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = allocate_slot_for_run(
            db=db,
            run_id=args.run_id,
            seed_version=args.seed_version,
            strategy=args.strategy,
            snapshot_version=args.snapshot_version,
            lease_ttl_minutes=args.lease_ttl_minutes,
            dry_run=args.dry_run,
        )
    except SlotUnavailableError as exc:
        print(json.dumps({"status": "waiting", "reason": str(exc)}))
        return 2
    finally:
        db.close()

    print(
        json.dumps(
            {
                "status": "allocated",
                "run_id": result.run_id,
                "slot_id": result.slot_id,
                "db_name": result.db_name,
                "seed_version": result.seed_version,
                "snapshot_version": result.snapshot_version,
                "strategy": result.strategy,
                "dry_run": result.dry_run,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
