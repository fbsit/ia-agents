import { DashboardSummaryClient } from "@/features/agents/dashboard-summary-client";
import { RequireAuth } from "@/shared/session/require-auth";

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardSummaryClient />
    </RequireAuth>
  );
}
