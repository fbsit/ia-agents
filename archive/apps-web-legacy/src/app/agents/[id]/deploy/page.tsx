import { DeployChecklistClient } from "@/features/agents/deploy-checklist-client";
import { RequireAuth } from "@/shared/session/require-auth";

type DeployPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function DeployPage({ params }: DeployPageProps) {
  const { id } = await params;

  return (
    <RequireAuth>
      <DeployChecklistClient agentId={id} />
    </RequireAuth>
  );
}
