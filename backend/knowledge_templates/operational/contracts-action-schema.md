# Contratos de accion

## Metadata

- company_id: REEMPLAZAR_COMPANY_ID
- version: 2026-04-03
- owner: nombre.apellido

## Action: update_ticket_status

```json
{
  "action_id": "update_ticket_status",
  "input_schema": {
    "type": "object",
    "required": ["ticket_id", "new_status"],
    "properties": {
      "ticket_id": { "type": "string" },
      "new_status": { "type": "string", "enum": ["pending", "approved", "rejected"] }
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["ticket_id", "status", "updated_at"]
  },
  "preconditions": ["ticket_exists", "actor_has_permission"],
  "idempotency_key": "ticket_id:new_status",
  "errors": [
    { "code": "ERR_PERMISSION_DENIED", "retryable": false },
    { "code": "ERR_CONFLICT_STATUS", "retryable": false },
    { "code": "ERR_UPSTREAM_TIMEOUT", "retryable": true }
  ]
}
```

## Action: send_email_notification

```json
{
  "action_id": "send_email_notification",
  "input_schema": {
    "type": "object",
    "required": ["to", "template_id", "context"],
    "properties": {
      "to": { "type": "string", "format": "email" },
      "template_id": { "type": "string" },
      "context": { "type": "object" }
    }
  },
  "output_schema": {
    "type": "object",
    "required": ["provider_message_id", "status"]
  },
  "preconditions": ["domain_allowed", "template_exists"],
  "idempotency_key": "to:template_id:hash(context)",
  "errors": [
    { "code": "ERR_EMAIL_DOMAIN_BLOCKED", "retryable": false },
    { "code": "ERR_EMAIL_PROVIDER_RATE_LIMIT", "retryable": true }
  ]
}
```
