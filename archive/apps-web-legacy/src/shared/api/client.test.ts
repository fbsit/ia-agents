import { describe, expect, it } from "vitest";

import { normalizeApiError } from "@/shared/api/client";

describe("normalizeApiError", () => {
  it("returns detail when backend payload includes detail", () => {
    const error = normalizeApiError(401, { detail: "Credenciales invalidas" });
    expect(error.status).toBe(401);
    expect(error.detail).toBe("Credenciales invalidas");
  });

  it("returns fallback when payload has no known fields", () => {
    const error = normalizeApiError(500, { other: "x" }, "Backend roto");
    expect(error.status).toBe(500);
    expect(error.detail).toBe("Backend roto");
  });
});
