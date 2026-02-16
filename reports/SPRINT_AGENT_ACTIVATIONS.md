# SPRINT_AGENT_ACTIVATIONS
Generated: 2026-02-16 11:14 UTC

## Ready Now (reviewer only)

### Prompt 1: Reviewer for MYO-14
```text
Agent: recent-commit-review-agent
Goal: Final review of MYO-14 implementation for closeout decision.
Review mode: auto
Mode: review
Review window: commits=8
Primary deliverable: /Users/slobodan/Projects/Oroboros/reports/COMMIT_REVIEW_TASKS.md
Constraints:
- Read-only review. Do not modify source code.
- Review target branch/commit evidence from MYO-14 handoff (`codex/worker1-myo-14`, `455ebad`).
- Validate acceptance criteria coverage and identify any release-blocking defects.
Output:
- Findings sorted P0-P3 with evidence.
- Explicit final line: `MYO-14 decision: APPROVE_FOR_DONE` or `MYO-14 decision: CHANGES_REQUIRED`.
```

## Queue Prepared (execute only after MYO-14 = Done)

### Prompt 2: Worker (developer) for MYO-15
```text
Agent: backend-developer
Goal: Implement MYO-15 "[A0-02] Stand up base Linux runtime with process topology".
Inputs: task_identifier: MYO-15
Inputs: repo_root: /Users/slobodan/Projects/Oroboros
Inputs: default_branch: main
Inputs: acceptance_criteria: Service topology documented; base process manager setup committed; reverse proxy routes for production and 3 preview URLs prepared; health endpoints reachable for all core services.
Inputs: stack_file_path: /Users/slobodan/Projects/Oroboros/docs/codex-builder-core-spec.md
Inputs: task_list_path: /Users/slobodan/Projects/Oroboros/reports/SPRINT_EXECUTION_LOG.md
Inputs: linear_issue_id: MYO-15
Inputs: linear_workflow_path: /Users/slobodan/Projects/Agents/agents/_shared/LINEAR_WORKFLOW.md
Inputs: linear_ready_for_test_status: Agent work DONE
Inputs: branch_name: codex/myo-15-runtime-topology
Inputs: commit_mode: commit
Constraints:
- Start by setting MYO-15 to `Agent working` to claim ownership.
- Keep dependency order (prep lane).
- When dev is complete, set MYO-15 to `Agent work DONE` and post tester handoff with branch + commit.
Output:
- Code/config changes for MYO-15
- Check results
- Tester handoff comment payload
```

### Prompt 3: Tester for MYO-15
```text
Agent: backend-tester
Goal: Validate MYO-15 implementation and determine review readiness.
Inputs: task_identifier: MYO-15
Inputs: repo_root: /Users/slobodan/Projects/Oroboros
Inputs: default_branch: main
Inputs: test_target: deployment/process topology/reverse proxy/health endpoints
Inputs: stack_file_path: /Users/slobodan/Projects/Oroboros/docs/codex-builder-core-spec.md
Inputs: harness_mode: developer_handoff
Inputs: extra_test_focus: integration
Inputs: task_list_path: /Users/slobodan/Projects/Oroboros/reports/SPRINT_EXECUTION_LOG.md
Inputs: linear_issue_id: MYO-15
Inputs: linear_workflow_path: /Users/slobodan/Projects/Agents/agents/_shared/LINEAR_WORKFLOW.md
Inputs: linear_ready_statuses: Agent work DONE, Agent testing
Inputs: post_not_ready_comment: true
Inputs: branch_name: codex/myo-15-runtime-topology
Inputs: commit_mode: commit
Constraints:
- Set status to `Agent testing` when test phase starts.
- If pass, set `Agent test DONE` and hand off to reviewer.
- If fail, return issue to `Agent working` with defect evidence.
Output:
- /Users/slobodan/Projects/Oroboros/reports/BACKEND_TEST_REPORT.md
- Pass/fail evidence
- Reviewer handoff recommendation
```

### Prompt 4: Reviewer for MYO-15
```text
Agent: recent-commit-review-agent
Goal: Review tested MYO-15 output and provide closeout recommendation.
Review mode: auto
Mode: review
Review window: commits=8
Primary deliverable: /Users/slobodan/Projects/Oroboros/reports/COMMIT_REVIEW_TASKS.md
Constraints:
- Start only after MYO-15 is in `Agent test DONE`.
- Read-only review.
- Focus on deployment safety, topology correctness, and rollback risk.
Output:
- Prioritized findings with verification steps.
- Explicit final line: `MYO-15 decision: APPROVE_FOR_HUMAN_REVIEW` or `MYO-15 decision: CHANGES_REQUIRED`.
```
