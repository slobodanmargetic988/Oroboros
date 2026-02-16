Ignore `guides/` and its subfolders unless the user explicitly asks to read or edit files there.

Never create a new Git worktree without explicit user permission. If branch switch is blocked by local tracked changes and a safe checkpoint commit resolves it, commit with a clear message and continue; otherwise stop and ask the user.

## Review guidelines
- Read the pull request description first.
- If the pull request description includes expected outcome/task intent, review against that expected outcome before style comments.
- Validate linked issue acceptance criteria before best-practice/style-only suggestions.
- Prioritize correctness, regressions, and security over formatting.
- Treat auth, permissions, payment, and data-loss risks as high priority findings.
- Flag missing or weak tests for changed behavior.
- Require concrete evidence in findings (file/line references and why it matters).
- Keep feedback scoped to changed code unless the change introduces a broader risk.
