import { LlmSettingsClient } from "@/features/settings/llm-settings-client";
import { RequireAuth } from "@/shared/session/require-auth";

export default function SettingsPage() {
  return (
    <RequireAuth>
      <LlmSettingsClient />
    </RequireAuth>
  );
}
