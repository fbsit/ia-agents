"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle, Circle, RocketLaunch } from "@phosphor-icons/react";

import { ConsoleNav } from "@/features/agents/console-nav";
import {
  createAgentRagDecision,
  exportAgentEvaluationRunsCsv,
  getAgentEvaluationCompareLatest,
  getAgentEvaluationDataset,
  getAgentEvaluationJobStatus,
  getAgentFeedbackSummary,
  getAgentRagDecisionHistory,
  getAgentRetrievalComparison,
  runAgentEvaluationAsync,
  saveAgentEvaluationDataset,
  getAgentSetupStatus,
  getRetrievalSummary,
  rebuildAgentIndex,
  updateAgent
} from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type {
  AgentFeedbackSummary,
  EvaluationCompare,
  EvaluationRunJob,
  EvaluationRun,
  RagDecisionRecord,
  AgentSetupStatus,
  RetrievalComparison,
  RetrievalSummaryRow
} from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";

type AgentSetupClientProps = {
  agentId: string;
};

export function AgentSetupClient({ agentId }: AgentSetupClientProps) {
  const { session } = useSession();
  const [selectedWindowDays, setSelectedWindowDays] = useState<7 | 30 | 90>(30);
  const [status, setStatus] = useState<AgentSetupStatus | null>(null);
  const [retrievalRow, setRetrievalRow] = useState<RetrievalSummaryRow | null>(null);
  const [retrievalComparison, setRetrievalComparison] = useState<RetrievalComparison | null>(null);
  const [feedbackSummary, setFeedbackSummary] = useState<AgentFeedbackSummary | null>(null);
  const [ragDecisionHistory, setRagDecisionHistory] = useState<RagDecisionRecord[]>([]);
  const [evaluationDatasetText, setEvaluationDatasetText] = useState("[]");
  const [evaluationCompare, setEvaluationCompare] = useState<EvaluationCompare | null>(null);
  const [lastEvaluationRun, setLastEvaluationRun] = useState<EvaluationRun | null>(null);
  const [evaluationJob, setEvaluationJob] = useState<EvaluationRunJob | null>(null);
  const [selectedRagBackend, setSelectedRagBackend] = useState<"auto" | "tfidf" | "dense_openai" | "hybrid">("auto");
  const [applyingBackend, setApplyingBackend] = useState(false);
  const [backendNotice, setBackendNotice] = useState("");
  const [savingDecision, setSavingDecision] = useState(false);
  const [savingDataset, setSavingDataset] = useState(false);
  const [runningEvaluation, setRunningEvaluation] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadSetupPanels = useCallback(async () => {
    if (!session) {
      return null;
    }

    const setup = await getAgentSetupStatus(agentId, session.accessToken);
    let retrieval: RetrievalSummaryRow[] = [];
    let feedback: AgentFeedbackSummary | null = null;
    let comparison: RetrievalComparison | null = null;
    let decisions: RagDecisionRecord[] = [];
    let evalDataset = [] as { question: string; expected_answer: string }[];
    let evalCompare: EvaluationCompare | null = null;

    try {
          retrieval = await getRetrievalSummary(session.accessToken, {
            company_id: setup.company_id,
            days: selectedWindowDays
          });
    } catch (retrievalErr) {
      if (!(retrievalErr instanceof ApiError && (retrievalErr.status === 404 || retrievalErr.status === 405))) {
        throw retrievalErr;
      }
    }

    try {
          feedback = await getAgentFeedbackSummary(agentId, session.accessToken, { days: selectedWindowDays });
    } catch (feedbackErr) {
      if (!(feedbackErr instanceof ApiError && (feedbackErr.status === 404 || feedbackErr.status === 405))) {
        throw feedbackErr;
      }
    }

    try {
          comparison = await getAgentRetrievalComparison(agentId, session.accessToken, { days: selectedWindowDays });
    } catch (comparisonErr) {
      if (!(comparisonErr instanceof ApiError && (comparisonErr.status === 404 || comparisonErr.status === 405))) {
        throw comparisonErr;
      }
    }

    try {
      decisions = await getAgentRagDecisionHistory(agentId, session.accessToken);
    } catch (decisionErr) {
      if (!(decisionErr instanceof ApiError && (decisionErr.status === 404 || decisionErr.status === 405))) {
        throw decisionErr;
      }
    }

    try {
      const datasetPayload = await getAgentEvaluationDataset(agentId, session.accessToken);
      evalDataset = datasetPayload.cases;
    } catch (datasetErr) {
      if (!(datasetErr instanceof ApiError && (datasetErr.status === 404 || datasetErr.status === 405))) {
        throw datasetErr;
      }
    }

    try {
      evalCompare = await getAgentEvaluationCompareLatest(agentId, session.accessToken);
    } catch (evalErr) {
      if (!(evalErr instanceof ApiError && (evalErr.status === 404 || evalErr.status === 405))) {
        throw evalErr;
      }
    }

    return {
      setup,
      retrieval,
      feedback,
      comparison,
      decisions,
      evalDataset,
      evalCompare
    };
  }, [agentId, selectedWindowDays, session]);

  useEffect(() => {
    let mounted = true;

    async function loadStatus() {
      if (!session) {
        return;
      }

      setError("");
      try {
        const result = await loadSetupPanels();
        if (!result) {
          return;
        }
        if (!mounted) {
          return;
        }
        setStatus(result.setup);
        setSelectedRagBackend(result.setup.rag_backend);
        setRetrievalRow(result.retrieval.find((row) => row.agent_id === agentId) ?? null);
        setFeedbackSummary(result.feedback);
        setRetrievalComparison(result.comparison);
        setRagDecisionHistory(result.decisions);
        setEvaluationDatasetText(JSON.stringify(result.evalDataset, null, 2));
        setEvaluationCompare(result.evalCompare);
        setLastEvaluationRun(result.evalCompare?.current ?? null);
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el setup del agente");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void loadStatus();
    return () => {
      mounted = false;
    };
  }, [agentId, loadSetupPanels, session]);

  async function handleApplyRagBackend(
    rebuildNow: boolean,
    backendOverride?: "auto" | "tfidf" | "dense_openai" | "hybrid"
  ) {
    if (!session || !status) {
      return;
    }

    setApplyingBackend(true);
    setError("");
    setBackendNotice("");

    const backendToApply = backendOverride ?? selectedRagBackend;

    try {
      await updateAgent(
        status.agent_id,
        {
          rag_backend: backendToApply
        },
        session.accessToken
      );

      if (rebuildNow) {
        await rebuildAgentIndex(status.agent_id, session.accessToken);
      }

      const result = await loadSetupPanels();
      if (result) {
        setStatus(result.setup);
        setSelectedRagBackend(result.setup.rag_backend);
        setRetrievalRow(result.retrieval.find((row) => row.agent_id === agentId) ?? null);
        setFeedbackSummary(result.feedback);
        setRetrievalComparison(result.comparison);
        setRagDecisionHistory(result.decisions);
        setEvaluationDatasetText(JSON.stringify(result.evalDataset, null, 2));
        setEvaluationCompare(result.evalCompare);
        setLastEvaluationRun(result.evalCompare?.current ?? null);
      }

      setBackendNotice(
        rebuildNow
          ? `Backend ${backendToApply} aplicado y reindexacion completada.`
          : `Backend ${backendToApply} aplicado. Ejecuta rebuild para medir impacto.`
      );
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo aplicar backend RAG");
      }
    } finally {
      setApplyingBackend(false);
    }
  }

  async function handleSaveRecommendation() {
    if (!session || !status || !retrievalComparison) {
      return;
    }
    if (evaluationGate.blocked) {
      setError("Gate de evaluacion offline bloquea guardar recomendacion.");
      return;
    }

    setSavingDecision(true);
    setError("");

    try {
      const recommendation = backendRecommendation.label;
      const reason = `[ventana ${selectedWindowDays}d] ${backendRecommendation.detail} ${comparisonInsight}`.trim();
      await createAgentRagDecision(
        status.agent_id,
        {
          decision: recommendation,
          current_backend: retrievalComparison.current_backend,
          baseline_backend: retrievalComparison.baseline_backend,
          reason,
          grounded_rate_delta: retrievalComparison.grounded_rate_delta,
          fallback_rate_delta: retrievalComparison.fallback_rate_delta,
          score_delta: retrievalComparison.score_delta,
          latency_delta_ms: retrievalComparison.latency_delta_ms
        },
        session.accessToken
      );

      const history = await getAgentRagDecisionHistory(status.agent_id, session.accessToken);
      setRagDecisionHistory(history);
      setBackendNotice("Recomendacion guardada en historial.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo guardar recomendacion");
      }
    } finally {
      setSavingDecision(false);
    }
  }

  async function handleSaveEvaluationDataset() {
    if (!session || !status) {
      return;
    }

    setSavingDataset(true);
    setError("");

    try {
      const parsed = JSON.parse(evaluationDatasetText) as Array<{ question: string; expected_answer: string }>;
      const payload = {
        cases: Array.isArray(parsed) ? parsed : []
      };
      const saved = await saveAgentEvaluationDataset(status.agent_id, payload, session.accessToken);
      setEvaluationDatasetText(JSON.stringify(saved.cases, null, 2));
      setBackendNotice("Dataset de evaluacion guardado.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Dataset invalido. Usa JSON array con question y expected_answer.");
      }
    } finally {
      setSavingDataset(false);
    }
  }

  async function handleRunEvaluation() {
    if (!session || !status) {
      return;
    }

    setRunningEvaluation(true);
    setError("");

    try {
      const job = await runAgentEvaluationAsync(
        status.agent_id,
        {
          sample_size: 30
        },
        session.accessToken
      );
      setEvaluationJob(job);

      let latestJob = job;
      for (let attempt = 0; attempt < 90; attempt += 1) {
        if (latestJob.status === "succeeded" || latestJob.status === "failed") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
        latestJob = await getAgentEvaluationJobStatus(status.agent_id, job.job_id, session.accessToken);
        setEvaluationJob(latestJob);
      }

      if (latestJob.status === "failed") {
        throw new ApiError(400, latestJob.error || "La evaluacion offline fallo");
      }

      if (latestJob.run) {
        setLastEvaluationRun(latestJob.run);
      }

      const compare = await getAgentEvaluationCompareLatest(status.agent_id, session.accessToken);
      setEvaluationCompare(compare);
      setBackendNotice("Evaluacion offline completada.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo ejecutar evaluacion offline");
      }
    } finally {
      setRunningEvaluation(false);
    }
  }

  async function handleExportEvaluationCsv() {
    if (!session || !status) {
      return;
    }

    setExportingCsv(true);
    setError("");

    try {
      const csv = await exportAgentEvaluationRunsCsv(status.agent_id, session.accessToken, { limit: 200 });
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `agent-${status.agent_id}-evaluation-runs.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setBackendNotice("CSV de evaluacion exportado.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo exportar CSV de evaluacion");
      }
    } finally {
      setExportingCsv(false);
    }
  }

  const completedSteps = useMemo(() => {
    return status?.steps.filter((step) => step.ready).length ?? 0;
  }, [status]);

  const retrievalHealth = useMemo(() => {
    if (!retrievalRow || retrievalRow.queries_total === 0) {
      return {
        label: "Sin datos",
        cssClass: "uploaded",
        detail: "Aun no hay consultas suficientes para medir calidad de retrieval."
      };
    }

    const groundedRate = retrievalRow.answers_with_sources / Math.max(retrievalRow.queries_total, 1);
    const fallbackRate = retrievalRow.fallback_count / Math.max(retrievalRow.queries_total, 1);

    if (groundedRate >= 0.7 && fallbackRate <= 0.2) {
      return {
        label: "Salud alta",
        cssClass: "indexed",
        detail: "El agente responde con evidencia y bajo fallback."
      };
    }

    if (groundedRate >= 0.45 && fallbackRate <= 0.35) {
      return {
        label: "Salud media",
        cssClass: "uploaded",
        detail: "Recupera evidencia parcialmente; conviene fortalecer conocimiento y pruebas."
      };
    }

    return {
      label: "Salud baja",
      cssClass: "failed",
      detail: "Hay poca evidencia util o demasiado fallback; revisa documentos y bloques operativos."
    };
  }, [retrievalRow]);

  const comparisonInsight = useMemo(() => {
    if (!retrievalComparison?.baseline) {
      return "Sin baseline historico: aun no hay datos de otro backend para comparar.";
    }

    const groundedDelta = retrievalComparison.grounded_rate_delta ?? 0;
    const fallbackDelta = retrievalComparison.fallback_rate_delta ?? 0;
    const scoreDelta = retrievalComparison.score_delta ?? 0;

    if (groundedDelta >= 0.05 && fallbackDelta <= -0.03 && scoreDelta >= 0) {
      return "Mejora clara: subio evidencia y bajo fallback frente al backend anterior.";
    }
    if (groundedDelta <= -0.05 || fallbackDelta >= 0.05) {
      return "Empeora vs baseline: revisa chunking, documentos y configuracion del backend actual.";
    }
    return "Cambio neutro: la diferencia frente al backend anterior aun es marginal.";
  }, [retrievalComparison]);

  const backendRecommendation = useMemo(() => {
    if (!retrievalComparison?.baseline || !retrievalComparison.current || !retrievalComparison.baseline) {
      return {
        label: "Sin recomendacion",
        cssClass: "uploaded",
        detail: "Aun no hay baseline para recomendar un backend con confianza."
      };
    }

    const minSampleSize = 30;
    if (
      retrievalComparison.current.queries_total < minSampleSize ||
      retrievalComparison.baseline.queries_total < minSampleSize
    ) {
      return {
        label: "Muestra insuficiente",
        cssClass: "uploaded",
        detail: `Necesitas al menos ${minSampleSize} consultas por backend para recomendar con confianza.`
      };
    }

    const groundedDelta = retrievalComparison.grounded_rate_delta ?? 0;
    const fallbackDelta = retrievalComparison.fallback_rate_delta ?? 0;
    const scoreDelta = retrievalComparison.score_delta ?? 0;
    const latencyDelta = retrievalComparison.latency_delta_ms ?? 0;

    const clearlyBetter = groundedDelta >= 0.05 && fallbackDelta <= -0.03 && scoreDelta >= 0;
    const clearlyWorse = groundedDelta <= -0.05 || fallbackDelta >= 0.05 || scoreDelta <= -0.03;

    if (clearlyBetter) {
      return {
        label: `Recomendado: ${retrievalComparison.current_backend}`,
        cssClass: "indexed",
        detail: "Mejora groundedness y reduce fallback frente al backend baseline."
      };
    }

    if (clearlyWorse) {
      return {
        label: `Volver a ${retrievalComparison.baseline.backend}`,
        cssClass: "failed",
        detail: "El backend actual empeora calidad; conviene rollback y revisar indexado/chunking."
      };
    }

    if (latencyDelta > 180 && groundedDelta < 0.03) {
      return {
        label: "Costo alto, mejora baja",
        cssClass: "uploaded",
        detail: "La latencia subio fuerte sin ganancia clara; mantener baseline hasta optimizar."
      };
    }

    return {
      label: "Mantener y medir",
      cssClass: "uploaded",
      detail: "El cambio es marginal; junta mas trafico antes de decidir migracion definitiva."
    };
  }, [retrievalComparison]);

  const evaluationGate = useMemo(() => {
    const current = evaluationCompare?.current;
    if (!current) {
      return {
        blocked: true,
        cssClass: "uploaded",
        label: "Gate sin corrida",
        detail: "Corre evaluacion offline antes de guardar recomendacion de backend."
      };
    }

    if (current.cases_total < 30) {
      return {
        blocked: true,
        cssClass: "uploaded",
        label: "Gate muestra baja",
        detail: "Necesitas al menos 30 casos en la corrida offline para habilitar recomendacion."
      };
    }

    const semanticAvailable = current.llm_judge_enabled && current.llm_judge_scored_cases > 0;
    const semanticAccuracy = semanticAvailable ? current.semantic_accuracy ?? 0 : null;
    const semanticWeak = semanticAvailable && semanticAccuracy !== null && semanticAccuracy < 0.55;

    if (current.accuracy < 0.55 || current.grounded_rate < 0.55 || current.fallback_rate > 0.45 || semanticWeak) {
      return {
        blocked: true,
        cssClass: "failed",
        label: "Gate bloqueado",
        detail: semanticWeak
          ? "La calidad semantica del judge es baja; no guardar recomendacion todavia."
          : "La corrida actual no cumple umbrales minimos de calidad offline."
      };
    }

    return {
      blocked: false,
      cssClass: "indexed",
      label: "Gate aprobado",
      detail: "Calidad offline suficiente para guardar recomendacion con confianza."
    };
  }, [evaluationCompare]);

  if (loading) {
    return (
      <section className="stack" aria-label="Cargando setup del agente">
        <ConsoleNav />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Setup del agente">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / setup</p>
        <h1>{status?.agent_name ?? "Setup del agente"}</h1>
        <p className="muted">Configuracion guiada para publicar rapido sin friccion tecnica.</p>

        <label>
          Ventana de analisis
          <select
            value={selectedWindowDays}
            onChange={(event) => setSelectedWindowDays(Number(event.target.value) as 7 | 30 | 90)}
          >
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
        </label>

        <div className="knowledge-meter" aria-label="Progreso de setup">
          <div className="cluster between">
            <p className="mono muted">progreso: {status?.progress_percent ?? 0}%</p>
            <p className="mono muted">pasos listos: {completedSteps}/{status?.steps.length ?? 4}</p>
          </div>
          <div className="knowledge-meter-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={status?.progress_percent ?? 0}>
            <span className="knowledge-meter-fill" style={{ width: `${status?.progress_percent ?? 0}%` }} />
          </div>
        </div>

        {status?.ready_to_publish ? (
          <div className="cluster">
            <span className="status-pill indexed">Listo para publicar</span>
            <Link href={`/agents/${agentId}/deploy`} className="button-link ghost-link">
              <RocketLaunch size={16} weight="duotone" />
              Ir a desplegar
            </Link>
          </div>
        ) : (
          <div className="cluster">
            <span className="status-pill uploaded">Faltan pasos de setup</span>
            {status?.next_href ? (
              <Link href={status.next_href} className="button-link ghost-link">
                Continuar setup
                <ArrowRight size={16} />
              </Link>
            ) : null}
          </div>
        )}
      </article>

      <article className="surface stack">
        <h2>Pasos guiados</h2>
        <div className="stack compact">
          {status?.steps.map((step) => (
            <article key={step.id} className="source-row cluster between">
              <div className="stack compact">
                <div className="cluster">
                  {step.ready ? <CheckCircle size={18} weight="duotone" /> : <Circle size={18} />}
                  <strong>{step.label}</strong>
                </div>
                <p className="muted">{step.description}</p>
              </div>
              <Link href={step.href} className="button-link ghost-link">
                Abrir
              </Link>
            </article>
          ))}
        </div>
      </article>

      <article className="surface stack">
        <h2>Estado operativo</h2>
        <p className="mono muted">documentos: {status?.documents_total ?? 0}</p>
        <p className="mono muted">documentos indexados: {status?.documents_indexed ?? 0}</p>
        <p className="mono muted">mensajes de prueba: {status?.test_messages ?? 0}</p>
      </article>

      <article className="surface stack">
        <h2>Backend RAG</h2>
        <label>
          Estrategia de retrieval
          <select value={selectedRagBackend} onChange={(event) => setSelectedRagBackend(event.target.value as "auto" | "tfidf" | "dense_openai" | "hybrid")}>
            <option value="auto">auto</option>
            <option value="tfidf">tfidf</option>
            <option value="dense_openai">dense_openai</option>
            <option value="hybrid">hybrid</option>
          </select>
        </label>
        <div className="cluster">
          <button type="button" onClick={() => void handleApplyRagBackend(false)} disabled={applyingBackend}>
            {applyingBackend ? "Aplicando..." : "Aplicar backend"}
          </button>
          <button
            type="button"
            className="button-link ghost-link"
            onClick={() => void handleApplyRagBackend(true)}
            disabled={applyingBackend}
          >
            {applyingBackend ? "Procesando..." : "Aplicar + Rebuild + Medir"}
          </button>
          {retrievalComparison?.baseline_backend ? (
            <button
              type="button"
              className="button-link ghost-link"
              onClick={() =>
                void handleApplyRagBackend(
                  true,
                  retrievalComparison.baseline_backend as "auto" | "tfidf" | "dense_openai" | "hybrid"
                )
              }
              disabled={applyingBackend}
            >
              Volver a baseline + Rebuild
            </button>
          ) : null}
        </div>
        {backendNotice ? <p className="muted">{backendNotice}</p> : null}
      </article>

      <article className="surface stack">
        <h2>Calidad de retrieval ({selectedWindowDays} dias)</h2>
        <div className="cluster">
          <span className={`status-pill ${retrievalHealth.cssClass}`}>{retrievalHealth.label}</span>
          <p className="muted">{retrievalHealth.detail}</p>
        </div>

        <p className="mono muted">consultas medidas: {retrievalRow?.queries_total ?? 0}</p>
        <p className="mono muted">respuestas con evidencia: {retrievalRow?.answers_with_sources ?? 0}</p>
        <p className="mono muted">fallbacks: {retrievalRow?.fallback_count ?? 0}</p>
        <p className="mono muted">chunks promedio: {retrievalRow?.avg_retrieved_chunks ?? 0}</p>
        <p className="mono muted">score promedio: {retrievalRow?.avg_retrieval_score ?? 0}</p>
        <p className="mono muted">latencia promedio: {retrievalRow?.avg_latency_ms ?? 0}ms</p>
      </article>

      <article className="surface stack">
        <h2>Comparacion de backend RAG</h2>
        <div className="cluster">
          <span className={`status-pill ${backendRecommendation.cssClass}`}>{backendRecommendation.label}</span>
          <p className="muted">{backendRecommendation.detail}</p>
        </div>
        <div className="cluster">
          <span className={`status-pill ${evaluationGate.cssClass}`}>{evaluationGate.label}</span>
          <p className="muted">{evaluationGate.detail}</p>
        </div>
        <p className="mono muted">backend actual: {retrievalComparison?.current_backend ?? "n/d"}</p>
        <p className="mono muted">baseline: {retrievalComparison?.baseline_backend ?? "sin baseline"}</p>
        <p className="mono muted">
          delta groundedness: {retrievalComparison?.grounded_rate_delta !== null && retrievalComparison?.grounded_rate_delta !== undefined
            ? `${(retrievalComparison.grounded_rate_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">
          delta fallback: {retrievalComparison?.fallback_rate_delta !== null && retrievalComparison?.fallback_rate_delta !== undefined
            ? `${(retrievalComparison.fallback_rate_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">
          delta score: {retrievalComparison?.score_delta !== null && retrievalComparison?.score_delta !== undefined
            ? retrievalComparison.score_delta.toFixed(4)
            : "n/d"}
        </p>
        <p className="mono muted">
          delta latencia: {retrievalComparison?.latency_delta_ms !== null && retrievalComparison?.latency_delta_ms !== undefined
            ? `${retrievalComparison.latency_delta_ms.toFixed(2)}ms`
            : "n/d"}
        </p>
        <p className="muted">{comparisonInsight}</p>
        <div className="cluster">
          <button
            type="button"
            onClick={() => void handleSaveRecommendation()}
            disabled={savingDecision || !retrievalComparison || evaluationGate.blocked}
          >
            {savingDecision ? "Guardando..." : "Guardar recomendacion"}
          </button>
        </div>

        {ragDecisionHistory.length ? (
          <div className="stack compact">
            <p className="mono muted">Historial de decisiones</p>
            {ragDecisionHistory.slice().reverse().slice(0, 5).map((row) => (
              <article key={`${row.recorded_at}-${row.decision}`} className="source-row stack compact">
                <p className="mono muted">{new Date(row.recorded_at).toLocaleString("es-CL")}</p>
                <strong>{row.decision}</strong>
                <p className="muted">{row.reason}</p>
              </article>
            ))}
          </div>
        ) : null}
      </article>

      <article className="surface stack">
        <h2>Feedback de usuarios ({selectedWindowDays} dias)</h2>
        <p className="mono muted">total feedback: {feedbackSummary?.feedback_total ?? 0}</p>
        <p className="mono muted">thumbs up: {feedbackSummary?.thumbs_up ?? 0}</p>
        <p className="mono muted">thumbs down: {feedbackSummary?.thumbs_down ?? 0}</p>
        <p className="mono muted">tasa positiva: {Math.round((feedbackSummary?.positive_rate ?? 0) * 100)}%</p>
        <p className="mono muted">con comentario: {feedbackSummary?.with_comment ?? 0}</p>
        <p className="mono muted">con respuesta esperada: {feedbackSummary?.with_expected_answer ?? 0}</p>
      </article>

      <article className="surface stack">
        <h2>Evaluacion offline</h2>
        <p className="muted">Carga un dataset reproducible para medir calidad y comparar corridas entre backends.</p>

        <label>
          Dataset JSON (array con question y expected_answer)
          <textarea
            rows={10}
            className="mono"
            value={evaluationDatasetText}
            onChange={(event) => setEvaluationDatasetText(event.target.value)}
          />
        </label>

        <div className="cluster">
          <button type="button" onClick={() => void handleSaveEvaluationDataset()} disabled={savingDataset}>
            {savingDataset ? "Guardando..." : "Guardar dataset"}
          </button>
          <button type="button" className="button-link ghost-link" onClick={() => void handleRunEvaluation()} disabled={runningEvaluation}>
            {runningEvaluation ? "Evaluando..." : "Correr evaluacion (30 casos)"}
          </button>
          <button type="button" className="button-link ghost-link" onClick={() => void handleExportEvaluationCsv()} disabled={exportingCsv}>
            {exportingCsv ? "Exportando..." : "Exportar corridas CSV"}
          </button>
        </div>

        <p className="mono muted">ultimo run: {lastEvaluationRun?.run_id ?? "sin corridas"}</p>
        <p className="mono muted">job actual: {evaluationJob ? `${evaluationJob.job_id} (${evaluationJob.status})` : "sin job"}</p>
        <p className="mono muted">backend: {lastEvaluationRun?.rag_backend ?? "n/d"}</p>
        <p className="mono muted">accuracy: {lastEvaluationRun ? `${(lastEvaluationRun.accuracy * 100).toFixed(1)}%` : "n/d"}</p>
        <p className="mono muted">
          semantic accuracy: {lastEvaluationRun?.semantic_accuracy !== null && lastEvaluationRun?.semantic_accuracy !== undefined
            ? `${(lastEvaluationRun.semantic_accuracy * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">groundedness: {lastEvaluationRun ? `${(lastEvaluationRun.grounded_rate * 100).toFixed(1)}%` : "n/d"}</p>
        <p className="mono muted">fallback: {lastEvaluationRun ? `${(lastEvaluationRun.fallback_rate * 100).toFixed(1)}%` : "n/d"}</p>
        <p className="mono muted">
          judge: {lastEvaluationRun?.llm_judge_enabled ? `activo (${lastEvaluationRun.llm_judge_scored_cases} casos)` : "desactivado"}
        </p>
        <p className="mono muted">latencia promedio: {lastEvaluationRun?.avg_latency_ms ?? "n/d"}ms</p>

        <p className="mono muted">
          delta accuracy: {evaluationCompare?.accuracy_delta !== null && evaluationCompare?.accuracy_delta !== undefined
            ? `${(evaluationCompare.accuracy_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">
          delta semantic accuracy: {evaluationCompare?.semantic_accuracy_delta !== null && evaluationCompare?.semantic_accuracy_delta !== undefined
            ? `${(evaluationCompare.semantic_accuracy_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">
          delta groundedness: {evaluationCompare?.grounded_rate_delta !== null && evaluationCompare?.grounded_rate_delta !== undefined
            ? `${(evaluationCompare.grounded_rate_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
        <p className="mono muted">
          delta semantic score: {evaluationCompare?.semantic_score_avg_delta !== null && evaluationCompare?.semantic_score_avg_delta !== undefined
            ? evaluationCompare.semantic_score_avg_delta.toFixed(4)
            : "n/d"}
        </p>
        <p className="mono muted">
          delta fallback: {evaluationCompare?.fallback_rate_delta !== null && evaluationCompare?.fallback_rate_delta !== undefined
            ? `${(evaluationCompare.fallback_rate_delta * 100).toFixed(1)}%`
            : "n/d"}
        </p>
      </article>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
