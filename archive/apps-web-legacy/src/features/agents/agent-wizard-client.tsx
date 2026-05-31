"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { zodResolver } from "@hookform/resolvers/zod";
import { Check, CompassTool, Robot, Sparkle } from "@phosphor-icons/react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { createAgent } from "@/shared/api/agents";
import { ApiError } from "@/shared/api/client";
import { getTenantLlmSettings } from "@/shared/api/settings";
import { listOrganizations } from "@/shared/api/tenancy";
import type { Organization } from "@/shared/api/types";
import {
  ensureModelInOptions,
  getModelOptions,
  isProviderEnabled,
  normalizeProvider,
  pickDefaultProvider
} from "@/shared/llm/catalog";
import { useSession } from "@/shared/session/provider";
import { ConsoleNav } from "@/features/agents/console-nav";

const formSchema = z.object({
  company_id: z.string().min(1, "Selecciona una organizacion"),
  name: z.string().min(2, "Nombre demasiado corto"),
  objective: z.string().min(8, "El objetivo debe ser mas especifico"),
  tone: z.string().min(3, "El tono debe tener al menos 3 caracteres"),
  description: z.string().optional(),
  rag_backend: z.enum(["auto", "tfidf", "dense_openai", "hybrid"]),
  generation_provider: z.enum(["auto", "openai", "anthropic"]),
  use_openai_generation: z.boolean(),
  openai_model: z.string().min(3, "Modelo invalido")
});

type WizardForm = z.infer<typeof formSchema>;

const STEPS = [
  { title: "Identidad", subtitle: "Nombre y tenant" },
  { title: "Comportamiento", subtitle: "Objetivo y tono" },
  { title: "RAG", subtitle: "Backend e indexado" },
  { title: "Canal", subtitle: "Proveedor y modelo" }
];

const STEP_FIELDS: Array<Array<keyof WizardForm>> = [
  ["company_id", "name"],
  ["objective", "tone", "description"],
  ["rag_backend"],
  ["generation_provider", "use_openai_generation", "openai_model"]
];

export function AgentWizardClient() {
  const router = useRouter();
  const { session } = useSession();
  const [step, setStep] = useState(0);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [providerAvailability, setProviderAvailability] = useState({ openai: true, anthropic: true });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors },
    watch,
    setValue,
    trigger
  } = useForm<WizardForm>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      company_id: "",
      name: "",
      objective: "Responder consultas frecuentes de la empresa con evidencia del conocimiento cargado",
      tone: "profesional",
      description: "",
      rag_backend: "auto",
      generation_provider: "auto",
      use_openai_generation: true,
      openai_model: "gpt-4o-mini"
    }
  });

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
          setValue("company_id", response[0].company_id);
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
      }
    }

    void loadOrganizations();
    return () => {
      mounted = false;
    };
  }, [session, setValue]);

  const selectedOrg = useMemo(() => {
    const companyId = watch("company_id");
    return organizations.find((item) => item.company_id === companyId) ?? null;
  }, [organizations, watch]);

  const selectedCompanyId = watch("company_id");
  const selectedProvider = normalizeProvider(watch("generation_provider"));
  const selectedModel = watch("openai_model");
  const baseModelOptions = getModelOptions(selectedProvider, providerAvailability);
  const providerModelOptions = ensureModelInOptions(
    baseModelOptions,
    selectedModel || "gpt-4o-mini"
  );

  useEffect(() => {
    let mounted = true;

    async function loadTenantLlmDefaults() {
      if (!session || !selectedCompanyId) {
        return;
      }

      try {
        const llmSettings = await getTenantLlmSettings(session.accessToken, selectedCompanyId);
        if (!mounted) {
          return;
        }

        const availability = {
          openai: llmSettings.has_openai_api_key,
          anthropic: llmSettings.has_anthropic_api_key
        };
        setProviderAvailability(availability);

        const nextProvider = isProviderEnabled(llmSettings.generation_provider, availability)
          ? normalizeProvider(llmSettings.generation_provider)
          : pickDefaultProvider(availability);
        setValue("generation_provider", nextProvider);

        if (nextProvider === "anthropic") {
          setValue("openai_model", llmSettings.anthropic_model);
        } else {
          setValue("openai_model", llmSettings.openai_model);
        }
      } catch {
        setProviderAvailability({ openai: true, anthropic: true });
      }
    }

    void loadTenantLlmDefaults();
    return () => {
      mounted = false;
    };
  }, [selectedCompanyId, session, setValue]);

  useEffect(() => {
    if (isProviderEnabled(selectedProvider, providerAvailability)) {
      return;
    }
    setValue("generation_provider", pickDefaultProvider(providerAvailability));
  }, [providerAvailability, selectedProvider, setValue]);

  useEffect(() => {
    if (!baseModelOptions.length) {
      return;
    }
    if (baseModelOptions.includes(selectedModel)) {
      return;
    }
    setValue("openai_model", baseModelOptions[0]);
  }, [baseModelOptions, selectedModel, setValue]);

  const progressPercent = (step / (STEPS.length - 1)) * 100;

  async function nextStep() {
    const fields = STEP_FIELDS[step] ?? [];
    const valid = await trigger(fields);
    if (!valid) {
      return;
    }

    setStep((current) => Math.min(current + 1, STEPS.length - 1));
  }

  function prevStep() {
    setStep((current) => Math.max(current - 1, 0));
  }

  async function onSubmit(values: WizardForm) {
    if (!session) {
      setError("Sesion invalida");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const agent = await createAgent(values, session.accessToken);
      router.push(`/agents/${agent.agent_id}/knowledge`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo crear el agente");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="stack console-screen" aria-label="Wizard de agente">
      <ConsoleNav />

      <article className="surface stack">
        <p className="mono muted">agents / wizard</p>
        <h1>Crear agente</h1>
        <p className="muted">Configura identidad, comportamiento, estrategia RAG y canal por defecto en cuatro pasos.</p>
      </article>

      <article className="surface stack">
        <div className="wizard-flow" aria-label="Progreso del wizard">
          <div className="wizard-flow-track" aria-hidden="true">
            <span className="wizard-flow-progress" style={{ width: `${progressPercent}%` }} />
          </div>
          <div className="wizard-flow-header">
            <p className="mono muted">Paso {step + 1} de {STEPS.length}</p>
            <p className="wizard-flow-title">{STEPS[step]?.title}</p>
          </div>

          <div className="wizard-steps" role="list">
            {STEPS.map((item, idx) => {
              const state = idx < step ? "done" : idx === step ? "current" : "pending";
              return (
                <div
                  key={item.title}
                  role="listitem"
                  className={`wizard-step ${state}`}
                  aria-current={idx === step ? "step" : undefined}
                >
                  <span className="wizard-step-badge" aria-hidden="true">
                    {state === "done" ? <Check size={12} weight="bold" /> : idx + 1}
                  </span>
                  <div>
                    <p className="wizard-step-title">{item.title}</p>
                    <p className="wizard-step-subtitle">{item.subtitle}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <motion.form
          key={step}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 100, damping: 20 }}
          onSubmit={handleSubmit(onSubmit)}
          className="stack"
        >
          {step === 0 ? (
            <div className="stack">
              <h2>Identidad</h2>
              <label>
                Organizacion
                <select {...register("company_id")}>
                  {organizations.map((organization) => (
                    <option key={organization.org_id} value={organization.company_id}>
                      {organization.name} ({organization.company_id})
                    </option>
                  ))}
                </select>
              </label>
              {errors.company_id ? <p className="error">{errors.company_id.message}</p> : null}

              <label>
                Nombre del agente
                <input {...register("name")} placeholder="Soporte Atlas" />
              </label>
              {errors.name ? <p className="error">{errors.name.message}</p> : null}
            </div>
          ) : null}

          {step === 1 ? (
            <div className="stack">
              <h2>Comportamiento</h2>
              <label>
                Objetivo
                <textarea rows={4} {...register("objective")} />
              </label>
              {errors.objective ? <p className="error">{errors.objective.message}</p> : null}

              <label>
                Tono
                <input {...register("tone")} placeholder="profesional cercano" />
              </label>
              {errors.tone ? <p className="error">{errors.tone.message}</p> : null}

              <label>
                Descripcion
                <input {...register("description")} placeholder="Responde horarios, politicas y soporte" />
              </label>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="stack">
              <h2>RAG</h2>
              <label>
                Backend de recuperacion
                <select {...register("rag_backend")}>
                  <option value="auto">auto</option>
                  <option value="tfidf">tfidf</option>
                  <option value="dense_openai">dense_openai</option>
                  <option value="hybrid">hybrid (tfidf + dense)</option>
                </select>
              </label>
              <div className="cluster">
                <span className="badge-chip">
                  <CompassTool size={16} weight="duotone" />
                  {watch("rag_backend")}
                </span>
                <span className="badge-chip">
                  <Robot size={16} weight="duotone" />
                  Tenant: {selectedOrg?.company_id ?? "-"}
                </span>
              </div>
            </div>
          ) : null}

          {step === 3 ? (
            <div className="stack">
              <h2>Canal y humanizacion</h2>
              <label>
                <span>Activar generacion LLM por defecto</span>
                <input type="checkbox" {...register("use_openai_generation")} />
              </label>

              <label>
                Proveedor LLM
                <select {...register("generation_provider")}>
                  <option value="auto">auto</option>
                  <option value="openai" disabled={!providerAvailability.openai}>
                    openai
                  </option>
                  <option value="anthropic" disabled={!providerAvailability.anthropic}>
                    anthropic (Claude)
                  </option>
                </select>
              </label>

              <label>
                Modelo LLM
                <select {...register("openai_model")}>
                  {providerModelOptions.map((modelOption) => (
                    <option key={modelOption} value={modelOption}>
                      {modelOption}
                    </option>
                  ))}
                </select>
              </label>
              {errors.openai_model ? <p className="error">{errors.openai_model.message}</p> : null}

              <span className="badge-chip">
                <Sparkle size={16} weight="duotone" />
                Este ajuste se puede cambiar luego en deploy y playground.
              </span>
            </div>
          ) : null}

          <div className="cluster between">
            <div className="cluster">
              <button type="button" onClick={prevStep} disabled={step === 0 || submitting}>
                Volver
              </button>
              {step < STEPS.length - 1 ? (
                <button type="button" onClick={nextStep}>
                  Siguiente
                </button>
              ) : null}
            </div>

            {step === STEPS.length - 1 ? (
              <button type="submit" disabled={submitting}>
                {submitting ? "Creando..." : "Crear y continuar"}
              </button>
            ) : null}
          </div>
        </motion.form>
      </article>

      <p className="muted">
        ¿Ya tienes agentes? <Link href="/agents">Volver al listado</Link>
      </p>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
