# Reglas de decision

## Metadata

- company_id: REEMPLAZAR_COMPANY_ID
- version: 2026-04-03
- owner: nombre.apellido

## Tabla principal

| rule_id | priority | if | then | else | requires_approval | reason_code |
| --- | --- | --- | --- | --- | --- | --- |
| RULE-001 | 10 | role=owner AND amount<=50000 AND status=pending | action=approve_refund | action=request_manual_review | false | APPROVE_OWNER_LIMIT |
| RULE-002 | 20 | role=supervisor AND amount<=20000 AND risk_score<0.4 | action=update_status_approved | action=escalate_to_human | false | SUPERVISOR_LOW_RISK |
| RULE-003 | 90 | risk_score>=0.8 | action=block_and_notify | action=escalate_to_human | true | HIGH_RISK_BLOCK |

## Fallback

- Default action: `escalate_to_human`
- Default reason_code: `NO_RULE_MATCH`
- Audit required: true
