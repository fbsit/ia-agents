export type OperationalKnowledgeSectionId = "facts" | "rules" | "contracts" | "permissions" | "feedback";

export type OperationalKnowledgeSection = {
  id: OperationalKnowledgeSectionId;
  label: string;
  description: string;
  filenameHint: string;
  tags: string[];
  checks: string[];
};

export const OPERATIONAL_SECTIONS: OperationalKnowledgeSection[] = [
  {
    id: "facts",
    label: "Hechos canonicos",
    description: "Politicas, precios, SLA y excepciones con fecha de vigencia.",
    filenameHint: "facts-canonicos.md",
    tags: ["facts", "fact", "hecho", "politica", "precio", "sla", "excepcion"],
    checks: ["Version por vigencia", "Fuente oficial", "Owner responsable"]
  },
  {
    id: "rules",
    label: "Reglas de decision",
    description: "Tablas if/then para decidir accion segun rol, monto y contexto.",
    filenameHint: "rules-decision-table.md",
    tags: ["rules", "rule", "regla", "decision", "if", "tabla"],
    checks: ["Prioridad de regla", "Condicion explicita", "Fallback definido"]
  },
  {
    id: "contracts",
    label: "Contratos de accion",
    description: "Entradas, salidas y errores esperables por API o tarea.",
    filenameHint: "contracts-action-schema.md",
    tags: ["contracts", "contract", "schema", "api", "accion", "task"],
    checks: ["JSON schema", "Precondiciones", "Idempotencia"]
  },
  {
    id: "permissions",
    label: "Permisos y limites",
    description: "Que se ejecuta automatico, que requiere aprobacion, que esta prohibido.",
    filenameHint: "permissions-limits-matrix.md",
    tags: ["permissions", "permiso", "limit", "approval", "role", "matriz"],
    checks: ["Matriz rol x accion", "Limites por monto", "Politica de aprobacion"]
  },
  {
    id: "feedback",
    label: "Feedback de ejecucion",
    description: "Registro real de ok/fail, motivo y aprendizaje para mejorar decisiones.",
    filenameHint: "feedback-execution-log.md",
    tags: ["feedback", "execution", "result", "learn", "retro"],
    checks: ["Estado por accion", "Codigo de error", "Aprendizaje operativo"]
  }
];

export function findOperationalSection(sectionId?: string | null): OperationalKnowledgeSection {
  return OPERATIONAL_SECTIONS.find((section) => section.id === sectionId) ?? OPERATIONAL_SECTIONS[0];
}

export function matchesOperationalSection(filename: string, section: OperationalKnowledgeSection): boolean {
  const normalized = filename.toLowerCase();
  return section.tags.some((tag) => normalized.includes(tag));
}

export function buildTemplateContent(section: OperationalKnowledgeSection, companyId: string): string {
  const date = new Date().toISOString().slice(0, 10);

  if (section.id === "facts") {
    return [
      `# Hechos canonicos - ${companyId}`,
      "",
      "## Metadata",
      `- company_id: ${companyId}`,
      `- version: ${date}`,
      "- owner: completar",
      "",
      "## Politicas y precios",
      "| fact_id | categoria | valor | effective_from | effective_to | source |",
      "| --- | --- | --- | --- | --- | --- |",
      "| FACT-001 | politica_devoluciones | 30 dias corridos | 2026-01-01 | null | politica-interna-v3.pdf |",
      "",
      "## SLA",
      "| fact_id | servicio | objetivo | unidad | excepcion |",
      "| --- | --- | --- | --- | --- |",
      "| SLA-001 | soporte_nivel_1 | 4 | horas | feriados regionales |"
    ].join("\n");
  }

  if (section.id === "rules") {
    return [
      `# Reglas de decision - ${companyId}`,
      "",
      "## Tabla de reglas",
      "| rule_id | priority | if | then | else | requires_approval |",
      "| --- | --- | --- | --- | --- | --- |",
      "| RULE-001 | 10 | role=owner AND amount<=50000 | action=approve_refund | action=request_manual_review | false |",
      "",
      "## Notas de fallback",
      "- Cuando ninguna regla matchea, usar action=escalate_to_human.",
      "- Registrar reason_code=NO_RULE_MATCH."
    ].join("\n");
  }

  if (section.id === "contracts") {
    return [
      `# Contratos de accion - ${companyId}`,
      "",
      "## action: update_ticket_status",
      "```json",
      "{",
      '  "input_schema": {',
      '    "type": "object",',
      '    "required": ["ticket_id", "new_status"],',
      '    "properties": {',
      '      "ticket_id": { "type": "string" },',
      '      "new_status": { "type": "string", "enum": ["pending", "approved", "rejected"] }',
      "    }",
      "  },",
      '  "output_schema": { "type": "object", "required": ["ticket_id", "status"] },',
      '  "preconditions": ["ticket_exists", "user_has_permission"],',
      '  "idempotency_key": "ticket_id:new_status"',
      "}",
      "```",
      "",
      "## Errores esperables",
      "- ERR_CONFLICT_STATUS",
      "- ERR_PERMISSION_DENIED",
      "- ERR_UPSTREAM_TIMEOUT"
    ].join("\n");
  }

  if (section.id === "permissions") {
    return [
      `# Permisos y limites - ${companyId}`,
      "",
      "## Matriz rol x accion",
      "| role | action | modo | limite |",
      "| --- | --- | --- | --- |",
      "| owner | approve_refund | automatico | <= 50000 CLP |",
      "| supervisor | send_email_notification | automatico | max 200 envios/hora |",
      "| analyst | update_ticket_status | requiere_aprobacion | cualquier monto |",
      "",
      "## Prohibiciones",
      "- El agente no puede cambiar estado a approved cuando score_fraude >= 0.8.",
      "- El agente no puede enviar emails fuera de dominios permitidos."
    ].join("\n");
  }

  return [
    `# Feedback de ejecucion - ${companyId}`,
    "",
    "## Log de resultados",
    "| execution_id | rule_id | action | status | reason | learned |",
    "| --- | --- | --- | --- | --- | --- |",
    "| EXEC-001 | RULE-001 | approve_refund | ok | regla aplicada segun monto | Mantener limite en 50000 CLP |",
    "| EXEC-002 | RULE-004 | send_email_notification | fail | ERR_UPSTREAM_TIMEOUT | Reintentar con backoff exponencial |",
    "",
    "## Mejora de reglas",
    "- Revisar reglas con fail rate > 3% semanal.",
    "- Abrir ticket cuando learned sugiere cambio de contrato."
  ].join("\n");
}
