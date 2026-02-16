# COMMIT REVIEW TASKS

Task identifier: `MYO-40-REVIEW`  
Mode: `review`  
Tracking mode: `local`  
Review selector: `commits=1`  
Review range: `b6c1727..b4307c1`  
Merged commit in scope: `b4307c1` (MYO-40 direct merge)

## Executive Summary
Review result: `review_blocked`.

No P0/P1 issues were found. Two P2 keyboard/interaction correctness issues were identified (`P2-1`, `P2-2`). One P3 testing gap remains (`P3-1`).

## Top Urgent Items
1. `P2-1` - Fix Enter behavior in route filter so typed route is applied instead of forcing current page route.
2. `P2-2` - Prevent inbox hotkeys from firing while focus is inside `<select>` controls.

## Findings By Priority (P0-P3)
### P0
None.

### P1
None.

### P2
#### P2-1
Task: `MYO-40`  
Severity: `P2`  
Summary: Pressing Enter in Route Filter applies current page route, not the user-typed route.

Evidence:
- `frontend/src/pages/CodexPage.vue:65` binds Enter on route filter input to `applyCurrentRouteFilter`.
- `frontend/src/pages/CodexPage.vue:477` sets `routeFilter.value = currentRoutePath.value`, overwriting typed input.

Impact:
- Keyboard flow is inconsistent with user expectation for direct text filtering.
- Users can accidentally lose typed filter input.

Verification steps:
1. Open Codex inbox and type a custom route in Route Filter.
2. Press Enter.
3. Confirm field value is replaced with current page route instead of typed value.

#### P2-2
Task: `MYO-40`  
Severity: `P2`  
Summary: Global inbox hotkeys still trigger while focus is in status `<select>`, causing unintended actions.

Evidence:
- `frontend/src/pages/CodexPage.vue:517` `isTypingTarget()` excludes `select` elements.
- `frontend/src/pages/CodexPage.vue:526` hotkeys handle `Alt+R`, `Alt+ArrowRight`, `Alt+ArrowLeft` when not in typing target.

Impact:
- Keyboard navigation can unexpectedly refresh/paginate while user is interacting with filter dropdown.
- Regresses predictable focus behavior for keyboard users.

Verification steps:
1. Focus the Status Filter dropdown in Codex inbox.
2. Press `Alt+R` or `Alt+ArrowLeft/Right`.
3. Confirm refresh/pagination triggers while dropdown is focused.

### P3
#### P3-1
Task: `MYO-40`  
Severity: `P3`  
Summary: New UX/accessibility keyboard flows lack dedicated component-level test coverage.

Evidence:
- Frontend test suite currently only runs `frontend/src/lib/runs.test.ts`.
- No tests target new behaviors in:
  - `frontend/src/pages/CodexPage.vue`
  - `frontend/src/components/GlobalShortcutOverlay.vue`
  - `frontend/src/components/RunLifecycleNotifications.vue`
  - `frontend/src/pages/RunDetailsPage.vue`

Impact:
- Hotkey/focus/accessibility regressions can ship undetected.

Verification steps:
1. Run `npm run -s test` in `/Users/slobodan/Projects/Oroboros/frontend`.
2. Confirm only `src/lib/runs.test.ts` executes.

## Findings Grouped By Task
- `MYO-40`: `P2-1`, `P2-2`, `P3-1`

## Duplicate Merge Notes
1. No duplicate merge finding clusters detected within MYO-40 scope.

## Per-Task Verdicts
### MYO-40 Verdict
`AT_RISK` - UX/a11y improvements landed, but two keyboard interaction defects and a missing test safety net remain (`P2-1`, `P2-2`, `P3-1`).

## Review Checks Run
- `npm run -s test` (frontend) -> pass
- `npm run -s typecheck` (frontend) -> pass
- `npm run -s lint` (frontend) -> pass (warnings only)

## Decision
- Decision: `review_blocked`
- Handoff target: `developer`
