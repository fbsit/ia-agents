import { redirect } from "next/navigation";

type KnowledgePageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function KnowledgePage({ params }: KnowledgePageProps) {
  const { id } = await params;
  redirect(`/agents/${id}/knowledge/new?section=facts`);
}
