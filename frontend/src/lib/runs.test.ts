import { describe, expect, it } from "vitest";

import {
  extractArtifactLinks,
  extractFailureReasons,
  extractFileDiffEntries,
  hasMigrationWarning,
  makeRunTitle,
  statusChipClass,
  summarizeChecks,
} from "./runs";

describe("makeRunTitle", () => {
  it("uses untitled fallback for empty prompt", () => {
    expect(makeRunTitle("   ")).toBe("Untitled run");
  });

  it("trims and truncates long prompt", () => {
    const title = makeRunTitle("a".repeat(80));
    expect(title.length).toBe(72);
    expect(title.endsWith("...")).toBe(true);
  });
});

describe("statusChipClass", () => {
  it("maps failed states to danger chip", () => {
    expect(statusChipClass("failed")).toContain("chip-danger");
  });

  it("maps merged state to success chip", () => {
    expect(statusChipClass("merged")).toContain("chip-success");
  });
});

describe("extractArtifactLinks", () => {
  it("collects check artifacts and event payload artifact/log links", () => {
    const links = extractArtifactLinks(
      [
        {
          id: 1,
          run_id: "run-1",
          check_name: "lint",
          status: "passed",
          started_at: null,
          ended_at: null,
          artifact_uri: "https://example.com/lint.log",
        },
      ],
      [
        {
          id: 2,
          run_id: "run-1",
          event_type: "status_transition",
          status_from: "testing",
          status_to: "failed",
          payload: {
            logs: {
              stderr_uri: "https://example.com/stderr.log",
            },
            artifact_url: "/artifacts/report.json",
          },
          created_at: "2026-02-16T00:00:00Z",
        },
      ],
    );

    expect(links.map((item) => item.uri)).toContain("https://example.com/lint.log");
    expect(links.map((item) => item.uri)).toContain("https://example.com/stderr.log");
    expect(links.map((item) => item.uri)).toContain("/artifacts/report.json");
  });
});

describe("extractFailureReasons", () => {
  it("derives reasons from events and failed checks", () => {
    const reasons = extractFailureReasons(
      [
        {
          id: 1,
          run_id: "run-1",
          event_type: "status_transition",
          status_from: "testing",
          status_to: "failed",
          payload: {
            failure_reason_code: "CHECKS_FAILED",
            reason: "unit tests failed",
          },
          created_at: "2026-02-16T00:00:00Z",
        },
      ],
      [
        {
          id: 2,
          run_id: "run-1",
          check_name: "unit",
          status: "failed",
          started_at: null,
          ended_at: null,
          artifact_uri: null,
        },
      ],
    );

    expect(reasons).toContain("CHECKS_FAILED: unit tests failed");
    expect(reasons).toContain("Validation check failed: unit");
  });
});

describe("extractFileDiffEntries", () => {
  it("extracts file paths, stats, and patch snippets from nested event payloads", () => {
    const entries = extractFileDiffEntries([
      {
        id: 1,
        run_id: "run-1",
        event_type: "diff_generated",
        status_from: "editing",
        status_to: "testing",
        payload: {
          diff: {
            files: [
              {
                path: "frontend/src/pages/RunDetailsPage.vue",
                additions: 12,
                deletions: 3,
                patch: "@@ -1 +1 @@",
              },
              {
                filename: "backend/alembic/versions/20260216_0002_preview_db_resets.py",
                insertions: 50,
                removed_lines: 0,
              },
            ],
          },
        },
        created_at: "2026-02-16T00:00:00Z",
      },
    ]);

    expect(entries.length).toBe(2);
    expect(entries[0]?.path).toBe("backend/alembic/versions/20260216_0002_preview_db_resets.py");
    expect(entries[1]?.patch).toContain("@@");
  });
});

describe("hasMigrationWarning", () => {
  it("returns true when diff includes migration-related files", () => {
    const warning = hasMigrationWarning([
      {
        path: "backend/alembic/versions/20260216_0002_preview_db_resets.py",
        additions: 1,
        deletions: 0,
        patch: null,
        source: "event:diff_generated",
      },
    ]);
    expect(warning).toBe(true);
  });
});

describe("summarizeChecks", () => {
  it("counts checks by pass/fail/running/pending groups", () => {
    const summary = summarizeChecks([
      {
        id: 1,
        run_id: "run-1",
        check_name: "lint",
        status: "passed",
        started_at: null,
        ended_at: null,
        artifact_uri: null,
      },
      {
        id: 2,
        run_id: "run-1",
        check_name: "unit",
        status: "failed",
        started_at: null,
        ended_at: null,
        artifact_uri: null,
      },
      {
        id: 3,
        run_id: "run-1",
        check_name: "smoke",
        status: "running",
        started_at: null,
        ended_at: null,
        artifact_uri: null,
      },
      {
        id: 4,
        run_id: "run-1",
        check_name: "manual",
        status: "queued_for_review",
        started_at: null,
        ended_at: null,
        artifact_uri: null,
      },
    ]);

    expect(summary).toEqual({
      total: 4,
      passed: 1,
      failed: 1,
      running: 2,
      pending: 0,
    });
  });
});
