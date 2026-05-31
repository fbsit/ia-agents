"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiError } from "@/shared/api/client";
import { registerUser } from "@/shared/api/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      await registerUser({ email, password });
      setSuccess("Cuenta creada. Ahora inicia sesion.");
      setTimeout(() => router.push("/login"), 800);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo registrar la cuenta");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="auth-shell">
      <article className="surface auth-hero" aria-label="Introduccion de registro">
        <div className="stack">
          <p className="mono muted">northline / onboarding</p>
          <h1>Crear cuenta</h1>
          <p className="muted">Registra tu usuario y activa el workspace para empezar a construir agentes empresariales.</p>
        </div>

        <div className="auth-meta">
          <p className="muted">Despues del registro podras:</p>
          <ul>
            <li>Crear tu primera organizacion</li>
            <li>Asignar un company_id por tenant</li>
            <li>Entrenar y probar agentes con RAG</li>
          </ul>
        </div>
      </article>

      <article className="surface auth-card" aria-label="Formulario de registro">
        <form onSubmit={onSubmit}>
          <label>
            Email
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label>
            Password (min 8)
            <input
              required
              type="password"
              value={password}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error ? <p className="error">{error}</p> : null}
          {success ? <p className="success">{success}</p> : null}

          <button type="submit" disabled={loading}>
            {loading ? "Registrando..." : "Registrarme"}
          </button>
        </form>

        <p className="muted">
          ¿Ya tenes cuenta? <Link href="/login">Inicia sesion</Link>
        </p>
      </article>
    </section>
  );
}
