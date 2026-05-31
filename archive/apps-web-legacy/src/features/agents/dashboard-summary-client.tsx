"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ChatsCircle, Database, PlusCircle, Robot, Sparkle } from "@phosphor-icons/react";

import { listAgents } from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import { listOrganizations } from "@/shared/api/tenancy";
import type { Agent, Organization } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";

export function DashboardSummaryClient() {
  const { session, bootstrapProfile } = useSession();
  const accessToken = session?.accessToken;
  const [ready, setReady] = useState(false);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    async function load() {
      if (!accessToken) {
        if (mounted) {
          setReady(true);
        }
        return;
      }

      try {
        await bootstrapProfile();
        const [orgs, items] = await Promise.all([
          listOrganizations(accessToken),
          listAgents(accessToken)
        ]);
        if (!mounted) {
          return;
        }
        setOrganizations(orgs);
        setAgents(items);
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el resumen del dashboard");
        }
      } finally {
        if (mounted) {
          setReady(true);
        }
      }
    }

    setReady(false);
    void load();
    return () => {
      mounted = false;
    };
  }, [bootstrapProfile, accessToken]);

  const indexedAgents = useMemo(
    () => agents.filter((agent) => Boolean(agent.indexed_at)).length,
    [agents]
  );

  const totalDocs = useMemo(
    () => agents.reduce((accumulator, item) => accumulator + item.documents_count, 0),
    [agents]
  );

  if (!ready) {
    return (
      <section className="stack" aria-label="Cargando dashboard">
        <div className="surface skeleton-block" />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Resumen de operacion">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">northline / control</p>
        <h1>Resumen operativo</h1>
        <p className="muted">
          Estado de tus agentes en una vista rapida. Continua con el builder para completar el flujo de 3 a 5
          minutos.
        </p>

        <div className="kpi-grid">
          <article className="kpi-box">
            <strong className="mono">Organizaciones</strong>
            <p className="mono">{organizations.length}</p>
          </article>
          <article className="kpi-box">
            <strong className="mono">Agentes creados</strong>
            <p className="mono">{agents.length}</p>
          </article>
          <article className="kpi-box">
            <strong className="mono">Indices listos</strong>
            <p className="mono">{indexedAgents}</p>
          </article>
        </div>

        <div className="cluster">
          <span className="badge-chip">
            <Database size={16} weight="duotone" />
            {totalDocs} documentos cargados
          </span>
          <span className="badge-chip">
            <Sparkle size={16} weight="duotone" />
            Humanizacion OpenAI disponible
          </span>
        </div>
      </article>

      <div className="dashboard-grid">
        <article className="surface stack">
          <h2>Ruta sugerida</h2>
          <ol className="ordered-steps">
            <li>
              <strong>Crear agente</strong>
              <p className="muted">Define objetivo, tono y backend RAG en un wizard de 4 pasos.</p>
            </li>
            <li>
              <strong>Subir documentos</strong>
              <p className="muted">Carga txt, md, csv o json y valida el estado de cada archivo.</p>
            </li>
            <li>
              <strong>Reindexar</strong>
              <p className="muted">Reconstruye el indice para actualizar el contexto recuperable.</p>
            </li>
            <li>
              <strong>Probar chat</strong>
              <p className="muted">Consulta al agente y audita fuentes con toggle de OpenAI.</p>
            </li>
          </ol>
        </article>

        <article className="surface stack">
          <h2>Quick actions</h2>
          <Link href="/agents/new" className="quick-link">
            <PlusCircle size={18} weight="duotone" />
            <span>Crear nuevo agente</span>
            <ArrowRight size={18} />
          </Link>
          <Link href="/agents" className="quick-link">
            <Robot size={18} weight="duotone" />
            <span>Gestionar agentes existentes</span>
            <ArrowRight size={18} />
          </Link>
          <Link href="/agents" className="quick-link">
            <ChatsCircle size={18} weight="duotone" />
            <span>Ir al playground de conversaciones</span>
            <ArrowRight size={18} />
          </Link>
        </article>
      </div>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
