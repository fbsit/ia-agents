import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";
import { ApiError } from "@/shared/api/client";

const pushMock = vi.fn();
const loginMock = vi.fn();
const setFromLoginMock = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushMock })
}));

vi.mock("@/shared/api/auth", () => ({
  loginUser: (...args: unknown[]) => loginMock(...args)
}));

vi.mock("@/shared/session/provider", () => ({
  useSession: () => ({
    setFromLogin: setFromLoginMock
  })
}));

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to dashboard on successful login with memberships", async () => {
    loginMock.mockResolvedValueOnce({
      user_id: "u1",
      email: "a@b.com",
      memberships: [{ org_id: "o1", role: "owner" }],
      tokens: { access_token: "a", refresh_token: "r", token_type: "bearer" }
    });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@demo.com" }
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /ingresar/i }));

    await waitFor(() => {
      expect(setFromLoginMock).toHaveBeenCalled();
      expect(pushMock).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows backend error on invalid login", async () => {
    loginMock.mockRejectedValueOnce(new ApiError(401, "Credenciales invalidas"));

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@demo.com" }
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrong" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /ingresar/i }));

    await waitFor(() => {
      expect(screen.getByText("Credenciales invalidas")).toBeInTheDocument();
    });
  });
});
