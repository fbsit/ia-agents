import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "@/shared/session/provider";

const fetchMeMock = vi.fn();

vi.mock("@/shared/api/auth", () => ({
  fetchMe: (...args: unknown[]) => fetchMeMock(...args)
}));

function Harness() {
  const { setFromLogin, bootstrapProfile, session } = useSession();
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          setFromLogin({
            user_id: "u1",
            email: "owner@demo.com",
            memberships: [],
            tokens: {
              access_token: "access",
              refresh_token: "refresh",
              token_type: "bearer"
            }
          })
        }
      >
        seed
      </button>
      <button
        type="button"
        onClick={async () => {
          await bootstrapProfile();
        }}
      >
        bootstrap
      </button>
      <span data-testid="email">{session?.email ?? "none"}</span>
    </div>
  );
}

function Wrapper({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}

describe("SessionProvider bootstrapProfile", () => {
  it("keeps session and updates profile on valid /me", async () => {
    fetchMeMock.mockResolvedValueOnce({
      user_id: "u1",
      email: "owner+updated@demo.com",
      memberships: [{ org_id: "o1", role: "owner" }]
    });

    render(<Harness />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: "seed" }));
    fireEvent.click(screen.getByRole("button", { name: "bootstrap" }));

    await waitFor(() => {
      expect(screen.getByTestId("email")).toHaveTextContent("owner+updated@demo.com");
    });
  });

  it("clears session on invalid /me response", async () => {
    fetchMeMock.mockRejectedValueOnce(new Error("Unauthorized"));

    render(<Harness />, { wrapper: Wrapper });
    fireEvent.click(screen.getByRole("button", { name: "seed" }));
    fireEvent.click(screen.getByRole("button", { name: "bootstrap" }));

    await waitFor(() => {
      expect(screen.getByTestId("email")).toHaveTextContent("none");
    });
  });
});
