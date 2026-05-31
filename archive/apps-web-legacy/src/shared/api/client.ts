import {
  emitSessionCleared,
  emitSessionRefreshed,
  readPersistedSession,
  writePersistedSession
} from "@/shared/session/storage";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function normalizeApiError(
  status: number,
  payload: unknown,
  fallback = "Error inesperado del backend"
): ApiError {
  if (typeof payload === "string" && payload.trim()) {
    return new ApiError(status, payload);
  }

  if (payload && typeof payload === "object") {
    const item = payload as Record<string, unknown>;
    if (typeof item.detail === "string" && item.detail.trim()) {
      return new ApiError(status, item.detail);
    }
    if (typeof item.message === "string" && item.message.trim()) {
      return new ApiError(status, item.message);
    }
  }

  return new ApiError(status, fallback);
}

async function parsePayload(response: Response): Promise<unknown> {
  const raw = await response.text();
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function buildHeaders(init: RequestInit, accessToken?: string): Headers {
  const headers = new Headers(init.headers ?? {});
  const isFormDataBody = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (!isFormDataBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return headers;
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === "undefined") {
    return null;
  }

  if (refreshInFlight) {
    return refreshInFlight;
  }

  const current = readPersistedSession();
  if (!current?.refreshToken) {
    return null;
  }

  refreshInFlight = (async () => {
    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refreshToken })
    });

    const payload = await parsePayload(response);
    if (!response.ok || !payload || typeof payload !== "object") {
      writePersistedSession(null);
      emitSessionCleared();
      return null;
    }

    const item = payload as Record<string, unknown>;
    const accessToken = typeof item.access_token === "string" ? item.access_token : "";
    const refreshToken = typeof item.refresh_token === "string" ? item.refresh_token : "";

    if (!accessToken || !refreshToken) {
      writePersistedSession(null);
      emitSessionCleared();
      return null;
    }

    writePersistedSession({
      ...current,
      accessToken,
      refreshToken
    });
    emitSessionRefreshed();
    return accessToken;
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  accessToken?: string
): Promise<T> {
  const firstResponse = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildHeaders(init, accessToken)
  });

  const firstPayload = await parsePayload(firstResponse);
  if (firstResponse.ok) {
    return firstPayload as T;
  }

  if (firstResponse.status === 401 && accessToken && path !== "/auth/refresh") {
    const refreshedAccessToken = await refreshAccessToken();
    if (refreshedAccessToken) {
      const retryResponse = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: buildHeaders(init, refreshedAccessToken)
      });
      const retryPayload = await parsePayload(retryResponse);
      if (retryResponse.ok) {
        return retryPayload as T;
      }

      if (retryResponse.status === 401) {
        throw new ApiError(401, "Token invalido o expirado. Inicia sesion nuevamente.");
      }
      throw normalizeApiError(retryResponse.status, retryPayload);
    }

    throw new ApiError(401, "Token invalido o expirado. Inicia sesion nuevamente.");
  }

  throw normalizeApiError(firstResponse.status, firstPayload);
}
