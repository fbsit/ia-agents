"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChatsCircle, ThumbsDown, ThumbsUp } from "@phosphor-icons/react";

import { chatWithAgent, createAgentFeedback, listAgents } from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import { getTenantLlmSettings } from "@/shared/api/settings";
import type { Agent } from "@/shared/api/types";
import {
  ensureModelInOptions,
  getModelOptions,
  isProviderEnabled,
  normalizeProvider,
  pickDefaultProvider
} from "@/shared/llm/catalog";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";

type PlaygroundChatClientProps = {
  agentId: string;
};

type ChatEntry = {
  role: "user" | "assistant";
  content: string;
  rawAnswer?: string;
  question?: string;
  sources?: string[];
  feedbackStatus?: "idle" | "sending" | "sent_up" | "sent_down" | "error";
};

function tuneAssistantAnswer(text: string): string {
  const normalized = (text || "").replace(/\r\n/g, "\n");
  if (!normalized.trim()) {
    return "";
  }

  const inlineSplit = normalized.replace(/(?<=\S)\s+\d+\)\s*/g, "\n");
  const rawLines = inlineSplit.split("\n");

  const cleaned: string[] = [];
  for (const rawLine of rawLines) {
    let line = rawLine.trim();
    if (!line) {
      continue;
    }

    line = line.replace(/^\d+\)\s*/, "").trim();
    if (!line) {
      continue;
    }

    if (/^(referencias?( usadas)?|fuentes)\s*[:：-]/i.test(line)) {
      continue;
    }

    if (/^(respuesta breve|que aprendemos|aprendizajes clave|referencias usadas)\s*:?$/i.test(line)) {
      continue;
    }

    line = line.replace(/\b(referencias?( usadas)?|fuentes)\s*[:：-].*$/i, "").trim();
    if (!line) {
      continue;
    }

    const segments = line.split(/\s+-\s+/g).map((segment) => segment.trim().replace(/^[-\s]+/, "")).filter(Boolean);
    if (!segments.length) {
      continue;
    }

    cleaned.push(...segments);
  }

  const deduped = cleaned.filter((line, index) => cleaned.findIndex((item) => item.toLowerCase() === line.toLowerCase()) === index);
  if (!deduped.length) {
    return normalized.trim();
  }
  return deduped.join(" ");
}

export function PlaygroundChatClient({ agentId }: PlaygroundChatClientProps) {
  const { session } = useSession();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [message, setMessage] = useState("");
  const [generationProvider, setGenerationProvider] = useState<"auto" | "openai" | "anthropic">("auto");
  const [generationModel, setGenerationModel] = useState("gpt-4o-mini");
  const [providerAvailability, setProviderAvailability] = useState({ openai: true, anthropic: true });
  const [sending, setSending] = useState(false);
  const [loadingAgent, setLoadingAgent] = useState(true);
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [feedbackNotice, setFeedbackNotice] = useState("");
  const [error, setError] = useState("");
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScrollRef = useRef(true);

  const baseModelOptions = getModelOptions(generationProvider, providerAvailability);
  const selectableModelOptions = ensureModelInOptions(baseModelOptions, generationModel || "gpt-4o-mini");

  useEffect(() => {
    let mounted = true;

    async function loadAgent() {
      if (!session) {
        setLoadingAgent(false);
        return;
      }
      setLoadingAgent(true);
      try {
        const agents = await listAgents(session.accessToken);
        if (!mounted) {
          return;
        }
        const selected = agents.find((item) => item.agent_id === agentId) ?? null;
        setAgent(selected);
        if (selected) {
          try {
            const llmSettings = await getTenantLlmSettings(session.accessToken, selected.company_id);
            if (!mounted) {
              return;
            }

            const availability = {
              openai: llmSettings.has_openai_api_key,
              anthropic: llmSettings.has_anthropic_api_key
            };
            setProviderAvailability(availability);

            const selectedProvider = normalizeProvider(selected.generation_provider);
            const effectiveProvider = isProviderEnabled(selectedProvider, availability)
              ? selectedProvider
              : pickDefaultProvider(availability);
            setGenerationProvider(effectiveProvider);

            if (effectiveProvider === "anthropic") {
              setGenerationModel(llmSettings.anthropic_model);
            } else if (effectiveProvider === "openai") {
              setGenerationModel(selected.openai_model || llmSettings.openai_model);
            } else {
              setGenerationModel(availability.openai ? llmSettings.openai_model : llmSettings.anthropic_model);
            }
          } catch {
            setProviderAvailability({ openai: true, anthropic: true });
            setGenerationProvider(selected.generation_provider);
            setGenerationModel(selected.openai_model);
          }
        }
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el agente seleccionado");
        }
      }
      finally {
        if (mounted) {
          setLoadingAgent(false);
        }
      }
    }

    void loadAgent();
    return () => {
      mounted = false;
    };
  }, [agentId, session]);

  useEffect(() => {
    if (isProviderEnabled(generationProvider, providerAvailability)) {
      return;
    }
    setGenerationProvider(pickDefaultProvider(providerAvailability));
  }, [generationProvider, providerAvailability]);

  useEffect(() => {
    const container = messageListRef.current;
    if (!container) {
      return;
    }

    if (shouldAutoScrollRef.current || sending) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }, [history, sending, loadingAgent]);

  function handleMessageListScroll() {
    const container = messageListRef.current;
    if (!container) {
      return;
    }

    const distanceToBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldAutoScrollRef.current = distanceToBottom < 72;
  }

  useEffect(() => {
    if (!baseModelOptions.length) {
      return;
    }
    if (baseModelOptions.includes(generationModel)) {
      return;
    }
    setGenerationModel(baseModelOptions[0]);
  }, [baseModelOptions, generationModel]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !agent || !message.trim()) {
      setError("Ingresa una consulta y confirma el agente");
      return;
    }

    const question = message.trim();
    setSending(true);
    setError("");
    setMessage("");
    setHistory((current) => [...current, { role: "user", content: question }]);

    try {
      const result = await chatWithAgent(
        agent.agent_id,
        {
          message: question,
          top_k: 4,
          session_id: session.userId,
          use_openai_generation: true,
          generation_provider: generationProvider,
          generation_model: generationModel
        },
        session.accessToken
      );

      setHistory((current) => [
        ...current,
        {
          role: "assistant",
          content: tuneAssistantAnswer(result.answer),
          rawAnswer: result.answer,
          question,
          sources: result.sources,
          feedbackStatus: "idle"
        }
      ]);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo ejecutar la consulta");
      }
    } finally {
      setSending(false);
    }
  }

  async function onSendFeedback(index: number, rating: "up" | "down") {
    if (!session || !agent) {
      return;
    }

    const target = history[index];
    if (!target || target.role !== "assistant") {
      return;
    }
    if (!target.question?.trim()) {
      setError("No se pudo identificar la pregunta asociada al feedback");
      return;
    }
    if (target.feedbackStatus === "sending" || target.feedbackStatus === "sent_up" || target.feedbackStatus === "sent_down") {
      return;
    }

    setFeedbackNotice("");
    setHistory((current) =>
      current.map((entry, entryIndex) =>
        entryIndex === index ? { ...entry, feedbackStatus: "sending" } : entry
      )
    );

    try {
      await createAgentFeedback(
        agent.agent_id,
        {
          rating,
          question: target.question,
          answer: target.rawAnswer ?? target.content,
          sources: target.sources ?? [],
          session_id: session.userId,
          source_channel: "agent_playground"
        },
        session.accessToken
      );

      setHistory((current) =>
        current.map((entry, entryIndex) =>
          entryIndex === index
            ? { ...entry, feedbackStatus: rating === "up" ? "sent_up" : "sent_down" }
            : entry
        )
      );
      setFeedbackNotice(rating === "up" ? "Feedback positivo guardado." : "Feedback negativo guardado.");
    } catch (err) {
      setHistory((current) =>
        current.map((entry, entryIndex) =>
          entryIndex === index ? { ...entry, feedbackStatus: "error" } : entry
        )
      );
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo guardar feedback");
      }
    }
  }

  return (
    <section className="stack console-screen" aria-label="Playground de agente">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / playground</p>
        <h1>{agent?.name ?? "Playground"}</h1>
        <p className="muted">Consulta al agente y obtene respuestas operativas en lenguaje natural.</p>
      </article>

      <div className="dashboard-grid">
        <article className="surface stack conversation-panel">
          <div className="cluster between">
            <h2>Conversacion</h2>
          </div>

          <div className="cluster">
            <label>
              Provider
              <select
                value={generationProvider}
                onChange={(event) => setGenerationProvider(normalizeProvider(event.target.value))}
              >
                <option value="auto">auto</option>
                <option value="openai" disabled={!providerAvailability.openai}>
                  openai
                </option>
                <option value="anthropic" disabled={!providerAvailability.anthropic}>
                  anthropic
                </option>
              </select>
            </label>

            <label>
              Modelo
              <select
                value={generationModel}
                onChange={(event) => setGenerationModel(event.target.value)}
              >
                {selectableModelOptions.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="chat-shell">
            <div
              ref={messageListRef}
              className="message-list"
              aria-live="polite"
              onScroll={handleMessageListScroll}
            >
              {loadingAgent ? (
                <div className="stack chat-loading" aria-live="polite" aria-busy="true">
                  <div className="surface skeleton-row" />
                  <div className="surface skeleton-row" />
                </div>
              ) : !history.length ? (
                <div className="empty-state">
                  <p className="muted">Aun no hay mensajes. Escribe una consulta para iniciar la prueba.</p>
                </div>
              ) : (
                history.map((entry, index) => (
                  <motion.article
                    key={`${entry.role}-${index}`}
                    className={`message ${entry.role}`}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ type: "spring", stiffness: 100, damping: 20 }}
                  >
                    <p className="message-role">{entry.role === "user" ? "Tu" : "Agente"}</p>
                    <p>{entry.content}</p>
                    {entry.role === "assistant" ? (
                      <div className="cluster compact">
                        <button
                          type="button"
                          className="button-link ghost-link"
                          onClick={() => void onSendFeedback(index, "up")}
                          disabled={entry.feedbackStatus === "sending" || entry.feedbackStatus === "sent_up" || entry.feedbackStatus === "sent_down"}
                        >
                          <ThumbsUp size={14} weight="duotone" />
                          Util
                        </button>
                        <button
                          type="button"
                          className="button-link ghost-link"
                          onClick={() => void onSendFeedback(index, "down")}
                          disabled={entry.feedbackStatus === "sending" || entry.feedbackStatus === "sent_up" || entry.feedbackStatus === "sent_down"}
                        >
                          <ThumbsDown size={14} weight="duotone" />
                          No sirvio
                        </button>
                        {entry.feedbackStatus === "sending" ? <span className="mono muted">guardando...</span> : null}
                        {entry.feedbackStatus === "sent_up" || entry.feedbackStatus === "sent_down" ? (
                          <span className="mono muted">guardado</span>
                        ) : null}
                      </div>
                    ) : null}
                  </motion.article>
                ))
              )}
              {sending ? (
                <article className="message assistant pending" aria-live="polite" aria-busy="true">
                  <p className="message-role">Agente</p>
                  <p className="typing-indicator" aria-label="Generando respuesta">
                    <span />
                    <span />
                    <span />
                  </p>
                </article>
              ) : null}
            </div>

            <form onSubmit={onSubmit} className="chat-composer">
              <input
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Pregunta algo actual sobre la empresa"
              />
              <button type="submit" disabled={sending || loadingAgent}>
                <ChatsCircle size={16} weight="duotone" />
                {sending ? "Enviando..." : "Enviar"}
              </button>
            </form>
          </div>
        </article>
      </div>

      {feedbackNotice ? <p className="muted">{feedbackNotice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
