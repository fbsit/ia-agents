import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import DashboardPage from "@/app/dashboard/page";

const listOrganizationsMock = vi.fn();
const listAgentsMock = vi.fn();
const bootstrapProfileMock = vi.fn();

vi.mock("@/shared/api/tenancy", () => ({
  listOrganizations: (...args: unknown[]) => listOrganizationsMock(...args)
}));

vi.mock("@/shared/api/agents", () => ({
  listAgents: (...args: unknown[]) => listAgentsMock(...args)
}));

vi.mock("@/shared/session/provider", () => ({
  useSession: () => ({
    session: {
      userId: "u1",
      email: "owner@demo.com",
      accessToken: "access-token",
      refreshToken: "refresh-token",
      memberships: [{ org_id: "o1", role: "owner" }]
    },
    bootstrapProfile: bootstrapProfileMock
  })
}));

vi.mock("@/shared/session/require-auth", () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => children
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    replace: vi.fn(),
    push: vi.fn()
  })
}));

describe("DashboardPage", () => {
  it("renders operational summary and quick actions", async () => {
    bootstrapProfileMock.mockResolvedValue(true);
    listOrganizationsMock.mockResolvedValue([
      { org_id: "o1", name: "Norte Logistics", company_id: "norte-logistics", role: "owner" }
    ]);
    listAgentsMock.mockResolvedValue([
      {
        agent_id: "a1",
        org_id: "o1",
        company_id: "norte-logistics",
        name: "Atlas Support",
        objective: "Responder consultas de soporte",
        tone: "profesional",
        description: "",
        rag_backend: "tfidf",
        generation_provider: "auto",
        use_openai_generation: true,
        openai_model: "gpt-4o-mini",
        knowledge_dir: "knowledge",
        index_path: "index",
        indexed_at: "2026-01-01T10:00:00Z",
        documents_count: 3
      }
    ]);

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/resumen operativo/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/quick actions/i)).toBeInTheDocument();
    expect(screen.getByText(/crear nuevo agente/i)).toBeInTheDocument();
  });
});
