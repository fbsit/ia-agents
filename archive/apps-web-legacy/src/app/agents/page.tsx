import { AgentsListClient } from "@/features/agents/agents-list-client";
import { RequireAuth } from "@/shared/session/require-auth";

export default function AgentsPage() {
  return (
    <RequireAuth>
      <AgentsListClient />
    </RequireAuth>
  );
}
