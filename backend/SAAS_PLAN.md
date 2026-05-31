# SAAS_PLAN.md

Quick execution plan to evolve this project into a SaaS conversational-agent platform.

## Goal

Allow companies to create and deploy a business agent in minutes:
upload documents -> build RAG + intent routing -> deploy to WhatsApp/web chat.

## Product scope (MVP)

1. Auth + workspace onboarding (`register`, `login`, session management).
2. Multi-tenant workspace (`organization_id`, `agent_id`) linked to authenticated users.
3. Agent builder wizard (React): name, files, prompt/tone, deploy.
4. Async knowledge ingestion and indexing pipeline.
5. Chat API with session memory + tenant isolation.
6. WhatsApp deployment with delivery tracking and retries.

## Architecture (MVP)

- Frontend: React/Next.js dashboard.
- API: FastAPI (existing), modular services.
- Queue/Workers: Redis-backed tasks for ingestion/indexing.
- DB: Postgres for tenants, agents, docs, deployments, conversations.
- Session/cache: Redis.
- Retrieval backend: start with `dense_openai` fallback `tfidf`; evolve to vector DB (Qdrant/pgvector).

## Key frontend modules

- Auth pages: register, login, forgot/reset password.
- Organization onboarding and selector.
- Agents list + create/edit.
- Agent wizard (4 steps):
  - Basic config
  - Knowledge upload
  - Behavior/prompt config
  - Deployment channels
- Deployments page (WhatsApp/Webchat).
- Conversations inbox + filters + escalation queue.
- Analytics dashboard (volume, fallback rate, delivery failures).

### Frontend foundation status

- ✅ Foundation SDD change started: `nextjs-frontend-foundation`
- Scope activo: scaffold Next.js + auth pages + onboarding + protected shell
- Pendiente: implementación de módulos avanzados (wizard, analytics, inbox)

## Backend milestones

### Phase 1: Identity and access foundation
- Implement `register`, `login`, refresh token, logout.
- Introduce user model, password hashing, email verification hooks.
- Create organization during onboarding and link first owner user.
- Enforce tenant context resolution from auth token in each request.

#### Rollout gates (chat auth migration)
- Gate A: habilitar endpoints `/auth/*`, `/me`, `/orgs` con `CHAT_AUTH_COMPAT_MODE=true`.
- Gate B: migrar clientes de `/chat` a flujo con Bearer token.
- Gate C: desactivar compatibilidad (`CHAT_AUTH_COMPAT_MODE=false`) y exigir auth en `/chat`.

### Phase 2: Multi-tenant hardening
- Add strict tenant checks to all data access and retrieval paths.
- Persist chat/session metadata in Postgres (beyond Redis ephemeral memory).
- Add RBAC (`owner`, `admin`, `operator`).

### Phase 3: Ingestion/index jobs
- Add document status lifecycle: `uploaded -> processing -> indexed -> failed`.
- Run chunking + indexing in background workers.
- Add incremental reindex by document/agent.

### Phase 4: Channel deployment
- Persist WhatsApp deployment credentials by agent.
- Add outbound status and retry history.
- Add webchat snippet generation and domain allowlist.

### Phase 5: SaaS operations
- Billing plans and usage counters.
- Observability (traces, latency, fallback, cost).
- Admin controls for limits and abuse protection.

## API capabilities to add

- `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`.
- `GET /me`, `POST /orgs`, `POST /orgs/switch`.
- `POST /agents`, `GET /agents`.
- `POST /agents/{id}/documents` (upload + process job).
- `POST /agents/{id}/index/rebuild`.
- `POST /agents/{id}/deploy/whatsapp`.
- `GET /agents/{id}/conversations`.
- `GET /agents/{id}/analytics`.

## Success criteria

- Secure login with tenant-scoped token/session context.
- Tenant-safe by default in all retrieval and conversation routes.
- New agent ready to answer in less than 10 minutes.
- WhatsApp message delivery > 99% with retry support.
- Fallback/escalation observable and actionable from dashboard.
