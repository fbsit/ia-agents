"use client";

import { useEffect, useMemo, useState } from "react";

import { ConsoleNav } from "@/features/agents/console-nav";
import { ApiError } from "@/shared/api/client";
import { getTenantLlmSettings, updateTenantLlmSettings } from "@/shared/api/settings";
import { listOrganizations } from "@/shared/api/tenancy";
import type { Organization, TenantLlmSettings } from "@/shared/api/types";
import {
  ANTHROPIC_MODEL_OPTIONS,
  OPENAI_MODEL_OPTIONS,
  ensureModelInOptions,
  isProviderEnabled,
  normalizeProvider,
  pickDefaultProvider
} from "@/shared/llm/catalog";
import { useSession } from "@/shared/session/provider";

export function LlmSettingsClient() {
  const { session } = useSession();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [settings, setSettings] = useState<TenantLlmSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [generationProvider, setGenerationProvider] = useState<"auto" | "openai" | "anthropic">("auto");
  const [openaiModel, setOpenaiModel] = useState("gpt-4o-mini");
  const [anthropicModel, setAnthropicModel] = useState("claude-sonnet-4-6");
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [anthropicApiKey, setAnthropicApiKey] = useState("");
  const [clearOpenAiKey, setClearOpenAiKey] = useState(false);
  const [clearAnthropicKey, setClearAnthropicKey] = useState(false);

  const effectiveAvailability = useMemo(
    () => ({
      openai: Boolean((settings?.has_openai_api_key && !clearOpenAiKey) || openaiApiKey.trim()),
      anthropic: Boolean((settings?.has_anthropic_api_key && !clearAnthropicKey) || anthropicApiKey.trim())
    }),
    [anthropicApiKey, clearAnthropicKey, clearOpenAiKey, openaiApiKey, settings]
  );
  const openaiModelOptions = ensureModelInOptions([...OPENAI_MODEL_OPTIONS], openaiModel);
  const anthropicModelOptions = ensureModelInOptions([...ANTHROPIC_MODEL_OPTIONS], anthropicModel);

  useEffect(() => {
    if (isProviderEnabled(generationProvider, effectiveAvailability)) {
      return;
    }
    setGenerationProvider(pickDefaultProvider(effectiveAvailability));
  }, [effectiveAvailability, generationProvider]);

  useEffect(() => {
    let mounted = true;

    async function loadOrganizations() {
      if (!session) {
        return;
      }

      setLoading(true);
      setError("");
      try {
        const orgs = await listOrganizations(session.accessToken);
        if (!mounted) {
          return;
        }
        setOrganizations(orgs);
        if (orgs.length > 0) {
          setSelectedCompanyId(orgs[0].company_id);
        }
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudieron cargar organizaciones");
        }
      } finally {
        if (mounted) {
          setLoading(false);
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

    async function loadSettings() {
      if (!session || !selectedCompanyId) {
        return;
      }

      setLoading(true);
      setError("");
      setNotice("");

      try {
        const response = await getTenantLlmSettings(session.accessToken, selectedCompanyId);
        if (!mounted) {
          return;
        }

        setSettings(response);
        setGenerationProvider(response.generation_provider);
        setOpenaiModel(response.openai_model);
        setAnthropicModel(response.anthropic_model);
        setOpenaiApiKey("");
        setAnthropicApiKey("");
        setClearOpenAiKey(false);
        setClearAnthropicKey(false);
      } catch (err) {
        if (!mounted) {
          return;
        }
        if (err instanceof ApiError) {
          setError(err.detail);
        } else {
          setError("No se pudo cargar configuracion LLM");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void loadSettings();
    return () => {
      mounted = false;
    };
  }, [session, selectedCompanyId]);

  async function handleSave() {
    if (!session || !selectedCompanyId) {
      setError("Selecciona una organizacion");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");

    try {
      const response = await updateTenantLlmSettings(session.accessToken, {
        company_id: selectedCompanyId,
        generation_provider: generationProvider,
        openai_model: openaiModel,
        anthropic_model: anthropicModel,
        openai_api_key: openaiApiKey.trim() || undefined,
        anthropic_api_key: anthropicApiKey.trim() || undefined,
        clear_openai_api_key: clearOpenAiKey,
        clear_anthropic_api_key: clearAnthropicKey
      });

      setSettings(response);
      setOpenaiApiKey("");
      setAnthropicApiKey("");
      setClearOpenAiKey(false);
      setClearAnthropicKey(false);
      setNotice("Configuracion guardada");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo guardar configuracion LLM");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="stack console-screen" aria-label="Configuracion LLM">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">settings / llm</p>
        <h1>Configuracion de modelos y API keys</h1>
        <p className="muted">
          Define proveedor y modelos por tenant. Las keys quedan guardadas para este workspace.
        </p>
      </article>

      <article className="surface stack">
        <h2>Proveedor y modelos</h2>
        <label>
          Organizacion
          <select
            value={selectedCompanyId}
            onChange={(event) => setSelectedCompanyId(event.target.value)}
            disabled={loading || !organizations.length}
          >
            {organizations.map((organization) => (
              <option key={organization.org_id} value={organization.company_id}>
                {organization.name} ({organization.company_id})
              </option>
            ))}
          </select>
        </label>

        <label>
          Proveedor por defecto
          <select
            value={generationProvider}
            onChange={(event) => setGenerationProvider(normalizeProvider(event.target.value))}
            disabled={loading}
          >
            <option value="auto">auto</option>
            <option value="openai" disabled={!effectiveAvailability.openai}>
              openai
            </option>
            <option value="anthropic" disabled={!effectiveAvailability.anthropic}>
              anthropic (Claude)
            </option>
          </select>
        </label>

        <label>
          Modelo OpenAI
          <select
            value={openaiModel}
            onChange={(event) => setOpenaiModel(event.target.value)}
            disabled={loading || !effectiveAvailability.openai}
          >
            {openaiModelOptions.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <label>
          Modelo Claude
          <select
            value={anthropicModel}
            onChange={(event) => setAnthropicModel(event.target.value)}
            disabled={loading || !effectiveAvailability.anthropic}
          >
            {anthropicModelOptions.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <button type="button" onClick={() => void handleSave()} disabled={saving || loading || !selectedCompanyId}>
          {saving ? "Guardando..." : "Guardar cambios"}
        </button>
      </article>

      <article className="surface stack">
        <h2>Credenciales OpenAI</h2>
        <label>
          OpenAI API key
          <input
            type="password"
            value={openaiApiKey}
            onChange={(event) => setOpenaiApiKey(event.target.value)}
            placeholder="sk-..."
            disabled={loading}
          />
        </label>
        <label className="toggle-label">
          <span>Eliminar key OpenAI guardada en tenant</span>
          <input
            type="checkbox"
            checked={clearOpenAiKey}
            onChange={(event) => setClearOpenAiKey(event.target.checked)}
            disabled={loading}
          />
        </label>

        <p className="mono muted">
          OpenAI: {settings?.openai_api_key_masked ?? "sin key"} ({settings?.openai_key_source ?? "none"})
        </p>

        <button type="button" onClick={() => void handleSave()} disabled={saving || loading || !selectedCompanyId}>
          {saving ? "Guardando..." : "Guardar cambios"}
        </button>
      </article>

      <article className="surface stack">
        <h2>Credenciales Claude</h2>
        <label>
          Anthropic API key
          <input
            type="password"
            value={anthropicApiKey}
            onChange={(event) => setAnthropicApiKey(event.target.value)}
            placeholder="sk-ant-..."
            disabled={loading}
          />
        </label>
        <label className="toggle-label">
          <span>Eliminar key Anthropic guardada en tenant</span>
          <input
            type="checkbox"
            checked={clearAnthropicKey}
            onChange={(event) => setClearAnthropicKey(event.target.checked)}
            disabled={loading}
          />
        </label>

        <p className="mono muted">
          Claude: {settings?.anthropic_api_key_masked ?? "sin key"} ({settings?.anthropic_key_source ?? "none"})
        </p>

        <button type="button" onClick={() => void handleSave()} disabled={saving || loading || !selectedCompanyId}>
          {saving ? "Guardando..." : "Guardar cambios"}
        </button>
      </article>

      {notice ? <p className="mono muted">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
