# SPRINT_AGENT_ACTIVATIONS
Generated: 2026-02-16 11:32 UTC

## Ready Now

### Prompt 1: Reviewer for MYO-14
```text
Agent: recent-commit-review-agent
Goal: Final review of MYO-14 for closeout decision.
Review mode: auto
Mode: review
Review window: commits=8
Primary deliverable: /Users/slobodan/Projects/Oroboros/reports/COMMIT_REVIEW_TASKS.md
Constraints:
- Read-only review. Do not modify source code.
- Validate evidence from branch `codex/worker1-myo-14` commit `455ebad`.
- Confirm no container-only assumptions were introduced in scaffolding/docs.
Output:
- Findings sorted P0-P3 with evidence.
- Explicit final line: `MYO-14 decision: APPROVE_FOR_DONE` or `MYO-14 decision: CHANGES_REQUIRED`.
```

## Queue Prepared (execute after MYO-14 = Done)

### Prompt 2: Tester for MYO-15
```text
Agent: backend-tester
Goal: Validate MYO-15 implementation and enforce host-only runtime policy.
Inputs: task_identifier: MYO-15
Inputs: repo_root: /Users/slobodan/Projects/Oroboros
Inputs: default_branch: main
Inputs: test_target: process topology, reverse proxy routes, health endpoints, deploy/runtime scripts
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
- Start by setting MYO-15 to `Agent testing`.
- Enforce non-container policy: fail if Docker/Compose/K8s/container runtime is required or introduced.
- Validate host-level process manager/supervisor + reverse proxy + service health checks.
- If pass, set `Agent test DONE` and handoff to reviewer.
- If fail, return to `Agent working` with defect evidence.
Output:
- /Users/slobodan/Projects/Oroboros/reports/BACKEND_TEST_REPORT.md
- Pass/fail evidence
- Reviewer handoff recommendation
```

### Prompt 3: Reviewer for MYO-15
```text
Agent: recent-commit-review-agent
Goal: Review tested MYO-15 output for human-review readiness.
Review mode: auto
Mode: review
Review window: commits=8
Primary deliverable: /Users/slobodan/Projects/Oroboros/reports/COMMIT_REVIEW_TASKS.md
Constraints:
- Start only after MYO-15 is `Agent test DONE`.
- Read-only review.
- Prioritize policy conformance: host-only deploy, no containers.
Output:
- Prioritized findings with verification steps.
- Explicit final line: `MYO-15 decision: APPROVE_FOR_HUMAN_REVIEW` or `MYO-15 decision: CHANGES_REQUIRED`.
```

### Prompt 4: Worker (rework only, if tester/reviewer finds Docker dependency)
```text
Agent: backend-developer
Goal: Remove any Docker/container dependency from MYO-15 and deliver host-only runtime.
Inputs: task_identifier: MYO-15
Inputs: repo_root: /Users/slobodan/Projects/Oroboros
Inputs: default_branch: main
Inputs: acceptance_criteria: host-level process supervisor, reverse proxy routes, service health checks; no containers.
Inputs: stack_file_path: /Users/slobodan/Projects/Oroboros/docs/codex-builder-core-spec.md
Inputs: task_list_path: /Users/slobodan/Projects/Oroboros/reports/SPRINT_EXECUTION_LOG.md
Inputs: linear_issue_id: MYO-15
Inputs: linear_workflow_path: /Users/slobodan/Projects/Agents/agents/_shared/LINEAR_WORKFLOW.md
Inputs: linear_ready_for_test_status: Agent work DONE
Inputs: branch_name: codex/myo-15-runtime-topology
Inputs: commit_mode: commit
Constraints:
- Use this only for defect-driven rework.
- Replace container paths with host-native scripts/processes.
- On completion set `Agent work DONE` and handoff back to tester.
Output:
- Rework changes
- Check results
- Tester handoff comment
```
