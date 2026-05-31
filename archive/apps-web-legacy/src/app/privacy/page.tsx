import Link from "next/link";

export default function PrivacyPage() {
  return (
    <section className="surface stack">
      <p className="mono muted">legal</p>
      <h1>Privacy policy</h1>
      <p>
        Guardamos datos de autenticacion, pertenencia a organizaciones y configuracion de agentes para operar
        el servicio. No compartimos contenido de documentos fuera del contexto del tenant autorizado.
      </p>
      <p>
        Puedes solicitar eliminacion de datos de una organizacion escribiendo al equipo de soporte con el
        company_id correspondiente.
      </p>
      <p>
        <Link href="/dashboard">Volver al dashboard</Link>
      </p>
    </section>
  );
}
