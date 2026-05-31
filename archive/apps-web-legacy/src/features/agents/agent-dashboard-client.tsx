"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ConsoleNav } from "@/features/agents/console-nav";
import {
  getAgentEvaluationCompareLatest,
  getAgentFeedbackSummary,
  getAgentRetrievalComparison,
  getAgentRagDecisionHistory,
  getAgentSetupStatus,
  getRetrievalSummary
} from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type {
  AgentFeedbackSummary,
  AgentSetupStatus,
  EvaluationCompare,
  RagDecisionRecord,
  RetrievalComparison,
  RetrievalSummaryRow
} from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";

type AgentDashboardClientProps = {
  agentId: string;
};

export function AgentDashboardClient({ agentId }: AgentDashboardClientProps) {
  const { session } = useSession();
  const [selectedWindowDays, setSelectedWindowDays] = useState<7 | 30 | 90>(30);
  const [setupStatus, setSetupStatus] = useState<AgentSetupStatus | null>(null);
  const [retrievalRow, setRetrievalRow] = useState<RetrievalSummaryRow | null>(null);
  const [retrievalComparison, setRetrievalComparison] = useState<RetrievalComparison | null>(null);
  const [feedbackSummary, setFeedbackSummary] = useState<AgentFeedbackSummary | null>(null);
  const [evaluationCompare, setEvaluationCompare] = useState<EvaluationCompare | null>(null);
  const [ragDecisionHistory, setRagDecisionHistory] = useState<RagDecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadDashboard() {
      if (!session) {
        return;
      }

      setError("");
      try {
        const setup = await getAgentSetupStatus(agentId, session.accessToken);
        let retrieval: RetrievalSummaryRow[] = [];
        let comparison: RetrievalComparison | null = null;
        let feedback: AgentFeedbackSummary | null = null;
        let evalCompare: EvaluationCompare | null = null;
        let decisions: RagDecisionRecord[] = [];

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
          comparison = await getAgentRetrievalComparison(agentId, session.accessToken, { days: selectedWindowDays });
        } catch (comparisonErr) {
          if (!(comparisonErr instanceof ApiError && (comparisonErr.status === 404 || comparisonErr.status === 405))) {
            throw comparisonErr;
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
          evalCompare = await getAgentEvaluationCompareLatest(agentId, session.accessToken);
        } catch (evalErr) {
          if (!(evalErr instanceof ApiError && (evalErr.status === 404 || evalErr.status === 405))) {
            throw evalErr;
          }
        }

        try {
          decisions = await getAgentRagDecisionHistory(agentId, session.accessToken);
        } catch (decisionErr) {
          if (!(decisionErr instanceof ApiError && (decisionErr.status === 404 || decisionErr.status === 405))) {
            throw decisionErr;
          }
        }

        if (!mounted) {
          return;
        }

        setSetupStatus(setup);
        setRetrievalRow(retrieval.find((row) => row.agent_id === agentId) ?? null);
        setRetrievalComparison(comparison);
        setFeedbackSummary(feedback);
        setEvaluationCompare(evalCompare);
        setRagDecisionHistory(decisions);
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el dashboard del agente");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void loadDashboard();
    return () => {
      mounted = false;
    };
  }, [agentId, selectedWindowDays, session]);

  const retrievalHealth = useMemo(() => {
    if (!retrievalRow || retrievalRow.queries_total === 0) {
      return { label: "Sin datos", cssClass: "uploaded" };
    }
    const groundedRate = retrievalRow.answers_with_sources / Math.max(retrievalRow.queries_total, 1);
    const fallbackRate = retrievalRow.fallback_count / Math.max(retrievalRow.queries_total, 1);
    if (groundedRate >= 0.7 && fallbackRate <= 0.2) {
      return { label: "Salud alta", cssClass: "indexed" };
    }
    if (groundedRate >= 0.45 && fallbackRate <= 0.35) {
      return { label: "Salud media", cssClass: "uploaded" };
    }
    return { label: "Salud baja", cssClass: "failed" };
  }, [retrievalRow]);

  const chartMetrics = useMemo(() => {
    const groundedness = retrievalRow && retrievalRow.queries_total > 0
      ? (retrievalRow.answers_with_sources / Math.max(retrievalRow.queries_total, 1)) * 100
      : 0;
    const positiveFeedback = Math.max(0, Math.min(100, (feedbackSummary?.positive_rate ?? 0) * 100));
    const evalAccuracy = Math.max(0, Math.min(100, (evaluationCompare?.current?.accuracy ?? 0) * 100));
    const semanticAccuracy = Math.max(0, Math.min(100, (evaluationCompare?.current?.semantic_accuracy ?? 0) * 100));

    return [
      { id: "groundedness", label: "Groundedness", value: groundedness },
      { id: "feedback", label: "Feedback +", value: positiveFeedback },
      { id: "accuracy", label: "Eval accuracy", value: evalAccuracy },
      { id: "semantic", label: "Eval semantica", value: semanticAccuracy }
    ];
  }, [evaluationCompare, feedbackSummary, retrievalRow]);

  if (loading) {
    return (
      <section className="stack" aria-label="Cargando dashboard del agente">
        <ConsoleNav />
        <div className="surface skeleton-block" />
      </section>
    );
  }

  return (
    <section className="stack console-screen" aria-label="Dashboard del agente">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / dashboard</p>
        <h1>{setupStatus?.agent_name ?? "Dashboard del agente"}</h1>
        <p className="muted">Vista ejecutiva de calidad, retrieval, feedback y evaluacion del agente.</p>

        <label>
          Ventana de analisis
          <select value={selectedWindowDays} onChange={(event) => setSelectedWindowDays(Number(event.target.value) as 7 | 30 | 90)}>
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
        </label>
      </article>

      <div className="agent-metrics-grid">
        <article className="surface stack">
          <h2>Estado operativo</h2>
          <p className="mono muted">backend: {setupStatus?.rag_backend ?? "n/d"}</p>
          <p className="mono muted">documentos: {setupStatus?.documents_total ?? 0}</p>
          <p className="mono muted">documentos indexados: {setupStatus?.documents_indexed ?? 0}</p>
          <p className="mono muted">mensajes de prueba: {setupStatus?.test_messages ?? 0}</p>
        </article>

        <article className="surface stack">
          <h2>Calidad de retrieval</h2>
          <span className={`status-pill ${retrievalHealth.cssClass}`}>{retrievalHealth.label}</span>
          <p className="mono muted">consultas medidas: {retrievalRow?.queries_total ?? 0}</p>
          <p className="mono muted">respuestas con evidencia: {retrievalRow?.answers_with_sources ?? 0}</p>
          <p className="mono muted">fallbacks: {retrievalRow?.fallback_count ?? 0}</p>
          <p className="mono muted">score promedio: {retrievalRow?.avg_retrieval_score ?? 0}</p>
          <p className="mono muted">latencia promedio: {retrievalRow?.avg_latency_ms ?? 0}ms</p>
        </article>

        <article className="surface stack">
          <h2>Comparacion de backend</h2>
          <p className="mono muted">actual: {retrievalComparison?.current_backend ?? "n/d"}</p>
          <p className="mono muted">baseline: {retrievalComparison?.baseline_backend ?? "sin baseline"}</p>
          <p className="mono muted">delta groundedness: {retrievalComparison?.grounded_rate_delta ?? "n/d"}</p>
          <p className="mono muted">delta fallback: {retrievalComparison?.fallback_rate_delta ?? "n/d"}</p>
          <p className="mono muted">delta score: {retrievalComparison?.score_delta ?? "n/d"}</p>
          <p className="mono muted">delta latencia: {retrievalComparison?.latency_delta_ms ?? "n/d"}ms</p>
          <Link href={`/agents/${agentId}/setup`} className="button-link ghost-link">
            Ir a Setup para aplicar cambios
          </Link>
        </article>

        <article className="surface stack">
          <h2>Scoreboard visual</h2>
          <div className="metric-bars">
            {chartMetrics.map((item) => (
              <div key={item.id} className="metric-bar-row">
                <div className="cluster between">
                  <span className="mono muted">{item.label}</span>
                  <span className="mono muted">{item.value.toFixed(1)}%</span>
                </div>
                <div className="metric-bar-track">
                  <span className="metric-bar-fill" style={{ width: `${item.value}%` }} />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="surface stack">
          <h2>Feedback usuarios ({selectedWindowDays} dias)</h2>
          <p className="mono muted">total feedback: {feedbackSummary?.feedback_total ?? 0}</p>
          <p className="mono muted">thumbs up: {feedbackSummary?.thumbs_up ?? 0}</p>
          <p className="mono muted">thumbs down: {feedbackSummary?.thumbs_down ?? 0}</p>
          <p className="mono muted">tasa positiva: {Math.round((feedbackSummary?.positive_rate ?? 0) * 100)}%</p>
        </article>

        <article className="surface stack">
          <h2>Evaluacion offline</h2>
          <p className="mono muted">run actual: {evaluationCompare?.current?.run_id ?? "n/d"}</p>
          <p className="mono muted">accuracy: {evaluationCompare?.current ? `${(evaluationCompare.current.accuracy * 100).toFixed(1)}%` : "n/d"}</p>
          <p className="mono muted">groundedness: {evaluationCompare?.current ? `${(evaluationCompare.current.grounded_rate * 100).toFixed(1)}%` : "n/d"}</p>
          <p className="mono muted">delta accuracy: {evaluationCompare?.accuracy_delta ?? "n/d"}</p>
          <p className="mono muted">delta semantic accuracy: {evaluationCompare?.semantic_accuracy_delta ?? "n/d"}</p>
        </article>

        <article className="surface stack">
          <h2>Historial de decisiones RAG</h2>
          {ragDecisionHistory.length ? (
            <div className="stack compact">
              {ragDecisionHistory.slice().reverse().slice(0, 4).map((row) => (
                <article key={`${row.recorded_at}-${row.decision}`} className="source-row stack compact">
                  <p className="mono muted">{new Date(row.recorded_at).toLocaleString("es-CL")}</p>
                  <strong>{row.decision}</strong>
                  <p className="muted">{row.reason}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted">Sin decisiones registradas aun.</p>
          )}
        </article>
      </div>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
