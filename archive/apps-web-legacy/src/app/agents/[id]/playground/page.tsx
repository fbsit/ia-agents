import { PlaygroundChatClient } from "@/features/agents/playground-chat-client";
import { RequireAuth } from "@/shared/session/require-auth";

type PlaygroundPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function PlaygroundPage({ params }: PlaygroundPageProps) {
  const { id } = await params;

  return (
    <RequireAuth>
      <PlaygroundChatClient agentId={id} />
    </RequireAuth>
  );
}
