"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ArrowClockwise, FileArrowUp, FileX, Trash } from "@phosphor-icons/react";

import {
  deleteAgentDocument,
  getAgentDocuments,
  getAgentIndexStatus,
  listAgents,
  rebuildAgentIndex,
  uploadAgentDocument
} from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type { Agent, AgentDocument, AgentIndexStatus } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";
import { OPERATIONAL_SECTIONS, matchesOperationalSection } from "@/features/agents/knowledge-templates";

type KnowledgeUploaderClientProps = {
  agentId: string;
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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


const FALLBACK_DOCS_KEY_PREFIX = "clasi-agent-fallback-docs";

function fallbackDocsKey(agentId: string): string {
  return `${FALLBACK_DOCS_KEY_PREFIX}:${agentId}`;
}

function readFallbackDocuments(agentId: string): AgentDocument[] {
  if (typeof window === "undefined") {
    return [];
  }

  const raw = window.sessionStorage.getItem(fallbackDocsKey(agentId));
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as AgentDocument[];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed;
  } catch {
    return [];
  }
}

function writeFallbackDocuments(agentId: string, documents: AgentDocument[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(fallbackDocsKey(agentId), JSON.stringify(documents));
}

export function KnowledgeUploaderClient({ agentId }: KnowledgeUploaderClientProps) {
  const { session } = useSession();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<AgentDocument[]>([]);
  const [indexStatus, setIndexStatus] = useState<AgentIndexStatus | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [compatNotice, setCompatNotice] = useState("");
  const [docsApiUnavailable, setDocsApiUnavailable] = useState(false);
  const [indexStatusApiUnavailable, setIndexStatusApiUnavailable] = useState(false);

  const operationalCoverage = useMemo(() => {
    return OPERATIONAL_SECTIONS.map((section) => {
      const completed = documents.some(
        (document) => document.status !== "failed" && matchesOperationalSection(document.filename, section)
      );
      return {
        ...section,
        completed
      };
    });
  }, [documents]);

  const completedSections = useMemo(() => {
    return operationalCoverage.filter((section) => section.completed).length;
  }, [operationalCoverage]);

  const readinessProgress = useMemo(() => {
    const base = Math.round((completedSections / OPERATIONAL_SECTIONS.length) * 100);
    if (!indexStatus?.has_index) {
      return Math.max(base, 8);
    }
    return Math.min(100, base + 10);
  }, [completedSections, indexStatus?.has_index]);

  const nextSection = useMemo(() => {
    return operationalCoverage.find((section) => !section.completed) ?? null;
  }, [operationalCoverage]);

  const loadAll = useCallback(async () => {
    if (!session) {
      return;
    }

    setCompatNotice("");
    const compatibilityHints: string[] = [];
    let docsUnavailable = false;
    let statusUnavailable = false;

    const docsPromise = getAgentDocuments(agentId, session.accessToken).catch((err: unknown) => {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
        docsUnavailable = true;
        compatibilityHints.push("Listado de documentos no disponible en este backend (se usa historial local).");
        return readFallbackDocuments(agentId);
      }
      throw err;
    });

    const indexStatusPromise = getAgentIndexStatus(agentId, session.accessToken).catch((err: unknown) => {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
        statusUnavailable = true;
        compatibilityHints.push("Estado de indexado no disponible en este backend.");
        return null;
      }
      throw err;
    });

    const [agents, docs, idxStatus] = await Promise.all([
      listAgents(session.accessToken),
      docsPromise,
      indexStatusPromise
    ]);

    setAgent(agents.find((item) => item.agent_id === agentId) ?? null);
    setDocuments(docs);
    setIndexStatus(idxStatus);
    setDocsApiUnavailable(docsUnavailable);
    setIndexStatusApiUnavailable(statusUnavailable);
    if (!docsUnavailable) {
      writeFallbackDocuments(agentId, docs);
    }
    if (compatibilityHints.length > 0) {
      setCompatNotice(compatibilityHints.join(" "));
    }
  }, [agentId, session]);

  useEffect(() => {
    let mounted = true;

    async function initialize() {
      if (!session) {
        return;
      }

      try {
        await loadAll();
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar la vista de conocimiento");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void initialize();
    return () => {
      mounted = false;
    };
  }, [loadAll, session]);

  const statusText = useMemo(() => {
    if (!indexStatus) {
      return "sin datos";
    }
    return `docs=${indexStatus.documents_total} indexed=${indexStatus.documents_indexed} failed=${indexStatus.documents_failed}`;
  }, [indexStatus]);

  async function onUpload() {
    if (!session || !pendingFile) {
      setError("Selecciona un archivo primero");
      return;
    }

    setUploading(true);
    setError("");
    setStatus("");

    try {
      const uploaded = await uploadAgentDocument(agentId, pendingFile, session.accessToken);
      if (docsApiUnavailable) {
        const fallbackList = readFallbackDocuments(agentId);
        const fallbackDocumentId = uploaded.document_id || `${Date.now()}-${pendingFile.name}`;
        const fallbackItem: AgentDocument = {
          document_id: fallbackDocumentId,
          agent_id: uploaded.agent_id || agentId,
          filename: uploaded.filename || pendingFile.name,
          size_bytes: uploaded.size_bytes || pendingFile.size,
          status: uploaded.status ?? "uploaded",
          indexed_at: uploaded.indexed_at ?? null,
          error_message: uploaded.error_message ?? null,
          created_at: uploaded.created_at ?? new Date().toISOString(),
          operational_section: uploaded.operational_section ?? null,
          learning_summary: uploaded.learning_summary ?? null,
          summary_updated_at: uploaded.summary_updated_at ?? null
        };
        const merged = [fallbackItem, ...fallbackList.filter((item) => item.document_id !== fallbackItem.document_id)];
        writeFallbackDocuments(agentId, merged);
      }
      await loadAll();
      setPendingFile(null);
      setStatus("Archivo cargado. Ejecuta reconstruccion de indice para habilitar consultas.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo subir el documento");
      }
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(documentId: string) {
    if (!session) {
      return;
    }
    setError("");
    setStatus("");

    try {
      await deleteAgentDocument(agentId, documentId, session.accessToken);
      if (docsApiUnavailable) {
        const fallbackList = readFallbackDocuments(agentId).filter((item) => item.document_id !== documentId);
        writeFallbackDocuments(agentId, fallbackList);
      }
      await loadAll();
      setStatus("Documento eliminado");
    } catch (err) {
      if (err instanceof ApiError && docsApiUnavailable && (err.status === 404 || err.status === 405)) {
        const fallbackList = readFallbackDocuments(agentId).filter((item) => item.document_id !== documentId);
        writeFallbackDocuments(agentId, fallbackList);
        await loadAll();
        setStatus("Documento eliminado del historial local");
        return;
      }
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo eliminar el documento");
      }
    }
  }

  async function onRebuild() {
    if (!session) {
      return;
    }
    setIndexing(true);
    setError("");
    setStatus("");
    try {
      const result = await rebuildAgentIndex(agentId, session.accessToken);
      if (docsApiUnavailable) {
        const indexedAt = new Date().toISOString();
        const fallbackList = readFallbackDocuments(agentId).map((item) => ({
          ...item,
          status: "indexed" as const,
          indexed_at: indexedAt,
          error_message: null
        }));
        writeFallbackDocuments(agentId, fallbackList);
      }
      await loadAll();
      if (indexStatusApiUnavailable) {
        const fallbackList = readFallbackDocuments(agentId);
        setIndexStatus({
          agent_id: agentId,
          has_index: result.total_documents > 0,
          indexed_at: new Date().toISOString(),
          documents_total: fallbackList.length,
          documents_indexed: fallbackList.filter((item) => item.status === "indexed").length,
          documents_failed: fallbackList.filter((item) => item.status === "failed").length,
          documents_uploaded: fallbackList.filter((item) => item.status === "uploaded").length,
          last_error: null
        });
      }
      setStatus(
        `Indice reconstruido (${result.backend}). total_documents=${result.total_documents}, total_chunks=${result.total_chunks}`
      );
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo reconstruir el indice");
      }
    } finally {
      setIndexing(false);
    }
  }

  if (loading) {
    return (
      <section className="stack" aria-label="Cargando conocimiento">
        <ConsoleNav />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Modulo de conocimiento">
      <ConsoleNav />

      <div className="knowledge-shell">
        <div className="knowledge-main stack">
          <article className="surface stack">
            <p className="mono muted">agents / knowledge</p>
            <h1>{agent?.name ?? "Agente"}</h1>
            <p className="muted">Disena conocimiento operativo con una ruta simple: hechos, reglas, contratos, permisos y feedback.</p>

            <div className="knowledge-meter" aria-label="Progreso de conocimiento operativo">
              <div className="cluster between">
                <p className="mono muted">readiness: {readinessProgress}%</p>
                <p className="mono muted">bloques listos: {completedSections}/5</p>
              </div>
              <div className="knowledge-meter-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={readinessProgress}>
                <span className="knowledge-meter-fill" style={{ width: `${readinessProgress}%` }} />
              </div>
              <p className="mono muted">index_status: {statusText}</p>
            </div>

            <div className="cluster">
              <Link href={`/agents/${agentId}/playground`} className="button-link ghost-link">
                Ir a playground
              </Link>
              <Link href={`/agents/${agentId}/deploy`} className="button-link ghost-link">
                Ir a deploy
              </Link>
            </div>
          </article>

          <article className="surface stack">
            <h2>Subida de documentos</h2>
            <motion.div
              className={dragActive ? "dropzone active" : "dropzone"}
              onDragOver={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragActive(false);
                const dropped = event.dataTransfer.files?.[0];
                if (dropped) {
                  setPendingFile(dropped);
                }
              }}
              initial={{ opacity: 0.9 }}
              animate={{ opacity: 1 }}
              transition={{ type: "spring", stiffness: 100, damping: 20 }}
            >
              <FileArrowUp size={22} weight="duotone" />
              <p>Arrastra tu archivo o selecciona uno manualmente</p>
              <p className="muted mono">formatos permitidos: .txt .md .csv .json</p>
            </motion.div>

            <input
              type="file"
              accept=".txt,.md,.csv,.json"
              onChange={(event) => setPendingFile(event.target.files?.[0] ?? null)}
            />

            <p className="muted mono">archivo: {pendingFile ? `${pendingFile.name} (${pendingFile.size} bytes)` : "ninguno"}</p>
            <p className="muted">
              {nextSection
                ? `Siguiente recomendado: cargar ${nextSection.label.toLowerCase()}.`
                : "Excelente: ya cubriste los 5 bloques operativos. Podes reconstruir indice y validar en playground."}
            </p>

            <div className="cluster">
              <button type="button" disabled={uploading || !pendingFile} onClick={onUpload}>
                {uploading ? "Subiendo..." : "Subir"}
              </button>
              <button type="button" disabled={indexing} onClick={onRebuild}>
                <ArrowClockwise size={16} />
                {indexing ? "Reconstruyendo..." : "Reconstruir indice"}
              </button>
            </div>
          </article>

          <article className="surface stack">
            <h2>Plan UX simple para lograr operacion</h2>
            <div className="knowledge-plan-grid">
              <article className="knowledge-plan-step">
                <p className="mono muted">Fase 1</p>
                <strong>Modelar conocimiento oficial</strong>
                <p className="muted">Completa hechos canonicos y reglas de decision. Objetivo: cero ambiguedad en decisiones criticas.</p>
              </article>
              <article className="knowledge-plan-step">
                <p className="mono muted">Fase 2</p>
                <strong>Conectar acciones seguras</strong>
                <p className="muted">Subi contratos de accion y matriz de permisos para ejecutar API, correo y estados con guardrails.</p>
              </article>
              <article className="knowledge-plan-step">
                <p className="mono muted">Fase 3</p>
                <strong>Cerrar ciclo de aprendizaje</strong>
                <p className="muted">Registra feedback de ejecucion y ajusta reglas por tasa de fallo, no por intuicion.</p>
              </article>
            </div>
          </article>
        </div>

        <aside className="knowledge-sidebar stack" aria-label="Sidebar de conocimiento">
          <article className="surface stack">
            <h2>Historial de documentos</h2>

            {!documents.length ? (
              <div className="empty-state">
                <p className="muted">No hay documentos cargados en este agente.</p>
              </div>
            ) : (
              <div className="doc-table" role="table" aria-label="Documentos del agente">
                <div className="doc-row header" role="row">
                  <span>Archivo</span>
                  <span>Estado</span>
                  <span>Tamano</span>
                  <span>Creado</span>
                  <span>Accion</span>
                </div>
                {documents.map((document) => (
                  <div key={document.document_id} className="doc-row" role="row">
                    <span className="mono">{document.filename}</span>
                    <span className={`status-pill ${document.status}`}>{document.status}</span>
                    <span className="mono">{formatBytes(document.size_bytes)}</span>
                    <span className="mono muted">{formatDate(document.created_at)}</span>
                    <button type="button" className="inline-danger" onClick={() => onDelete(document.document_id)}>
                      <Trash size={14} />
                      Eliminar
                    </button>
                  </div>
                ))}
              </div>
            )}

            {indexStatus?.last_error ? (
              <p className="error">
                <FileX size={16} /> {indexStatus.last_error}
              </p>
            ) : null}
          </article>

          <article className="surface stack">
            <h2>Bloques operativos</h2>
            <div className="knowledge-card-grid" aria-label="Bloques operativos">
              {operationalCoverage.map((section) => (
                <article key={section.id} className="knowledge-card">
                  <div className="cluster between">
                    <h3>{section.label}</h3>
                    <span className={section.completed ? "knowledge-state done" : "knowledge-state pending"}>
                      {section.completed ? "listo" : "pendiente"}
                    </span>
                  </div>
                  <p className="muted">{section.description}</p>
                  <p className="mono muted">archivo recomendado: {section.filenameHint}</p>
                  <ul className="knowledge-checks">
                    {section.checks.map((check) => (
                      <li key={check}>{check}</li>
                    ))}
                  </ul>
                  <Link href={`/agents/${agentId}/knowledge/new?section=${section.id}`} className="button-link ghost-link">
                    Preparar plantilla
                  </Link>
                </article>
              ))}
            </div>
          </article>
        </aside>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {compatNotice ? <p className="muted">{compatNotice}</p> : null}
      {status ? <p className="success">{status}</p> : null}
    </section>
  );
}
