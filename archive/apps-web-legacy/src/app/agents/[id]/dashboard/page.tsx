import { AgentDashboardClient } from "@/features/agents/agent-dashboard-client";
import { RequireAuth } from "@/shared/session/require-auth";

type AgentDashboardPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AgentDashboardPage({ params }: AgentDashboardPageProps) {
  const { id } = await params;

  return (
    <RequireAuth>
      <AgentDashboardClient agentId={id} />
    </RequireAuth>
  );
}
