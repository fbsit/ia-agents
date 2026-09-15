# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es este repo

Monorepo de una plataforma SaaS multi-tenant de agentes conversacionales (arquitectura "Option A", ver `AGENTS.md` §10):

| Dir | Rol | Puerto |
|---|---|---|
| `backend/` | **AI Engine** — FastAPI + LangGraph + RAG + scikit-learn. Dueño de agentes, conocimiento, retrieval, generación LLM, workflow de checkout comercial y evaluación. Persiste agentes/usuarios/orgs por sí mismo (SQLite por defecto). | 8080 (docs) / 8000 (Docker) |
| `platform-api/` | **API Gateway/BFF en Spring Boot** — auth, tenancy, catálogo de skills/flows; proxea los endpoints de agentes a Python vía `/internal/ai/*` con headers HMAC. | 8081 |
| `frontend/` | **Consola Next.js 16** — habla solo con `platform-api` (`NEXT_PUBLIC_PLATFORM_API_BASE_URL`, default `:8081`). Nunca llama a Python directo. | 3000 |
| `archive/` | Frontend legacy, solo referencia. | — |

Los mapas detallados por proyecto están en `backend/CLAUDE.md` (módulo por módulo, env vars, flujo de request) y `frontend/CLAUDE.md`. `AGENTS.md` en la raíz tiene las convenciones globales y la decisión Option A. Leer esos archivos antes de editar el árbol correspondiente; este archivo cubre solo hechos transversales y comandos.

Los directorios con nombre hash (`0e673e82…`, `ebf57484…`, `backend/9b825f91…`) son artefactos de storage de conocimiento/documentos por tenant (clave `company_id`), no código.

## Comandos

Todos desde la raíz del repo salvo que se indique. Python 3.13 en uso local; el Dockerfile usa 3.12.

### Backend (Python)

```bash
# setup (desde backend/)
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
copy .env.example .env   # AUTH_SECRET_KEY es obligatoria

# correr API (las rutas se montan bajo /api, health en /health)
uvicorn backend.chat_api:app --host 0.0.0.0 --port 8080

# tests — los archivos de test insertan backend/src en sys.path, así que esto funciona desde la raíz
python -m pytest backend/tests
python -m pytest backend/tests/test_whatsapp_checkout_graph.py
python -m pytest backend/tests/test_whatsapp_checkout_resolver.py::test_resolver_handles_payment_to_boleta_to_order_confirmation
python -m pytest backend/tests -k checkout

# chequeo de sintaxis (no hay linter configurado)
python -m compileall backend/chat_api.py backend/src

# stack Docker (API + Redis + worker de evaluación)
cd backend && docker compose up --build
```

**Los módulos CLI necesitan `backend/src` en el path.** A diferencia de `chat_api.py` y los tests, `clasificacion_langchain/cli/*.py` no insertan `sys.path`, así que desde la raíz:

```bash
# PowerShell
$env:PYTHONPATH="backend/src"; python -m clasificacion_langchain.cli.train_model --source csv --csv-path backend/data/sample_tweets.csv
# bash
PYTHONPATH=backend/src python -m clasificacion_langchain.cli.build_rag_index --knowledge-dir backend/knowledge_base --backend auto --index-path backend/models/rag_index.joblib
PYTHONPATH=backend/src python -m clasificacion_langchain.cli.train_model --task intent --source csv --csv-path backend/data/intent_router_dataset_template.csv --model-path backend/models/intent_router.joblib
PYTHONPATH=backend/src python -m clasificacion_langchain.cli.ask_hybrid_agent --question "..." --company-id empresa_a --index-path backend/models/rag_index.joblib
PYTHONPATH=backend/src python -m clasificacion_langchain.cli.evaluation_worker
PYTHONPATH=backend/src python -m clasificacion_langchain.cli.migrate_agent_documents --backend s3 --db-path data/local_api.db --dry-run
```

Los defaults de los CLI (`--csv-path`, `--model-path`) asumen cwd en la raíz del repo. Un launcher único `python -m clasificacion_langchain.cli <cmd>` es el objetivo planificado (`backend/architecture/CLI_STRATEGY.md`) pero todavía no existe.

### platform-api (Spring Boot, JDK 21)

```bash
cd platform-api
.\mvnw.cmd spring-boot:run     # o ./run.ps1 — setea JAVA_HOME al temurin21 de scoop y carga .env
.\mvnw.cmd test
```

`app.auth.jwt.secret` debe tener ≥32 chars. `app.ai-engine.shared-secret` debe ser igual a `AI_ENGINE_SHARED_SECRET` en Python. `HttpAiEngineClient` arma las URLs como `base-url + path-prefix + /internal/ai/...`; el path prefix por defecto es `/api` (`AI_ENGINE_PATH_PREFIX`) porque Python monta todas sus rutas bajo ese prefijo.

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
npm run build
npm run lint      # ESLint 9 flat config; no hay script de test
```

## Hechos de arquitectura que cruzan archivos

**Shim HTTP fino, servicios gordos.** `backend/chat_api.py` solo arregla `sys.path` e importa `clasificacion_langchain.api.app:app`. `api/app.py` construye FastAPI, monta un router por dominio (`api/routes/*.py`) bajo `/api`, y guarda un único `RuntimeContainer` (de `api/runtime.py:build_runtime`) en `app.state.runtime`. Los routers solo validan payloads, resuelven auth/tenant/acceso al agente vía `api/dependencies.py`, llaman a un servicio y serializan. **Nunca agregar lógica de negocio en `chat_api.py`, `api/app.py` ni en un router** — `backend/CHAT_API_DIRECTIVE.md` es el conjunto de reglas vinculante. El comportamiento nuevo va en `agents/*`, `agents/commerce/*`, `chat/*`, `channels/*`, `rag/*`.

**El aislamiento de tenant es por `company_id` en todo lado.** Claves de sesión, fingerprints de la política conversacional, índices de retrieval, filas de auditoría, paths de storage de documentos y directorios de conocimiento están todos scopeados por `company_id` (+ `agent_id` / `session_id`). `TenancyService.resolve_company_id()` decide el tenant efectivo a partir del request, la org activa del principal, o una única membership. No introducir un camino que lo saltee.

**Flujo de un request de chat de agente** (`AgentService.chat()` en `agents/service.py`, ~1300 líneas, es el coordinador): `AgentIntentOrchestrator.decide()` → `ConversationPolicyEngine` (detección de repetición por SHA1; 3ra repetición = respuesta genérica sin LLM, 4ta+ = respuesta cacheada) → `RoleContext` desde `agents/role_knowledge.py` (roles `whatsapp_seller` / `web_support_seller`, conocimiento compartido en `backend/knowledge/shared/`) → `RAGPipeline.answer()` → `enforce_channel_response_contract()` (WhatsApp ≈420 chars, web ≈560) → auditoría → post-procesamiento commerce (timeout/resume). El canal (`whatsapp|widget|api|internal`) se resuelve *antes* de la lógica del agente y cambia el contrato de respuesta y el workflow permitido.

**El checkout comercial es su propio LangGraph** en `agents/commerce/`: plan → guard → execute_or_block → map, sobre un dataclass `WhatsAppCheckoutState` que se persiste en el `SessionSummary` de 38 campos vía `persistence.py`. Las transiciones de etapa las valida `agents/commerce_workflow.py:resolve_transition`; las llamadas a tools las filtra `guards.py` antes de pegarle a ClubHx (`integrations/clubhx.py`). La mayoría de la suite de tests cubre este paquete.

**Las escaleras de fallback son deliberadas.** Backend RAG `auto` → dense OpenAI si hay key, si no TF-IDF; fallas de dense/hybrid caen a TF-IDF en vez de 500. Falla del LLM remoto cae a `ExtractiveAnswerGenerator` con un aviso. Los providers LLM (OpenAI, Anthropic) se llaman con `urllib` crudo; intencionalmente no hay SDK `openai`/`anthropic` en `requirements.txt`.

**Patrón repository/store.** Cada preocupación de persistencia es un `Protocol` con implementaciones InMemory + SQLite + Postgres (o Redis / Local + S3) elegidas por env (`PERSISTENCE_BACKEND`, `CHAT_SESSION_BACKEND`, `DOC_STORAGE_BACKEND`, `EVAL_*`). Para agregar un backend nuevo, implementar el protocol y cablearlo en `runtime/builders.py` / `api/support/runtime_builders.py`, no ramificar dentro de los servicios. Con `DOC_STORAGE_BACKEND=s3`, `RoutedDocumentStorage` tambien persiste los indices `.joblib` en el bucket (`<prefix>/indexes/`) y `AgentService.ensure_index_local()` los baja a disco cuando faltan: en Railway el filesystem es efimero.

**Contrato Spring ↔ Python** documentado en `platform-api/docs/ai-engine-internal-contract.md`: rutas internas bajo `/internal/ai/*` en `api/routes/internal.py` (las vistas de índice, setup, widget y WhatsApp se comparten con las rutas autenticadas vía `api/support/agent_views.py`), headers `X-Company-Id`, `X-Org-Id`, `X-User-Id`, `X-Request-Id`, y HMAC-SHA256 en `X-Platform-Signature` sobre `timestamp\ncompany_id\norg_id\nuser_id\nrequest_id` (tolerancia ±300s). Cambiar ambos lados juntos; la identidad del tenant debe propagarse sin mapeos con pérdida. Los webhooks de WhatsApp son propiedad de un channel gateway externo; Python solo expone `/internal/ai/media/transcriptions` y `/internal/ai/agents/{id}/chat` para él.

## Convenciones que vale saber (más allá de PEP 8)

- `from __future__ import annotations` en todos los módulos; `TypedDict(total=False)` para estado LangGraph, `dataclass(slots=True)` para config/containers.
- Logs estructurados: `logger.info("event_name key=value key2=value2")`; el ruteo commerce usa `_trace_route()`.
- Env parseado con `os.getenv("X", "default")` + `_env_bool()` explícito; nunca hardcodear company ids, verify tokens ni nombres de modelo en rutas.
- ML: fit de transforms solo en el split de train, `random_state` explícito, un único artefacto joblib con pipeline + encoder + métricas.
- Los textos de cara al usuario (CLI, Streamlit, respuestas del agente) están en español.
- Los tests viven en `backend/tests/test_*.py` y son pytest plano sin conftest ni fixtures; cada archivo bootstrapea `sys.path` por su cuenta.

## Desfasajes conocidos a tener en cuenta

- El worker de `backend/docker-compose.yml` corre `python evaluation_worker.py`, pero ese script de raíz se eliminó a favor de `clasificacion_langchain.cli.evaluation_worker`. El worker de Docker está roto hasta que se actualice el comando del compose.
- Las docs (`backend/README.md`, `backend/CLAUDE.md`) listan los endpoints del backend sin el prefijo `/api` que `api/app.py` sí aplica.
- `AGENTS.md` menciona `npm run test` para el frontend; ese script no existe.
- `backend/CLAUDE.md` referencia `docs/whatsapp-checkout-workflow.md`, que ya no existe, y es anterior a varios módulos de `agents/commerce/` (`checkout_resolver.py`, `intent_parser.py`, `extractors.py`, `routing.py`, `widget_payload.py`).
- Generados/ignorados: `backend/models/`, `backend/logs/`, `backend/.env`, `frontend/.env.local`. Los `hs_err_pid*.log` / `replay_pid*.log` de la raíz son crash dumps de la JVM, se pueden ignorar.
