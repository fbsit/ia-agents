import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React, { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OnboardingPage from "@/app/onboarding/page";
import { ApiError } from "@/shared/api/client";

const pushMock = vi.fn();
const createOrgMock = vi.fn();
const bootstrapProfileMock = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushMock })
}));

vi.mock("@/shared/api/tenancy", () => ({
  createOrganization: (...args: unknown[]) => createOrgMock(...args)
}));

vi.mock("@/shared/session/provider", () => ({
  useSession: () => ({
    session: {
      userId: "u1",
      email: "owner@demo.com",
      accessToken: "access-token",
      refreshToken: "refresh-token",
      memberships: []
    },
    bootstrapProfile: bootstrapProfileMock
  })
}));

vi.mock("@/shared/session/require-auth", () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => children
}));

describe("OnboardingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    bootstrapProfileMock.mockResolvedValue(true);
  });

  it("redirects to dashboard on successful onboarding", async () => {
    createOrgMock.mockResolvedValueOnce({
      org_id: "o1",
      company_id: "demo",
      name: "Demo"
    });

    render(<OnboardingPage />);

    fireEvent.change(screen.getByLabelText(/nombre de la organizacion/i), {
      target: { value: "Mi Empresa" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /crear organizacion/i }));

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("shows conflict error when company already exists", async () => {
    createOrgMock.mockRejectedValueOnce(new ApiError(409, "El company_id ya existe"));

    render(<OnboardingPage />);

    fireEvent.change(screen.getByLabelText(/nombre de la organizacion/i), {
      target: { value: "Mi Empresa" }
    });
    fireEvent.change(screen.getByLabelText(/company id/i), {
      target: { value: "demo" }
    });
    fireEvent.submit(screen.getByRole("button", { name: /crear organizacion/i }));

    await waitFor(() => {
      expect(screen.getByText("El company_id ya existe")).toBeInTheDocument();
    });
  });
});
