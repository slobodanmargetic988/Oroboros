# SPRINT_PLAN
Generated: 2026-02-16 11:32 UTC
Agent: sprint-orchestrator-agent

## Scope
- Project: Ouroboros
- Team: Myownmint
- Tracked issues: MYO-14..MYO-44 (existing issues only)
- Mode: Planning/orchestration only
- Merge mode: sequential

## Platform Constraint (Hard)
- Deploy to a clean Linux server instance using host services/processes only.
- Do not use Docker, Docker Compose, Kubernetes, or any container runtime.
- Any task proposal that introduces containers is out of policy and must be rejected/reworked.

## Workflow Lock (to avoid duplicate pickup)
- Todo -> Agent working -> Agent work DONE -> Agent testing -> Agent test DONE -> Agent review -> Agent review DONE -> Human Review -> Done
- `Agent working`, `Agent testing`, `Agent review` are lock states (exclusive owner).

## Dependency Map
- Prep: MYO-14 -> MYO-15 -> MYO-16 -> MYO-17
- A1: MYO-18 -> MYO-21 -> MYO-24 -> MYO-27 -> MYO-30 -> MYO-33 -> MYO-36 -> MYO-39
- A2: MYO-19 -> MYO-22 -> MYO-25 -> MYO-29 -> MYO-31 -> MYO-34 -> MYO-37 -> MYO-40
- A3: MYO-20 -> MYO-23 -> MYO-26 -> MYO-28 -> MYO-32 -> MYO-35 -> MYO-38 -> MYO-41
- Integration: MYO-42 -> MYO-43 -> MYO-44

## Current Snapshot
- MYO-14: Human Review
- MYO-15: Agent work DONE
- Remaining tracked issues: Todo

## Ready Now
1. MYO-14 (Human Review): finalize review decision to Done or back to rework.
2. MYO-15 (Agent work DONE): tester phase is prepared, but start only once MYO-14 is Done to preserve strict prep ordering.

## Linear Updates Applied (this cycle)
- Updated descriptions for MYO-15, MYO-20, MYO-23, MYO-26, MYO-28, MYO-32, MYO-35, MYO-38, MYO-41, MYO-42, MYO-43, MYO-44
- Added explicit non-container deployment constraints to each above issue
