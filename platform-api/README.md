# platform-api

Spring Boot API Gateway/BFF for Option A architecture.

## Scope (current)

- Owns user auth and tenancy onboarding endpoints for frontend.
- Keeps Python backend as AI Engine (LangChain/RAG/chat).
- AI proxy migration is active: contract + Spring proxy for agent create/chat.

## Implemented endpoints

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`
- `POST /orgs`
- `GET /orgs`
- `POST /agents` (proxied to Python AI Engine)
- `GET /agents` (proxied to Python AI Engine)
- `PATCH /agents/{agentId}` (proxied to Python AI Engine)
- `DELETE /agents/{agentId}` (proxied to Python AI Engine)
- `GET /agents/{agentId}/documents` (proxied to Python AI Engine)
- `POST /agents/{agentId}/documents` (proxied to Python AI Engine)
- `DELETE /agents/{agentId}/documents/{documentId}` (proxied to Python AI Engine)
- `POST /agents/{agentId}/index/rebuild` (proxied to Python AI Engine)
- `GET /agents/{agentId}/index/status` (proxied to Python AI Engine)
- `POST /agents/{agentId}/chat` (proxied to Python AI Engine)
- `GET /agents/{agentId}/setup-status` (proxied to Python AI Engine)
- `GET /agents/{agentId}/feedback/summary` (proxied to Python AI Engine)
- `GET /agents/{agentId}/widget-config` (proxied to Python AI Engine)
- `GET /agents/{agentId}/channels/whatsapp/config` (proxied to Python AI Engine)
- `PUT /agents/{agentId}/channels/whatsapp/config` (proxied to Python AI Engine)
- `POST /agents/{agentId}/channels/whatsapp/validate` (proxied to Python AI Engine)

## Run

From `platform-api/`:

```bash
.\mvnw.cmd spring-boot:run
```

Default local ports:

- `server.port=8081` (Spring)
- `app.ai-engine.base-url=http://localhost:8080` (Python AI Engine)
- `app.ai-engine.path-prefix=/api` (Python monta `/internal/ai/*` bajo `/api`)

## Config

`src/main/resources/application.properties`:

- `app.auth.jwt.secret` (must be >= 32 chars)
- `app.auth.access-token-minutes`
- `app.auth.refresh-token-days`
- `app.cors.allowed-origins`
- `app.ai-engine.base-url`
- `app.ai-engine.path-prefix`
- `app.ai-engine.connect-timeout`
- `app.ai-engine.read-timeout`
- `app.ai-engine.public-base-url` (env `AI_ENGINE_PUBLIC_BASE_URL`, default = `app.ai-engine.base-url`) URL publica del AI Engine que se entrega en el widget embebible y en el webhook de WhatsApp. No se adivina desde el Origin/Referer de quien pide la config (esa consola no es el AI Engine)
- `app.ai-engine.shared-secret`
- `app.integration.service-token` (env `PLATFORM_INTERNAL_SERVICE_TOKEN`) token bearer para que un servicio externo (sin usuario logueado) llame a los endpoints de agentes, mandando `company_id`/`org_id` explicitos en vez de resolverlos de un JWT
- `app.integration.allowed-company-id`, `app.integration.allowed-org-id` (env `PLATFORM_INTEGRATION_ALLOWED_COMPANY_ID`, `PLATFORM_INTEGRATION_ALLOWED_ORG_ID`) acotan ese token a un solo tenant. **Obligatorios los dos si se usa el token de integracion**: sin ellos (o si el `company_id`/`org_id` del pedido no coincide) se rechaza con 400. El token por si solo no identifica de quien es ni para que tenant es valido, asi que sin este acotamiento cualquiera que lo tenga podria pedirse cualquier organizacion de la plataforma

Si configuras `app.ai-engine.shared-secret`, el backend Python debe tener el mismo valor en `AI_ENGINE_SHARED_SECRET`.

Internal contract reference:

- `docs/ai-engine-internal-contract.md`

## Notes

- Current storage uses SQLite via JDBC repositories.
- This is an incremental migration step; persistence and policy hardening come next.
