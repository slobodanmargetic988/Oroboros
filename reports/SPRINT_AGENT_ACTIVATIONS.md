# SPRINT_AGENT_ACTIVATIONS
Generated: 2026-02-16 10:22 UTC

## Ready Now Activations

### Activation 1: Developer (Run now)
```txt
Agent: fullstack-developer
Issue: MYO-14
Project: Ouroboros (team Myownmint)
Objective: Implement MYO-14 "[A0-01] Bootstrap monorepo skeleton and runtime boundaries".

Requirements:
- Follow issue acceptance criteria exactly.
- Keep dependency order intact (prep lane only; do not start MYO-15 yet).
- Do not touch unrelated issues.
- Use feature branch from the issue branch naming convention.

Status workflow to apply in Linear:
1) Set MYO-14 to In Progress when work starts.
2) Leave clear implementation notes + evidence links in issue comment.
3) When development is done, hand off to tester (do not mark Done directly).

Handoff target after dev: backend-tester
Handoff note to include: "MYO-14 ready for test pass under prep lane constraints."

Output back to orchestrator:
- What was completed vs acceptance criteria
- Risks/gaps
- Exact tester handoff note
```

### Activation 2: Tester (Run only after developer handoff)
```txt
Agent: backend-tester
Issue: MYO-14
Project: Ouroboros (team Myownmint)
Trigger: Run only after developer confirms implementation complete.

Objective:
- Validate MYO-14 acceptance criteria with reproducible checks.
- Record pass/fail evidence and defects in Linear comments.

Status workflow to apply in Linear:
1) Keep issue in In Progress during testing.
2) If defects exist, comment blockers and return to developer.
3) If tests pass, set issue to In Review and add "review-ready" comment.
4) Do not set Done; reviewer/maintainer closes after review.

Output back to orchestrator:
- Test evidence summary
- Defects (if any)
- Recommendation: review-ready or back-to-dev
```

## Queue-Prepared (Not Ready Yet)
- Prep next: MYO-15 (unblocks only after MYO-14 review-ready/done)
- Parallel lane starts after prep complete: MYO-18, MYO-19, MYO-20
