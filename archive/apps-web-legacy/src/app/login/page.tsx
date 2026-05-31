"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiError } from "@/shared/api/client";
import { loginUser } from "@/shared/api/auth";
import { useSession } from "@/shared/session/provider";

export default function LoginPage() {
  const router = useRouter();
  const { setFromLogin } = useSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await loginUser({ email, password });
      setFromLogin(result);
      router.push(result.memberships.length > 0 ? "/dashboard" : "/onboarding");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("No se pudo iniciar sesion");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="auth-shell">
      <article className="surface auth-hero auth-hero-with-video" aria-label="Contexto de acceso">
        <video className="auth-hero-video" autoPlay muted loop playsInline preload="metadata">
          <source src="/media/login-left-background.mp4" type="video/mp4" />
        </video>
        <div className="auth-hero-scrim" aria-hidden="true" />

        <div className="auth-hero-content">
          <div className="stack">
            <p className="mono muted">northline / acceso</p>
            <h1>Iniciar sesion</h1>
            <p className="muted">Accede al workspace de tu empresa y continua configurando tus agentes.</p>
          </div>

          <div className="auth-meta">
            <p className="muted">Con esta cuenta podras:</p>
            <ul>
              <li>Administrar organizaciones y company_id</li>
              <li>Subir documentos y reconstruir indices RAG</li>
              <li>Probar respuestas con o sin OpenAI</li>
            </ul>
          </div>
        </div>
      </article>

      <article className="surface auth-card" aria-label="Formulario de inicio de sesion">
        <form onSubmit={onSubmit}>
          <label>
            Email
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="tu@empresa.com"
            />
          </label>

          <label>
            Password
            <input
              required
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
            />
          </label>

          {error ? <p className="error">{error}</p> : null}

          <button type="submit" disabled={loading}>
            {loading ? "Ingresando..." : "Ingresar"}
          </button>
        </form>

        <p className="muted">
          ¿No tenes cuenta? <Link href="/register">Registrate</Link>
        </p>
      </article>
    </section>
  );
}
