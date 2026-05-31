import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { RequireAuth } from "@/shared/session/require-auth";

const replaceMock = vi.fn();
let readyMock = true;
let sessionMock: object | null = null;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: replaceMock })
}));

vi.mock("@/shared/session/provider", () => ({
  useSession: () => ({
    ready: readyMock,
    session: sessionMock
  })
}));

describe("RequireAuth", () => {
  it("renders children when session exists", () => {
    readyMock = true;
    sessionMock = {
      userId: "u1",
      email: "owner@demo.com"
    };

    render(
      <RequireAuth>
        <p>Contenido protegido</p>
      </RequireAuth>
    );

    expect(screen.getByText("Contenido protegido")).toBeInTheDocument();
  });

  it("redirects to login when session is missing", async () => {
    readyMock = true;
    sessionMock = null;

    render(
      <RequireAuth>
        <p>Contenido protegido</p>
      </RequireAuth>
    );

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
  });
});
