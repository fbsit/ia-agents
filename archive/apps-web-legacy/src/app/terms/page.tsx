import Link from "next/link";

export default function TermsPage() {
  return (
    <section className="surface stack">
      <p className="mono muted">legal</p>
      <h1>Terms of service</h1>
      <p>
        El usuario es responsable por los documentos y credenciales que carga en la plataforma. El servicio se
        provee para automatizacion de soporte y consulta empresarial.
      </p>
      <p>
        El uso de integraciones externas (por ejemplo OpenAI o WhatsApp) depende de credenciales validas,
        cumplimiento legal y politicas de terceros.
      </p>
      <p>
        <Link href="/dashboard">Volver al dashboard</Link>
      </p>
    </section>
  );
}
