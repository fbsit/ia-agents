import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";

const replaceMock = vi.fn();
let readyMock = false;
let hasSessionMock = false;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: replaceMock })
}));

vi.mock("@/shared/session/provider", () => ({
  useSession: () => ({
    ready: readyMock,
    session: hasSessionMock ? { userId: "u1" } : null
  })
}));

describe("HomePage bootstrap route", () => {
  it("renders bootstrap message while initializing", () => {
    readyMock = false;
    hasSessionMock = false;
    render(<HomePage />);
    expect(screen.getByText(/inicializando dashboard/i)).toBeInTheDocument();
  });

  it("redirects to login when no session", async () => {
    readyMock = true;
    hasSessionMock = false;

    render(<HomePage />);
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
  });
});
