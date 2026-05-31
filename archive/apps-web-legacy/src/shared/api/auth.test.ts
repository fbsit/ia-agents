import { describe, expect, it, vi } from "vitest";

import { loginUser } from "@/shared/api/auth";

const apiRequestMock = vi.fn();

vi.mock("@/shared/api/client", () => ({
  apiRequest: (...args: unknown[]) => apiRequestMock(...args)
}));

describe("auth api wrappers", () => {
  it("calls /auth/login through shared apiRequest", async () => {
    apiRequestMock.mockResolvedValueOnce({
      user_id: "u1",
      email: "owner@demo.com",
      memberships: [],
      tokens: { access_token: "a", refresh_token: "r", token_type: "bearer" }
    });

    await loginUser({ email: "owner@demo.com", password: "password123" });

    expect(apiRequestMock).toHaveBeenCalledWith("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: "owner@demo.com", password: "password123" })
    });
  });
});
