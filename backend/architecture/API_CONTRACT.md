# API Contract

Documentacion operativa de la API modular del AI Engine.

## 1. Entry Point

- Codigo: `backend/chat_api.py`
- App oficial: `backend/src/clasificacion_langchain/api/app.py`
- Prefijo publico principal: `/api`
- Endpoints de infraestructura fuera del prefijo: `/health`, `/docs`, `/redoc`, `/openapi.json`

## 2. OpenAPI nativo

FastAPI ya expone documentacion viva:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

## 3. Responsabilidad por capa

### `api/`

Responsabilidad:

- exponer HTTP
- validar payloads
- resolver auth/tenant/access
- delegar a servicios

Subpartes:

- `app.py` — composicion FastAPI y registro de routers
- `runtime.py` — construccion del container de servicios
- `dependencies.py` — auth, tenant, acceso a agente, contexto
- `routes/*` — endpoints agrupados por dominio
- `support/*` — helpers HTTP/serializacion/widget/media

### `runtime/`

Responsabilidad:

- construir servicios y stores compartidos
- centralizar defaults de entorno

### `operations/`

Responsabilidad:

- workers
- loops operativos
- jobs async

### `integrations/`

Responsabilidad:

- clientes externos
- contratos con terceros

### `agents/`

Responsabilidad:

- lifecycle del agente
- RAG por agente
- workflow comercial
- chat por agente
- evaluacion y feedback

### `chat/`

Responsabilidad:

- chat tenant-based legacy
- memoria/sesiones/summaries

### `channels/`

Responsabilidad:

- parseo de canales
- clientes de canal
- idempotencia de webhooks

### `shared/ml/`

Responsabilidad:

- bloque ML/hybrid legacy reutilizable
- entrenamiento
- router de intents
- grafos de inferencia e hibrido

## 4. Superficie HTTP

## 4.1 System

### `GET /health`

Uso:

- healthcheck de infraestructura

## 4.2 Auth

Base:

- `/api/auth`

Endpoints:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/me`

Responsabilidad:

- identidad de usuario
- emision y refresh de tokens
- contexto autenticado

## 4.3 Tenancy

Endpoints:

- `POST /api/orgs`
- `GET /api/orgs`

Responsabilidad:

- onboarding de organizacion
- membresias
- resolucion de tenant

## 4.4 Chat Legacy

Endpoints:

- `POST /api/chat`

Responsabilidad:

- chat general tenant-based
- fallback cuando el indice no esta listo: `route_reason=rag_not_ready`

## 4.5 Agents

Base:

- `/api/agents`

Endpoints:

- `POST /api/agents`
- `GET /api/agents`
- `POST /api/agents/{agent_id}/chat`

Responsabilidad:

- crear/listar agentes
- resolver chat por agente
- aplicar rol, memoria, RAG y workflow

## 4.6 Documents

Endpoints:

- `GET /api/agents/{agent_id}/documents`
- `POST /api/agents/{agent_id}/documents`
- `DELETE /api/agents/{agent_id}/documents/{document_id}`
- `GET /api/agents/{agent_id}/documents/{document_id}/content`

Responsabilidad:

- ingestion de conocimiento
- lectura de contenido
- lifecycle del documento

## 4.7 Indexing

Endpoints:

- `POST /api/agents/{agent_id}/index/rebuild`
- `GET /api/agents/{agent_id}/index/status`

Responsabilidad:

- reconstruccion del indice RAG
- estado operativo del retrieval

## 4.8 Setup

Endpoints:

- `GET /api/agents/{agent_id}/setup-status`

Responsabilidad:

- medir readiness del agente
- indicar siguiente paso operativo

## 4.9 Settings

Base:

- `/api/settings`

Endpoints:

- `GET /api/settings/llm`
- `PUT /api/settings/llm`

Responsabilidad:

- configuracion tenant-aware de provider/modelos/keys

## 4.10 Feedback

Endpoints:

- `POST /api/agents/{agent_id}/feedback`
- `GET /api/agents/{agent_id}/feedback/summary`

Responsabilidad:

- feedback de calidad de respuesta
- resumen por agente

## 4.11 Evaluations

Endpoints:

- `GET /api/agents/{agent_id}/evaluation/dataset`
- `POST /api/agents/{agent_id}/evaluation/dataset`
- `POST /api/agents/{agent_id}/evaluation/run`
- `GET /api/agents/{agent_id}/evaluation/runs`
- `GET /api/agents/{agent_id}/evaluation/runs.csv`
- `GET /api/agents/{agent_id}/evaluation/compare-latest`

Responsabilidad:

- dataset offline
- corridas de evaluacion
- comparacion de runs

## 4.12 Jobs

Endpoints:

- `POST /api/agents/{agent_id}/evaluation/run-async`
- `GET /api/agents/{agent_id}/jobs/{job_id}`

Responsabilidad:

- ejecucion asincrona de evaluaciones
- estado de jobs

## 4.13 Retrieval

Endpoints:

- `GET /api/agents/{agent_id}/retrieval/compare`
- `POST /api/agents/{agent_id}/retrieval/decision`
- `GET /api/agents/{agent_id}/retrieval/decision-history`

Responsabilidad:

- comparativa de backend RAG
- decisiones historicas de retrieval

## 4.14 Reports

Base:

- `/api/reports`

Endpoints:

- `GET /api/reports/chat/summary`
- `GET /api/reports/chat/cost-estimate`
- `GET /api/reports/retrieval/summary`

Responsabilidad:

- analitica agregada
- costo estimado
- salud del retrieval

## 4.15 Channels / WhatsApp Config

Endpoints:

- `GET /api/agents/{agent_id}/channels/whatsapp/config`
- `PUT /api/agents/{agent_id}/channels/whatsapp/config`
- `POST /api/agents/{agent_id}/channels/whatsapp/validate`

Responsabilidad:

- metadata de despliegue de canal
- readiness del canal

## 4.16 Widget

Endpoints:

- `GET /api/agents/{agent_id}/widget-config`
- `POST /api/public/widget/chat`

Responsabilidad:

- configuracion del widget
- chat publico embebido
- rate limit y token del widget

## 4.17 Internal AI

Base:

- `/api/internal/ai`

Endpoints:

- `GET /api/internal/ai/settings/llm`
- `PUT /api/internal/ai/settings/llm`
- `POST /api/internal/ai/agents/{agent_id}/chat`
- `POST /api/internal/ai/media/transcriptions`

Responsabilidad:

- integracion interna entre servicios
- auth por headers firmados
- transcripcion de audio
- invocacion interna del agente

## 4.18 WhatsApp Webhooks

Endpoints:

- `GET /api/internal/ai/agents/{agent_id}/channels/whatsapp/webhook`
- `POST /api/internal/ai/agents/{agent_id}/channels/whatsapp/webhook`

Responsabilidad:

- verificacion webhook
- recepcion de mensajes
- parseo + deduplicacion + respuesta

## 5. Flujo canónico de request conversacional

Todos los canales deberian converger a este contrato interno:

```json
{
  "company_id": "...",
  "agent_id": "...",
  "session_id": "...",
  "message": "...",
  "channel": "whatsapp|widget|api|internal",
  "visitor_id": "...",
  "external_user_id": "...",
  "metadata": {}
}
```

## 6. Notas operativas

- La API puede arrancar aunque falte el indice RAG.
- Si falta el indice, `POST /api/chat` degrada a fallback con `route_reason=rag_not_ready`.
- Si falta `AUTH_SECRET_KEY`, usa fallback de desarrollo y loguea warning. Eso no es aceptable para produccion.

## 7. Proxima mejora

Unificar el CLI en un solo launcher:

```bash
python -m clasificacion_langchain.cli <command>
```

Comandos objetivo:

- `train`
- `index`
- `ask`
- `migrate-docs`
- `eval-worker`
- `streamlit`
