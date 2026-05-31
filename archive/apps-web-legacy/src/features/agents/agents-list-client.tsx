"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Database, GearSix, PlusCircle, Trash } from "@phosphor-icons/react";

import { deleteAgent, listAgents } from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import { listOrganizations } from "@/shared/api/tenancy";
import type { Agent, Organization } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";

export function AgentsListClient() {
  const { session } = useSession();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [activeCompanyId, setActiveCompanyId] = useState("");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingAgentId, setDeletingAgentId] = useState("");
  const [error, setError] = useState("");

  async function refreshAgents(companyId: string) {
    if (!session || !companyId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await listAgents(session.accessToken, companyId);
      setAgents(response);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo cargar el listado de agentes");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteAgent(agent: Agent) {
    if (!session) {
      return;
    }
    const confirmed = window.confirm(`Vas a eliminar el agente '${agent.name}'. Esta accion no se puede deshacer.`);
    if (!confirmed) {
      return;
    }

    setDeletingAgentId(agent.agent_id);
    setError("");
    try {
      await deleteAgent(agent.agent_id, session.accessToken);
      await refreshAgents(activeCompanyId);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo eliminar el agente");
      }
    } finally {
      setDeletingAgentId("");
    }
  }

  useEffect(() => {
    let mounted = true;

    async function loadOrganizations() {
      if (!session) {
        return;
      }
      try {
        const response = await listOrganizations(session.accessToken);
        if (!mounted) {
          return;
        }
        setOrganizations(response);
        if (response.length > 0) {
          setActiveCompanyId(response[0].company_id);
        }
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudieron cargar las organizaciones");
        }
      }
    }

    void loadOrganizations();
    return () => {
      mounted = false;
    };
  }, [session]);

  useEffect(() => {
    let mounted = true;

    async function loadAgents() {
      if (!session || !activeCompanyId) {
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const response = await listAgents(session.accessToken, activeCompanyId);
        if (!mounted) {
          return;
        }
        setAgents(response);
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el listado de agentes");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void loadAgents();
    return () => {
      mounted = false;
    };
  }, [activeCompanyId, session]);

  return (
    <section className="stack console-screen" aria-label="Lista de agentes">
      <ConsoleNav
        organizations={organizations}
        activeCompanyId={activeCompanyId}
        onCompanyChange={setActiveCompanyId}
      />

      <article className="surface stack">
        <div className="cluster between">
          <div className="stack compact">
            <p className="mono muted">agents / workspace</p>
            <h1>Agentes por organizacion</h1>
            <p className="muted">Selecciona tenant, revisa estado de indice y abre los modulos de trabajo.</p>
          </div>
          <Link href="/agents/new" className="button-link">
            <PlusCircle size={18} weight="duotone" />
            <span>Crear agente</span>
          </Link>
        </div>

      </article>

      {loading ? (
        <div className="stack">
          <div className="surface skeleton-row" />
          <div className="surface skeleton-row" />
        </div>
      ) : null}

      {!loading && !agents.length ? (
        <article className="surface empty-state">
          <h2>Sin agentes en esta organizacion</h2>
          <p className="muted">Crea tu primer agente y luego carga documentos para activar RAG.</p>
          <p>
            <Link href="/agents/new">Ir al wizard</Link>
          </p>
        </article>
      ) : null}

      {!loading && agents.length > 0 ? (
        <div className="agents-grid">
          {agents.map((agent) => (
            <article key={agent.agent_id} className="surface agent-card">
              <div className="stack compact">
                <div className="cluster wrap agent-title-row">
                  <h2>{agent.name}</h2>
                  <span className="badge-chip">
                    <Database size={16} weight="duotone" />
                    tone: {agent.tone}
                  </span>
                </div>
                <p className="muted">{agent.objective}</p>
              </div>

              <div className="cluster agent-card-actions">
                <Link
                  href={`/agents/${agent.agent_id}/dashboard`}
                  className="button-link ghost-link agent-config-link"
                >
                  <GearSix size={18} weight="duotone" />
                  <span>Configurar</span>
                </Link>
                <button
                  type="button"
                  className="button-link ghost-link"
                  onClick={() => void handleDeleteAgent(agent)}
                  disabled={deletingAgentId === agent.agent_id}
                >
                  <Trash size={18} weight="duotone" />
                  <span>{deletingAgentId === agent.agent_id ? "Eliminando..." : "Eliminar"}</span>
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
