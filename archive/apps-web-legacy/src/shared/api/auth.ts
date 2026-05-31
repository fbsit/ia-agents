import { apiRequest } from "@/shared/api/client";
import type { LoginResponse, MeResponse, RegisterResponse } from "@/shared/api/types";

export function registerUser(input: { email: string; password: string }) {
  return apiRequest<RegisterResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function loginUser(input: { email: string; password: string }) {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function refreshSession(refreshToken: string) {
  return apiRequest<{ access_token: string; refresh_token: string; token_type: "bearer" }>(
    "/auth/refresh",
    {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken })
    }
  );
}

export function logoutUser(refreshToken: string) {
  return apiRequest<{ status: string }>("/auth/logout", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken })
  });
}

export function fetchMe(accessToken: string) {
  return apiRequest<MeResponse>("/me", { method: "GET" }, accessToken);
}
