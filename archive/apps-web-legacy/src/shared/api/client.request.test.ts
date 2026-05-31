import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_CLEARED_EVENT,
  SESSION_STORAGE_KEY
} from "@/shared/session/storage";

describe("apiRequest base URL wiring", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("uses NEXT_PUBLIC_API_BASE_URL for outgoing requests", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:9999");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true })
    });
    vi.stubGlobal("fetch", fetchMock);

    const { apiRequest } = await import("@/shared/api/client");
    await apiRequest<{ ok: boolean }>("/health", { method: "GET" });

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:9999/health", {
      method: "GET",
      headers: expect.any(Headers)
    });
  });

  it("refreshes token on 401 and retries request", async () => {
    window.sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        userId: "u1",
        email: "owner@demo.com",
        accessToken: "expired-token",
        refreshToken: "valid-refresh",
        memberships: []
      })
    );

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "Token invalido o expirado" })
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify({
            access_token: "fresh-access",
            refresh_token: "fresh-refresh",
            token_type: "bearer"
          })
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: true })
      });
    vi.stubGlobal("fetch", fetchMock);

    const { apiRequest } = await import("@/shared/api/client");
    const response = await apiRequest<{ ok: boolean }>("/protected", { method: "GET" }, "expired-token");

    expect(response.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? "{}");
    expect(parsed.accessToken).toBe("fresh-access");
    expect(parsed.refreshToken).toBe("fresh-refresh");
  });

  it("clears session and emits event when refresh fails", async () => {
    window.sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({
        userId: "u1",
        email: "owner@demo.com",
        accessToken: "expired-token",
        refreshToken: "bad-refresh",
        memberships: []
      })
    );

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "Token invalido o expirado" })
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "Refresh token invalido" })
      });
    vi.stubGlobal("fetch", fetchMock);

    const sessionClearedSpy = vi.fn();
    window.addEventListener(SESSION_CLEARED_EVENT, sessionClearedSpy);

    const { apiRequest, ApiError } = await import("@/shared/api/client");
    await expect(apiRequest("/protected", { method: "GET" }, "expired-token")).rejects.toEqual(
      expect.objectContaining({
        name: ApiError.name,
        status: 401,
        detail: "Token invalido o expirado. Inicia sesion nuevamente."
      })
    );

    expect(window.sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionClearedSpy).toHaveBeenCalled();
    window.removeEventListener(SESSION_CLEARED_EVENT, sessionClearedSpy);
  });
});
