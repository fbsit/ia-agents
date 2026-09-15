# AI Engine Internal Contract (Phase 1)

This document defines the internal request/response contract between `platform-api` (Spring Boot) and the AI engine (`backend/chat_api.py`).

## Scope for Phase 1-2

- Define canonical payloads for agent creation and agent chat.
- Define mandatory tenant and trace headers.
- Define transport config keys in Spring.
- Implement Spring proxy endpoints:
  - `POST /agents`
  - `GET /agents`
  - `PATCH /agents/{agentId}`
  - `DELETE /agents/{agentId}`
  - `GET /agents/{agentId}/documents`
  - `POST /agents/{agentId}/documents`
  - `DELETE /agents/{agentId}/documents/{documentId}`
  - `POST /agents/{agentId}/index/rebuild`
  - `GET /agents/{agentId}/index/status`
  - `GET /agents/{agentId}/setup-status`
  - `GET /agents/{agentId}/feedback/summary`
  - `GET /agents/{agentId}/widget-config`
  - `GET /agents/{agentId}/channels/whatsapp/config`
  - `PUT /agents/{agentId}/channels/whatsapp/config`
  - `POST /agents/{agentId}/channels/whatsapp/validate`
  - `POST /agents/{agentId}/chat`

## Internal headers

- `X-Company-Id`: effective tenant key.
- `X-Org-Id`: organization context resolved by Spring.
- `X-User-Id`: authenticated user in Spring.
- `X-Request-Id`: correlation id propagated end-to-end.
- `X-Platform-Signature`: HMAC signature for trusted gateway requests (phase 4 hardening).
- `X-Platform-Timestamp`: unix epoch seconds used in signature verification.

### Signature scheme (active)

- Algorithm: `HMAC-SHA256`.
- Secret source:
  - Spring: `app.ai-engine.shared-secret`
  - Python: `AI_ENGINE_SHARED_SECRET`
- Canonical string:

```text
{timestamp}\n{company_id}\n{org_id}\n{user_id}\n{request_id}
```

- Signature format: lowercase hex digest in `X-Platform-Signature`.
- Timestamp tolerance in Python: `+- 300s`.

## Agent create payload (Spring -> Python)

Internal route in Python used by Spring:

- `POST /internal/ai/agents`

Request body (`AiAgentCreateRequest`):

- `name`
- `objective`
- `tone`
- `description`
- `rag_backend`
- `generation_provider`
- `use_openai_generation`
- `openai_model`
- `clubhx_tenant_id` (opcional; UUID del tenant en ClubHx/whsflow: habilita el flujo de venta del agente)
- `clubhx_shop_domain` (opcional; dominio con el que la tienda esta conectada en ClubHx)

Response body (`AiAgentResponse`):

- `agent_id`
- `org_id`
- `company_id`
- `name`
- `objective`
- `tone`
- `description`
- `rag_backend`
- `generation_provider`
- `use_openai_generation`
- `openai_model`
- `knowledge_dir`
- `index_path`
- `indexed_at`
- `documents_count`
- `clubhx_tenant_id`
- `clubhx_shop_domain`
- `commerce_enabled`

## Agent chat payload (Spring -> Python)

Internal route in Python used by Spring:

- `POST /internal/ai/agents/{agent_id}/chat`

## Agent list payload (Spring -> Python)

Internal route in Python used by Spring:

- `GET /internal/ai/agents`

Response body:

- `List<AiAgentResponse>`

## Agent update payload (Spring -> Python)

Internal route in Python used by Spring:

- `PATCH /internal/ai/agents/{agent_id}`

Request body (`AiAgentUpdateRequest`):

- `name`
- `objective`
- `tone`
- `description`
- `rag_backend`
- `generation_provider`
- `use_openai_generation`
- `openai_model`

Response body:

- `AiAgentResponse`

## Agent delete payload (Spring -> Python)

Internal route in Python used by Spring:

- `DELETE /internal/ai/agents/{agent_id}`

Response body (`AiDeleteResponse`):

- `status`
- `agent_id`

## Agent documents payload (Spring -> Python)

Internal route in Python used by Spring:

- `GET /internal/ai/agents/{agent_id}/documents`
- `POST /internal/ai/agents/{agent_id}/documents`
- `DELETE /internal/ai/agents/{agent_id}/documents/{document_id}`

Response body:

- `List<AiAgentDocumentResponse>`

Upload request (`AiAgentDocumentUploadRequest`):

- `filename`
- `content_base64`
- `operational_section`

Delete response:

- `status`
- `document_id`

## Agent index payloads (Spring -> Python)

Internal routes in Python used by Spring:

- `POST /internal/ai/agents/{agent_id}/index/rebuild`
- `GET /internal/ai/agents/{agent_id}/index/status`

Response bodies:

- rebuild: `AiAgentIndexResponse`
- status: `AiAgentIndexStatusResponse`

## Agent setup/widget/channels payloads (Spring -> Python)

Internal routes in Python used by Spring:

- `GET /internal/ai/agents/{agent_id}/setup-status`
- `GET /internal/ai/agents/{agent_id}/feedback/summary`
- `GET /internal/ai/agents/{agent_id}/widget-config`
- `GET /internal/ai/agents/{agent_id}/channels/whatsapp/config`
- `PUT /internal/ai/agents/{agent_id}/channels/whatsapp/config`
- `POST /internal/ai/agents/{agent_id}/channels/whatsapp/validate`

Additional header used for public URL composition in these routes:

- `X-Public-Base-Url`

Request body (`AiAgentChatRequest`):

- `message`
- `top_k`
- `session_id`
- `use_openai_generation`
- `generation_provider`
- `generation_model`

Response body (`AiAgentChatResponse`):

- `agent_id`
- `company_id`
- `session_id`
- `answer`
- `sources[]`
- `intent_label`
- `route`
- `route_reason`
- `response_mode`
- `fallback_applied`
- `retrieval_min_score`

## Error envelope

When Python returns a controlled error, Spring maps it with:

- `code`
- `detail`
- `request_id`

Type reference in Spring: `AiErrorResponse`.

## Spring configuration keys

- `app.ai-engine.base-url`
- `app.ai-engine.path-prefix` (default `/api`; the Python app mounts every router, including `/internal/ai/*`, under that prefix)
- `app.ai-engine.connect-timeout`
- `app.ai-engine.read-timeout`
- `app.ai-engine.shared-secret`

Mapped by `AiEngineProperties`.
