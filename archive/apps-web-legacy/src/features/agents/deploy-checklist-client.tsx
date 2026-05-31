"use client";

import { useEffect, useState } from "react";
import { CopySimple, GearSix, WhatsappLogo } from "@phosphor-icons/react";

import {
  getAgentWhatsAppConfig,
  getAgentWidgetConfig,
  updateAgentWhatsAppConfig,
  validateAgentWhatsAppConfig
} from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import type { AgentWhatsAppConfig, AgentWhatsAppValidation, AgentWidgetConfig } from "@/shared/api/types";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";

type DeployChecklistClientProps = {
  agentId: string;
};

export function DeployChecklistClient({ agentId }: DeployChecklistClientProps) {
  const { session } = useSession();
  const [activeChannel, setActiveChannel] = useState<"whatsapp" | "webchat">("whatsapp");
  const [whatsAppConfig, setWhatsAppConfig] = useState<AgentWhatsAppConfig | null>(null);
  const [whatsAppApiUnavailable, setWhatsAppApiUnavailable] = useState(false);
  const [validation, setValidation] = useState<AgentWhatsAppValidation | null>(null);
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [businessAccountId, setBusinessAccountId] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [savingWhatsApp, setSavingWhatsApp] = useState(false);
  const [validatingWhatsApp, setValidatingWhatsApp] = useState(false);
  const [whatsAppNotice, setWhatsAppNotice] = useState("");
  const [widgetConfig, setWidgetConfig] = useState<AgentWidgetConfig | null>(null);
  const [copyNotice, setCopyNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadDeployContext() {
      if (!session) {
        return;
      }

      try {
        const widget = await getAgentWidgetConfig(agentId, session.accessToken);
        let channelConfig: AgentWhatsAppConfig;

        try {
          channelConfig = await getAgentWhatsAppConfig(agentId, session.accessToken);
          setWhatsAppApiUnavailable(false);
        } catch (err) {
          if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
            setWhatsAppApiUnavailable(true);
            const fallbackWebhookUrl = widget.endpoint_url.replace("/public/widget/chat", "/webhooks/whatsapp");
            channelConfig = {
              agent_id: widget.agent_id,
              company_id: "",
              webhook_url: fallbackWebhookUrl,
              phone_number_id: null,
              business_account_id: null,
              verify_token: null,
              updated_at: null
            };
          } else {
            throw err;
          }
        }

        if (!mounted) {
          return;
        }

        setWidgetConfig(widget);
        setWhatsAppConfig(channelConfig);
        setPhoneNumberId(channelConfig.phone_number_id ?? "");
        setBusinessAccountId(channelConfig.business_account_id ?? "");
        setVerifyToken(channelConfig.verify_token ?? "");
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar el estado de deploy");
        }
      }
    }

    void loadDeployContext();
    return () => {
      mounted = false;
    };
  }, [agentId, session]);

  async function handleCopySnippet() {
    if (!widgetConfig?.snippet_html) {
      return;
    }

    try {
      await navigator.clipboard.writeText(widgetConfig.snippet_html);
      setCopyNotice("Snippet copiado al portapapeles");
    } catch {
      setCopyNotice("No se pudo copiar automaticamente");
    }
  }

  async function handleSaveWhatsAppConfig() {
    if (!session) {
      return;
    }
    if (whatsAppApiUnavailable) {
      setWhatsAppNotice("Tu backend no tiene endpoints de WhatsApp por agente. Reinicia API para habilitar guardado.");
      return;
    }

    setSavingWhatsApp(true);
    setError("");
    setWhatsAppNotice("");

    try {
      const updated = await updateAgentWhatsAppConfig(
        agentId,
        {
          phone_number_id: phoneNumberId,
          business_account_id: businessAccountId,
          verify_token: verifyToken
        },
        session.accessToken
      );
      setWhatsAppConfig(updated);
      setWhatsAppNotice("Configuracion de WhatsApp guardada.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo guardar configuracion de WhatsApp");
      }
    } finally {
      setSavingWhatsApp(false);
    }
  }

  async function handleValidateWhatsAppConfig() {
    if (!session) {
      return;
    }
    if (whatsAppApiUnavailable) {
      setWhatsAppNotice("Tu backend no tiene endpoints de WhatsApp por agente. Reinicia API para validar.");
      return;
    }

    setValidatingWhatsApp(true);
    setError("");
    setWhatsAppNotice("");

    try {
      const result = await validateAgentWhatsAppConfig(agentId, session.accessToken);
      setValidation(result);
      setWhatsAppNotice(result.ready ? "Conexion lista para pruebas con Meta." : "Faltan requisitos para activar WhatsApp.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo validar configuracion de WhatsApp");
      }
    } finally {
      setValidatingWhatsApp(false);
    }
  }

  return (
    <section className="stack console-screen" aria-label="Preparacion de deploy">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / deploy</p>
        <h1>Deploy checklist</h1>
        <p className="muted">Valida requisitos antes de conectar WhatsApp o un widget web.</p>
      </article>

      <article className="surface stack deploy-channels-card">
        <h2>Canales disponibles</h2>
        <div className="compose-tabs" role="tablist" aria-label="Canales de despliegue">
          <button
            type="button"
            role="tab"
            aria-selected={activeChannel === "whatsapp"}
            className={activeChannel === "whatsapp" ? "compose-tab active" : "compose-tab"}
            onClick={() => setActiveChannel("whatsapp")}
          >
            <WhatsappLogo size={18} weight="duotone" />
            WhatsApp
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeChannel === "webchat"}
            className={activeChannel === "webchat" ? "compose-tab active" : "compose-tab"}
            onClick={() => setActiveChannel("webchat")}
          >
            <GearSix size={18} weight="duotone" />
            Webchat
          </button>
        </div>

        {activeChannel === "whatsapp" ? (
          <div className="channel-card" role="tabpanel" aria-label="Configuracion WhatsApp">
            <div className="cluster">
              <WhatsappLogo size={20} weight="duotone" />
              <strong>WhatsApp Cloud API</strong>
            </div>

            <label>
              Phone Number ID (Meta)
              <input
                type="text"
                value={phoneNumberId}
                onChange={(event) => setPhoneNumberId(event.target.value)}
                placeholder="123456789012345"
              />
            </label>

            <label>
              WhatsApp Business Account ID (opcional)
              <input
                type="text"
                value={businessAccountId}
                onChange={(event) => setBusinessAccountId(event.target.value)}
                placeholder="123456789012345"
              />
            </label>

            <label>
              Verify token (debe coincidir con servidor)
              <input
                type="text"
                value={verifyToken}
                onChange={(event) => setVerifyToken(event.target.value)}
                placeholder="mi-token-seguro"
              />
            </label>

            <p className="muted">
              Webhook para Meta: <span className="mono">{whatsAppConfig?.webhook_url ?? "cargando..."}</span>
            </p>

            <div className="cluster">
              <button
                type="button"
                onClick={() => void handleSaveWhatsAppConfig()}
                disabled={savingWhatsApp || whatsAppApiUnavailable}
              >
                {savingWhatsApp ? "Guardando..." : "Guardar configuracion"}
              </button>
              <button
                type="button"
                className="button-link ghost-link"
                onClick={() => void handleValidateWhatsAppConfig()}
                disabled={validatingWhatsApp || whatsAppApiUnavailable}
              >
                {validatingWhatsApp ? "Validando..." : "Validar conexion"}
              </button>
            </div>

            {whatsAppApiUnavailable ? (
              <p className="muted">Modo compatibilidad: actualiza/reinicia backend para habilitar guardado y validacion.</p>
            ) : null}

            {validation ? (
              <div className="stack compact">
                <p className={validation.ready ? "success" : "muted"}>
                  {validation.ready ? "Listo para conectar con Meta" : "Configuracion incompleta"}
                </p>
                <ul className="stack compact">
                  {validation.messages.map((message) => (
                    <li key={message} className="muted">
                      - {message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="channel-card" role="tabpanel" aria-label="Configuracion Webchat">
            <div className="cluster">
              <GearSix size={20} weight="duotone" />
              <strong>Webchat embebido</strong>
            </div>
            {widgetConfig ? (
              <div className="stack compact">
                <p className="muted">
                  Endpoint publico: <span className="mono">{widgetConfig.endpoint_url}</span>
                </p>
                <p className="muted">
                  Rate limit: {widgetConfig.rate_limit_max_requests} req cada {widgetConfig.rate_limit_window_seconds}s
                </p>
                <div className="cluster">
                  <button type="button" className="button-link ghost-link" onClick={() => void handleCopySnippet()}>
                    <CopySimple size={16} weight="duotone" />
                    Copiar snippet
                  </button>
                </div>
                <textarea
                  value={widgetConfig.snippet_html}
                  readOnly
                  rows={10}
                  className="mono"
                  aria-label="Snippet de webchat"
                />
              </div>
            ) : (
              <p className="muted">Generando snippet de widget...</p>
            )}
          </div>
        )}
      </article>

      {error ? <p className="error">{error}</p> : null}
      {copyNotice ? <p className="muted">{copyNotice}</p> : null}
      {whatsAppNotice ? <p className="muted">{whatsAppNotice}</p> : null}
    </section>
  );
}
