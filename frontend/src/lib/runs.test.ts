import { describe, expect, it } from "vitest";

import { extractArtifactLinks, extractFailureReasons, makeRunTitle, statusChipClass } from "./runs";

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
