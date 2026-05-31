"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { ApiError } from "@/shared/api/client";
import { createOrganization } from "@/shared/api/tenancy";
import { RequireAuth } from "@/shared/session/require-auth";
import { useSession } from "@/shared/session/provider";

function OnboardingContent() {
  const router = useRouter();
  const { session, bootstrapProfile } = useSession();

  const [organizationName, setOrganizationName] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      setError("Sesion invalida");
      return;
    }

    setError("");
    setLoading(true);
    try {
      await createOrganization(
        {
          organization_name: organizationName,
          company_id: companyId || undefined
        },
        session.accessToken
      );
      await bootstrapProfile();
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo crear la organizacion");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="auth-shell">
      <article className="surface auth-hero" aria-label="Guia de onboarding">
        <div className="stack">
          <p className="mono muted">tenant setup</p>
          <h1>Onboarding de organizacion</h1>
          <p className="muted">Configura tu primer tenant para habilitar agentes y separar conocimiento por empresa.</p>
        </div>

        <div className="auth-meta">
          <p className="muted">Tip:</p>
          <p className="muted">
            Si dejas vacio el company ID, el sistema genera un slug automaticamente a partir del nombre.
          </p>
          <p>
            <Link href="/dashboard">Volver al dashboard</Link>
          </p>
        </div>
      </article>

      <article className="surface auth-card" aria-label="Formulario de organizacion">
        <form onSubmit={onSubmit}>
          <label>
            Nombre de la organizacion
            <input
              required
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
            />
          </label>

          <label>
            Company ID (opcional)
            <input
              value={companyId}
              onChange={(event) => setCompanyId(event.target.value)}
              placeholder="mi-empresa"
            />
          </label>

          {error ? <p className="error">{error}</p> : null}

          <button type="submit" disabled={loading}>
            {loading ? "Creando..." : "Crear organizacion"}
          </button>
        </form>
      </article>
    </section>
  );
}

export default function OnboardingPage() {
  return (
    <RequireAuth>
      <OnboardingContent />
    </RequireAuth>
  );
}
