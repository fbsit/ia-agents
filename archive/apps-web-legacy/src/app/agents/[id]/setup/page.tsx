import { AgentSetupClient } from "@/features/agents/agent-setup-client";
import { RequireAuth } from "@/shared/session/require-auth";

type AgentSetupPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AgentSetupPage({ params }: AgentSetupPageProps) {
  const { id } = await params;

  return (
    <RequireAuth>
      <AgentSetupClient agentId={id} />
    </RequireAuth>
  );
}
