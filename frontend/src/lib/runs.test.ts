import { describe, expect, it } from "vitest";

import { makeRunTitle, statusChipClass } from "./runs";

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
