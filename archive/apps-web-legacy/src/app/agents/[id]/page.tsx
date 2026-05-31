import { redirect } from "next/navigation";

type AgentLandingPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function AgentLandingPage({ params }: AgentLandingPageProps) {
  const { id } = await params;
  redirect(`/agents/${id}/dashboard`);
}
