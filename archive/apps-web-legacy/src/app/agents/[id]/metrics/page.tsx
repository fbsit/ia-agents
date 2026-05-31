import { redirect } from "next/navigation";

type AgentMetricsPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AgentMetricsPage({ params }: AgentMetricsPageProps) {
  const { id } = await params;
  redirect(`/agents/${id}/dashboard`);
}
