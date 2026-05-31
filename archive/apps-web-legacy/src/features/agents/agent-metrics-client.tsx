"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ChartBar, ChatsCircle, GearSix, UploadSimple } from "@phosphor-icons/react";

import { ConsoleNav } from "@/features/agents/console-nav";
import { getAgentDocuments, getAgentIndexStatus, listAgents } from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type { Agent, AgentDocument, AgentIndexStatus } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";

type AgentMetricsClientProps = {
  agentId: string;
};

function formatDate(isoDate: string | null): string {
  if (!isoDate) {
    return "-";
  }
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return parsed.toLocaleString("es-CL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function AgentMetricsClient({ agentId }: AgentMetricsClientProps) {
  const { session } = useSession();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<AgentDocument[]>([]);
  const [indexStatus, setIndexStatus] = useState<AgentIndexStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [compatNotice, setCompatNotice] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadMetrics() {
      if (!session) {
        return;
      }

      setError("");
      setCompatNotice("");
      let statusUnavailable = false;

      try {
        const [agents, docs, status] = await Promise.all([
          listAgents(session.accessToken),
          getAgentDocuments(agentId, session.accessToken),
          getAgentIndexStatus(agentId, session.accessToken).catch((err: unknown) => {
            if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
              statusUnavailable = true;
              return null;
            }
            throw err;
          })
        ]);

        if (!mounted) {
          return;
        }

        const selected = agents.find((item) => item.agent_id === agentId) ?? null;
        setAgent(selected);
        setDocuments(docs);
        if (status) {
          setIndexStatus(status);
        } else {
          const indexedDocuments = docs.filter((item) => item.status === "indexed").length;
          const failedDocuments = docs.filter((item) => item.status === "failed").length;
          const uploadedDocuments = docs.filter((item) => item.status === "uploaded").length;
          setIndexStatus({
            agent_id: agentId,
            has_index: Boolean(selected?.indexed_at) || indexedDocuments > 0,
            indexed_at: selected?.indexed_at ?? null,
            documents_total: docs.length,
            documents_indexed: indexedDocuments,
            documents_failed: failedDocuments,
            documents_uploaded: uploadedDocuments,
            last_error: null
          });
        }

        if (statusUnavailable) {
          setCompatNotice("Estado de indexado en modo compatibilidad (fallback por metadata del agente).");
        }
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudieron cargar las metricas del agente");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void loadMetrics();
    return () => {
      mounted = false;
    };
  }, [agentId, session]);

  const readinessScore = useMemo(() => {
    if (!indexStatus) {
      return 0;
    }
    const total = Math.max(indexStatus.documents_total, 1);
    const indexedRatio = indexStatus.documents_indexed / total;
    const baseScore = Math.round(indexedRatio * 85);
    return Math.min(100, indexStatus.has_index ? baseScore + 15 : baseScore);
  }, [indexStatus]);

  const recentDocuments = useMemo(() => {
    return [...documents]
      .sort((left, right) => {
        const leftTime = new Date(left.created_at).getTime();
        const rightTime = new Date(right.created_at).getTime();
        return rightTime - leftTime;
      })
      .slice(0, 6);
  }, [documents]);

  if (loading) {
    return (
      <section className="stack" aria-label="Cargando metricas del agente">
        <ConsoleNav />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Metricas del agente">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / metricas</p>
        <h1>{agent?.name ?? "Agente"}</h1>
        <p className="muted">Panel operativo para medir cobertura documental, salud del indice y proximo paso.</p>
      </article>

      <div className="dashboard-grid">
        <article className="surface stack">
          <div className="cluster between">
            <h2>Indicadores clave</h2>
            <span className="badge-chip">
              <ChartBar size={16} weight="duotone" />
              readiness: {readinessScore}%
            </span>
          </div>

          <div className="kpi-grid">
            <article className="kpi-box">
              <strong className="mono">Documentos</strong>
              <p className="mono">{indexStatus?.documents_total ?? 0}</p>
            </article>
            <article className="kpi-box">
              <strong className="mono">Indexados</strong>
              <p className="mono">{indexStatus?.documents_indexed ?? 0}</p>
            </article>
            <article className="kpi-box">
              <strong className="mono">Fallidos</strong>
              <p className="mono">{indexStatus?.documents_failed ?? 0}</p>
            </article>
            <article className="kpi-box">
              <strong className="mono">Ultimo indexado</strong>
              <p className="mono">{formatDate(indexStatus?.indexed_at ?? null)}</p>
            </article>
          </div>

          {indexStatus?.last_error ? <p className="error">{indexStatus.last_error}</p> : null}
        </article>

        <article className="surface stack">
          <h2>Acciones recomendadas</h2>
          <Link href={`/agents/${agentId}/knowledge/new?section=facts`} className="quick-link">
            <UploadSimple size={18} weight="duotone" />
            <span>Completar conocimiento operativo</span>
            <ArrowRight size={18} />
          </Link>
          <Link href={`/agents/${agentId}/playground`} className="quick-link">
            <ChatsCircle size={18} weight="duotone" />
            <span>Validar respuestas en pruebas</span>
            <ArrowRight size={18} />
          </Link>
          <Link href={`/agents/${agentId}/deploy`} className="quick-link">
            <GearSix size={18} weight="duotone" />
            <span>Revisar checklist de despliegue</span>
            <ArrowRight size={18} />
          </Link>
        </article>
      </div>

      <article className="surface stack">
        <h2>Documentos recientes</h2>
        {!recentDocuments.length ? (
          <div className="empty-state">
            <p className="muted">No hay documentos cargados todavia para este agente.</p>
          </div>
        ) : (
          <div className="stack compact">
            {recentDocuments.map((document) => (
              <div key={document.document_id} className="source-row cluster between">
                <span className="mono">{document.filename}</span>
                <span className={`status-pill ${document.status}`}>{document.status}</span>
                <span className="mono muted">{formatDate(document.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </article>

      {compatNotice ? <p className="muted">{compatNotice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
