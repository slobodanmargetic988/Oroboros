import { describe, expect, it } from "vitest";

import { toActionableRequestError } from "./httpErrors";

describe("toActionableRequestError", () => {
  it("maps network/fetch failures to actionable guidance", () => {
    const message = toActionableRequestError(new TypeError("Failed to fetch"));
    expect(message).toContain("Unable to reach backend API");
    expect(message).toContain("CORS/preflight");
  });

  it("preserves explicit backend/request messages", () => {
    const message = toActionableRequestError(new Error("Request failed (422): invalid_reviewer_id"));
    expect(message).toBe("Request failed (422): invalid_reviewer_id");
  });
});

