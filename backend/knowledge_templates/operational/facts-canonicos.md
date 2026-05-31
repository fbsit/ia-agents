# Hechos canonicos

## Metadata

- company_id: REEMPLAZAR_COMPANY_ID
- version: 2026-04-03
- owner: nombre.apellido
- review_cycle_days: 30

## Politicas y precios

| fact_id | categoria | valor | currency | effective_from | effective_to | source |
| --- | --- | --- | --- | --- | --- | --- |
| FACT-001 | politica_devoluciones | 30 dias corridos | CLP | 2026-01-01 | null | politica-interna-v3.pdf |
| FACT-002 | precio_plan_standard | 19990 | CLP | 2026-01-01 | null | pricing-q1-2026.xlsx |

## SLA

| fact_id | servicio | objetivo | unidad | horario | excepcion |
| --- | --- | --- | --- | --- | --- |
| SLA-001 | soporte_nivel_1 | 4 | horas | lun-vie 09:00-18:00 | feriados regionales |
| SLA-002 | resolucion_incidente_alto | 24 | horas | 24x7 | terceros fuera de alcance |

## Excepciones

| exception_id | aplica_a | condicion | accion |
| --- | --- | --- | --- |
| EXC-001 | devoluciones | compra_promocion_final_sale=true | no_reembolso |
| EXC-002 | soporte | cliente_tier=enterprise | priorizar_cola |
