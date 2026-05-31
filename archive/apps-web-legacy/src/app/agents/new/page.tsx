import { AgentWizardClient } from "@/features/agents/agent-wizard-client";
import { RequireAuth } from "@/shared/session/require-auth";

export default function NewAgentPage() {
  return (
    <RequireAuth>
      <AgentWizardClient />
    </RequireAuth>
  );
}
