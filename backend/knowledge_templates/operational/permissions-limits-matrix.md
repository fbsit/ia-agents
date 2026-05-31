# Permisos y limites

## Metadata

- company_id: REEMPLAZAR_COMPANY_ID
- version: 2026-04-03
- owner: nombre.apellido

## Matriz rol x accion

| role | action | mode | limit | approval_flow |
| --- | --- | --- | --- | --- |
| owner | approve_refund | automatico | <= 50000 CLP | none |
| supervisor | send_email_notification | automatico | <= 200 envios/hora | none |
| analyst | update_ticket_status | con_aprobacion | cualquier monto | supervisor_or_owner |
| viewer | any | prohibido | n/a | n/a |

## Limites globales

- max_actions_per_minute: 120
- restricted_hours_local: 00:00-06:00
- blocked_domains: ejemplo-bloqueado.com

## Prohibiciones

- Nunca cambiar estado a `approved` cuando `risk_score >= 0.8`.
- Nunca enviar correo a dominios fuera de allowlist.
- Nunca ejecutar acciones en tenant distinto al `company_id` de la sesion.
