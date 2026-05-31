"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowClockwise, FileArrowUp, FloppyDisk } from "@phosphor-icons/react";

import { ConsoleNav } from "@/features/agents/console-nav";
import {
  buildTemplateContent,
  findOperationalSection,
  matchesOperationalSection,
  OPERATIONAL_SECTIONS,
  type OperationalKnowledgeSection,
  type OperationalKnowledgeSectionId
} from "@/features/agents/knowledge-templates";
import {
  analyzeAgentWebUrl,
  getAgentDocumentContent,
  getAgentDocuments,
  listAgents,
  rebuildAgentIndex,
  uploadAgentDocument
} from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type { Agent, AgentDocument, AgentWebAnalysis } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";

type KnowledgeComposeClientProps = {
  agentId: string;
};

type ComposeMode = "write" | "upload";

type SectionComposeDraft = {
  mode: ComposeMode;
  draft: string;
  filename: string;
  uploadedFile: File | null;
};

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
    return Array.isArray(parsed) ? parsed : [];
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

function defaultFilename(section: OperationalKnowledgeSection): string {
  return section.filenameHint;
}

function normalizeMarkdownFilename(filename: string, section: OperationalKnowledgeSection): string {
  const base = filename.trim() || defaultFilename(section);
  return base.toLowerCase().endsWith(".md") ? base : `${base}.md`;
}

function createDefaultDraft(section: OperationalKnowledgeSection, companyId: string): SectionComposeDraft {
  return {
    mode: "write",
    draft: buildTemplateContent(section, companyId),
    filename: defaultFilename(section),
    uploadedFile: null
  };
}

export function KnowledgeComposeClient({ agentId }: KnowledgeComposeClientProps) {
  const { session } = useSession();
  const searchParams = useSearchParams();

  const initialSectionId = useMemo(() => {
    return findOperationalSection(searchParams.get("section")).id;
  }, [searchParams]);

  const [activeSectionId, setActiveSectionId] = useState<OperationalKnowledgeSectionId>(initialSectionId);

  const section = useMemo(() => {
    return findOperationalSection(activeSectionId);
  }, [activeSectionId]);

  const [agent, setAgent] = useState<Agent | null>(null);
  const [documents, setDocuments] = useState<AgentDocument[]>([]);
  const [mode, setMode] = useState<ComposeMode>("write");
  const [draft, setDraft] = useState("");
  const [filename, setFilename] = useState("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [sectionDrafts, setSectionDrafts] = useState<Partial<Record<OperationalKnowledgeSectionId, SectionComposeDraft>>>({});
  const [hydratedSections, setHydratedSections] = useState<Partial<Record<OperationalKnowledgeSectionId, boolean>>>({});
  const [rebuildNow, setRebuildNow] = useState(true);
  const [analysisUrl, setAnalysisUrl] = useState("");
  const [analyzingUrl, setAnalyzingUrl] = useState(false);
  const [lastWebAnalysis, setLastWebAnalysis] = useState<AgentWebAnalysis | null>(null);
  const [docsApiUnavailable, setDocsApiUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingPersistedContent, setLoadingPersistedContent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const operationalCoverage = useMemo(() => {
    return OPERATIONAL_SECTIONS.map((item) => {
      const completed = documents.some(
        (document) => document.status !== "failed" && matchesOperationalSection(document.filename, item)
      );
      return {
        ...item,
        completed
      };
    });
  }, [documents]);

  const currentSectionState = useMemo(() => {
    return operationalCoverage.find((item) => item.id === section.id) ?? null;
  }, [operationalCoverage, section.id]);
  const completedSections = useMemo(() => {
    return operationalCoverage.filter((item) => item.completed).length;
  }, [operationalCoverage]);
  const completionPercent = useMemo(() => {
    return Math.round((completedSections / OPERATIONAL_SECTIONS.length) * 100);
  }, [completedSections]);
  const sectionDocuments = useMemo(() => {
    return documents
      .filter((document) => {
        if (document.status === "failed") {
          return false;
        }
        if (document.operational_section) {
          return document.operational_section === section.id;
        }
        return matchesOperationalSection(document.filename, section);
      })
      .sort((left, right) => {
        const leftTime = new Date(left.created_at).getTime();
        const rightTime = new Date(right.created_at).getTime();
        return rightTime - leftTime;
      });
  }, [documents, section]);

  const selectedDocument = useMemo(() => {
    if (!sectionDocuments.length) {
      return null;
    }
    return sectionDocuments[0] ?? null;
  }, [sectionDocuments]);

  const loadState = useCallback(async () => {
    if (!session) {
      return;
    }

    let docsUnavailable = false;
    const docsPromise = getAgentDocuments(agentId, session.accessToken).catch((err: unknown) => {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
        docsUnavailable = true;
        return readFallbackDocuments(agentId);
      }
      throw err;
    });

    const [agents, docs] = await Promise.all([listAgents(session.accessToken), docsPromise]);

    setAgent(agents.find((item) => item.agent_id === agentId) ?? null);
    setDocuments(docs);
    setDocsApiUnavailable(docsUnavailable);
    if (!docsUnavailable) {
      writeFallbackDocuments(agentId, docs);
    }
  }, [agentId, session]);

  useEffect(() => {
    let mounted = true;

    async function initialize() {
      if (!session) {
        return;
      }

      setError("");
      try {
        await loadState();
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el agente");
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
  }, [loadState, session]);

  useEffect(() => {
    if (initialSectionId === activeSectionId) {
      return;
    }

    setActiveSectionId(initialSectionId);
  }, [activeSectionId, initialSectionId]);

  useEffect(() => {
    const companyId = agent?.company_id ?? "company-id";
    const savedDraft = sectionDrafts[activeSectionId];
    const source = savedDraft ?? createDefaultDraft(section, companyId);

    setMode(source.mode);
    setDraft(source.draft);
    setFilename(source.filename);
    setUploadedFile(source.uploadedFile);
  }, [activeSectionId, agent?.company_id, section, sectionDrafts]);

  useEffect(() => {
    if (!session || !agent) {
      return;
    }
    if (hydratedSections[activeSectionId]) {
      return;
    }
    if (sectionDrafts[activeSectionId]) {
      setHydratedSections((prev) => ({ ...prev, [activeSectionId]: true }));
      return;
    }

    let cancelled = false;
    const sectionId = activeSectionId;
    const currentSection = findOperationalSection(sectionId);
    const latestDocument = sectionDocuments[0] ?? null;

    if (!latestDocument) {
      setHydratedSections((prev) => ({ ...prev, [sectionId]: true }));
      return;
    }

    async function hydrateSectionDraft() {
      setLoadingPersistedContent(true);
      try {
        const documentContent = await getAgentDocumentContent(
          agentId,
          latestDocument.document_id,
          session.accessToken
        );
        if (cancelled) {
          return;
        }

        const hydratedDraft: SectionComposeDraft = {
          mode: "write",
          draft: documentContent.content,
          filename: documentContent.filename,
          uploadedFile: null
        };

        setSectionDrafts((prev) => ({
          ...prev,
          [sectionId]: hydratedDraft
        }));

        if (sectionId === activeSectionId) {
          setMode("write");
          setDraft(documentContent.content);
          setFilename(documentContent.filename);
          setUploadedFile(null);
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
          setHydratedSections((prev) => ({ ...prev, [sectionId]: true }));
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el documento guardado");
        }
      } finally {
        if (!cancelled) {
          setHydratedSections((prev) => ({ ...prev, [sectionId]: true }));
          setLoadingPersistedContent(false);
        }
      }
    }

    void hydrateSectionDraft();

    return () => {
      cancelled = true;
    };
  }, [
    activeSectionId,
    agent,
    agentId,
    documents,
    hydratedSections,
    sectionDocuments,
    sectionDrafts,
    session,
  ]);

  async function onSave() {
    if (!session) {
      setError("Tu sesion expiro. Inicia sesion nuevamente para guardar.");
      return;
    }
    if (!agent) {
      setError("No se pudo resolver el agente actual. Recarga la vista.");
      return;
    }

    setSaving(true);
    setStatus("");
    setError("");

    try {
      const fileToUpload =
        mode === "write"
          ? new File([draft], normalizeMarkdownFilename(filename, section), { type: "text/markdown" })
          : uploadedFile
            ? new File([uploadedFile], `${section.id}-${uploadedFile.name}`, {
                type: uploadedFile.type || "text/plain"
              })
            : null;

      if (!fileToUpload) {
        setError("Selecciona un archivo o escribe contenido antes de guardar");
        return;
      }

      if (mode === "write" && !draft.trim()) {
        setError("El texto no puede estar vacio");
        return;
      }

      const uploaded = await uploadAgentDocument(agentId, fileToUpload, session.accessToken, section.id);
      if (docsApiUnavailable) {
        const fallbackList = readFallbackDocuments(agentId);
        const fallbackDocumentId = uploaded.document_id || `${Date.now()}-${fileToUpload.name}`;
        const fallbackItem: AgentDocument = {
          document_id: fallbackDocumentId,
          agent_id: uploaded.agent_id || agentId,
          filename: uploaded.filename || fileToUpload.name,
          size_bytes: uploaded.size_bytes || fileToUpload.size,
          status: uploaded.status ?? "uploaded",
          indexed_at: uploaded.indexed_at ?? null,
          error_message: uploaded.error_message ?? null,
          created_at: uploaded.created_at ?? new Date().toISOString(),
          operational_section: section.id,
          learning_summary: uploaded.learning_summary ?? null,
          summary_updated_at: uploaded.summary_updated_at ?? null
        };
        const merged = [fallbackItem, ...fallbackList.filter((item) => item.document_id !== fallbackItem.document_id)];
        writeFallbackDocuments(agentId, merged);
      }

      if (rebuildNow) {
        const result = await rebuildAgentIndex(agentId, session.accessToken);
        setStatus(`Guardado y indexado con backend ${result.backend}.`);
      } else {
        setStatus("Guardado. Falta reconstruir indice para usar el contenido en RAG.");
      }

      const persistedFilename = mode === "write" ? normalizeMarkdownFilename(filename, section) : fileToUpload.name;
      setSectionDrafts((prev) => ({
        ...prev,
        [section.id]: {
          mode,
          draft,
          filename: persistedFilename,
          uploadedFile: null
        }
      }));
      if (mode === "upload") {
        setUploadedFile(null);
      }

      await loadState();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo guardar el contenido");
      }
    } finally {
      setSaving(false);
    }
  }

  async function onAnalyzeUrl() {
    if (!session) {
      setError("Tu sesion expiro. Inicia sesion nuevamente para analizar URLs.");
      return;
    }

    const targetUrl = analysisUrl.trim();
    if (!targetUrl) {
      setError("Ingresa una URL valida para analizar.");
      return;
    }

    setAnalyzingUrl(true);
    setError("");
    setStatus("");

    try {
      const analysis = await analyzeAgentWebUrl(
        agentId,
        {
          url: targetUrl,
          max_points: 6,
          max_chars: 15000
        },
        session.accessToken
      );

      setLastWebAnalysis(analysis);

      const keyPoints =
        analysis.key_points.length > 0
          ? analysis.key_points.map((point) => `- ${point}`).join("\n")
          : "- Sin puntos clave detectados.";
      const markdownSnippet = [
        "## Fuente web analizada",
        `- URL: ${analysis.url}`,
        `- Titulo: ${analysis.title}`,
        `- HTTP: ${analysis.status_code}`,
        `- Palabras relevadas: ${analysis.word_count}`,
        "",
        "### Puntos clave",
        keyPoints,
        "",
        "### Extracto",
        analysis.content_excerpt
      ].join("\n");

      setDraft((prev) => {
        const current = prev.trimEnd();
        if (!current) {
          return `${markdownSnippet}\n`;
        }
        return `${current}\n\n${markdownSnippet}\n`;
      });
      setStatus("URL analizada. Se agrego un bloque util al borrador actual.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo analizar la URL");
      }
    } finally {
      setAnalyzingUrl(false);
    }
  }

  if (loading) {
    return (
      <section className="stack" aria-label="Cargando editor de conocimiento">
        <ConsoleNav />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Editor de conocimiento">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / knowledge / compose</p>
        <h1>{agent?.name ?? "Agente"}</h1>
        <p className="muted">Completa el modulo operativo y guardalo para que el agente lo use en RAG.</p>
      </article>

      <div className="compose-grid">
        <article className="surface stack">
          <div className="knowledge-meter" aria-label="Progreso de bloques operativos">
            <div className="cluster between">
              <p className="mono muted">progreso: {completionPercent}%</p>
              <p className="mono muted">listos: {completedSections}/{OPERATIONAL_SECTIONS.length}</p>
            </div>
            <div className="knowledge-meter-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={completionPercent}>
              <span className="knowledge-meter-fill" style={{ width: `${completionPercent}%` }} />
            </div>
          </div>

          <div className="cluster between">
            <h2>{section.label}</h2>
            <span className={currentSectionState?.completed ? "knowledge-state done" : "knowledge-state pending"}>
              {currentSectionState?.completed ? "modulo listo" : "modulo pendiente"}
            </span>
          </div>
          <p className="muted">{section.description}</p>
          <p className="mono muted">company_id: {agent?.company_id ?? "sin company"}</p>

          <div className="compose-tabs" role="tablist" aria-label="Modo de ingreso">
            <button
              type="button"
              className={mode === "write" ? "compose-tab active" : "compose-tab"}
              onClick={() => setMode("write")}
            >
              Escribir texto
            </button>
            <button
              type="button"
              className={mode === "upload" ? "compose-tab active" : "compose-tab"}
              onClick={() => setMode("upload")}
            >
              Subir archivo
            </button>
          </div>

          {loadingPersistedContent ? (
            <p className="muted">Cargando ultima version guardada del modulo...</p>
          ) : null}

          {mode === "write" ? (
            <>
              <label>
                Nombre de archivo
                <input
                  type="text"
                  value={filename}
                  onChange={(event) => setFilename(event.target.value)}
                  placeholder={section.filenameHint}
                />
              </label>

              <label>
                Contenido
                <textarea
                  className="compose-textarea"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>

              {section.id === "contracts" ? (
                <div className="stack">
                  <label>
                    URL para analizar (fuente para contratos de accion)
                    <input
                      type="url"
                      value={analysisUrl}
                      onChange={(event) => setAnalysisUrl(event.target.value)}
                      placeholder="https://docs.empresa.com/api/orders"
                    />
                  </label>
                  <div className="cluster">
                    <button type="button" onClick={onAnalyzeUrl} disabled={analyzingUrl || !analysisUrl.trim()}>
                      {analyzingUrl ? "Analizando URL..." : "Analizar y agregar al borrador"}
                    </button>
                  </div>

                  {lastWebAnalysis ? (
                    <article className="knowledge-card stack compact">
                      <p className="mono muted">ultima URL analizada</p>
                      <p className="muted">
                        {lastWebAnalysis.title} (HTTP {lastWebAnalysis.status_code})
                      </p>
                      <p className="mono muted">{lastWebAnalysis.url}</p>
                    </article>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : (
            <>
              <div className="dropzone">
                <FileArrowUp size={22} weight="duotone" />
                <p>Selecciona un archivo para este modulo</p>
                <p className="muted mono">formatos permitidos: .txt .md .csv .json</p>
              </div>
              <input
                type="file"
                accept=".txt,.md,.csv,.json"
                onChange={(event) => setUploadedFile(event.target.files?.[0] ?? null)}
              />
              <p className="mono muted">archivo: {uploadedFile ? uploadedFile.name : "ninguno"}</p>
            </>
          )}

          <label className="toggle-label">
            Reconstruir indice al guardar
            <input type="checkbox" checked={rebuildNow} onChange={(event) => setRebuildNow(event.target.checked)} />
          </label>

          <div className="cluster">
            <button type="button" onClick={onSave} disabled={saving}>
              <FloppyDisk size={16} />
              {saving ? "Guardando..." : "Guardar para RAG"}
            </button>

            <Link href={`/agents/${agentId}/setup`} className="button-link ghost-link">
              Volver a setup
            </Link>

            {!rebuildNow ? (
              <Link href={`/agents/${agentId}/setup`} className="button-link ghost-link">
                <ArrowClockwise size={16} />
                Reconstruir luego
              </Link>
            ) : null}
          </div>

          {error ? <p className="error">{error}</p> : null}
          {status ? <p className="success">{status}</p> : null}
        </article>

        <article className="surface stack">
          <p className="mono muted">resumen rapido</p>
          <h2>Lo que el agente aprendio</h2>
          <p className="muted">
            Este bloque entrena como responder en escenarios reales del tenant y como justificar cada accion.
          </p>

          <div className="knowledge-card stack compact">
            <p className="mono muted">Resumen generico guardado</p>
            {selectedDocument?.learning_summary ? (
              <p className="muted">{selectedDocument.learning_summary}</p>
            ) : (
              <p className="muted">Subi o actualiza un documento del bloque para generar su aprendizaje en backend.</p>
            )}
          </div>
        </article>
      </div>

      {docsApiUnavailable ? <p className="muted">Estado de documentos en modo compatibilidad local.</p> : null}

    </section>
  );
}
