import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RegisterPage from "@/app/register/page";
import { ApiError } from "@/shared/api/client";

const pushMock = vi.fn();
const registerMock = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushMock })
}));

vi.mock("@/shared/api/auth", () => ({
  registerUser: (...args: unknown[]) => registerMock(...args)
}));

describe("RegisterPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows success message on register success", async () => {
    registerMock.mockResolvedValueOnce({ user_id: "u1", email: "owner@demo.com" });

    render(<RegisterPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@demo.com" }
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /registrarme/i }));

    await waitFor(() => {
      expect(screen.getByText(/cuenta creada/i)).toBeInTheDocument();
    });
  });

  it("shows conflict error on duplicate user", async () => {
    registerMock.mockRejectedValueOnce(new ApiError(409, "El email ya esta registrado"));

    render(<RegisterPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "owner@demo.com" }
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /registrarme/i }));

    await waitFor(() => {
      expect(screen.getByText("El email ya esta registrado")).toBeInTheDocument();
    });
  });
});
