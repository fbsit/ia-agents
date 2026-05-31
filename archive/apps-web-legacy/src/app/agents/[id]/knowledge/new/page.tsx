import { KnowledgeComposeClient } from "@/features/agents/knowledge-compose-client";
import { RequireAuth } from "@/shared/session/require-auth";

type KnowledgeComposePageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function KnowledgeComposePage({ params }: KnowledgeComposePageProps) {
  const { id } = await params;

  return (
    <RequireAuth>
      <KnowledgeComposeClient agentId={id} />
    </RequireAuth>
  );
}
