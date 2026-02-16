import { describe, expect, it } from "vitest";

import {
  filterRunsByRoute,
  extractArtifactLinks,
  extractFailureReasons,
  extractFileDiffEntries,
  getRunRoute,
  hasMigrationWarning,
  makeRunTitle,
  normalizeRoutePath,
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

  it("does not treat unified patch text as file-path entries", () => {
    const entries = extractFileDiffEntries([
      {
        id: 2,
        run_id: "run-2",
        event_type: "diff_generated",
        status_from: "editing",
        status_to: "testing",
        payload: {
          diff: {
            files: [
              {
                path: "frontend/src/pages/RunDetailsPage.vue",
                patch: "@@ -1,3 +1,5 @@\n+ touched backend/alembic/versions/20260216_0003_preview_db_resets.py",
              },
            ],
          },
        },
        created_at: "2026-02-16T00:00:00Z",
      },
    ]);

    expect(entries).toHaveLength(1);
    expect(entries[0]?.path).toBe("frontend/src/pages/RunDetailsPage.vue");
    expect(hasMigrationWarning(entries)).toBe(false);
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

describe("route context helpers", () => {
  it("normalizes route values with trailing slash and query/hash", () => {
    expect(normalizeRoutePath("/codex/")).toBe("/codex");
    expect(normalizeRoutePath("/codex?tab=runs")).toBe("/codex");
    expect(normalizeRoutePath("codex/runs/abc#section")).toBe("/codex/runs/abc");
  });

  it("prefers context route when deriving run route", () => {
    const run = {
      id: "run-1",
      title: "Run",
      prompt: "Prompt",
      status: "queued",
      route: "/fallback",
      created_at: "2026-02-16T00:00:00Z",
      updated_at: "2026-02-16T00:00:00Z",
      context: {
        route: "/codex",
      },
    };

    expect(getRunRoute(run)).toBe("/codex");
  });

  it("filters runs related to current route and nested paths", () => {
    const runs = [
      {
        id: "run-1",
        title: "Home",
        prompt: "p1",
        status: "queued",
        route: "/",
        created_at: "2026-02-16T00:00:00Z",
        updated_at: "2026-02-16T00:00:00Z",
      },
      {
        id: "run-2",
        title: "Codex",
        prompt: "p2",
        status: "queued",
        route: "/codex",
        created_at: "2026-02-16T00:00:00Z",
        updated_at: "2026-02-16T00:00:00Z",
      },
      {
        id: "run-3",
        title: "Nested",
        prompt: "p3",
        status: "queued",
        route: "/codex/runs/abc",
        created_at: "2026-02-16T00:00:00Z",
        updated_at: "2026-02-16T00:00:00Z",
      },
      {
        id: "run-4",
        title: "Other",
        prompt: "p4",
        status: "queued",
        route: "/settings",
        created_at: "2026-02-16T00:00:00Z",
        updated_at: "2026-02-16T00:00:00Z",
      },
    ];

    const related = filterRunsByRoute(runs, "/codex");
    expect(related.map((run) => run.id)).toEqual(["run-2", "run-3"]);
  });
});
