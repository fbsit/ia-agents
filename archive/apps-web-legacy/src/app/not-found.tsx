import Link from "next/link";

export default function NotFoundPage() {
  return (
    <section className="surface stack" aria-label="Pagina no encontrada">
      <p className="mono muted">404</p>
      <h1>No encontramos esta pagina</h1>
      <p className="muted">Revisa la URL o vuelve al dashboard para continuar trabajando en tus agentes.</p>
      <p>
        <Link href="/dashboard">Ir al dashboard</Link>
      </p>
    </section>
  );
}
