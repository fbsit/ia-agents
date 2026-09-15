# Clasificacion de Tweets con LangChain + LangGraph

Este proyecto reconstruye tu notebook de 2014 en una arquitectura mantenible y demo-ready.

## Que mejora respecto al notebook original

- Sin credenciales hardcodeadas (usa `.env`).
- Sin data leakage (el vectorizador se entrena solo con train).
- Encoding correcto de etiquetas (fit en train, transform en test).
- Pipeline reproducible con artefacto versionable (`joblib`).
- Flujo de inferencia orquestado con `LangGraph`.
- Demo web con `Streamlit`.

## Stack

- `LangChain` para componentes de pipeline/runnables.
- `LangGraph` para orquestar el flujo de inferencia.
- `scikit-learn` para TF-IDF + clasificador lineal.
- `nltk` para normalizacion en espanol.

## Estructura

```text
clasificacion-langchain-demo/
  backend/
    chat_api.py
    requirements.txt
    .env.example
    data/sample_tweets.csv
    src/clasificacion_langchain/
      cli/
      data_sources.py
      text_cleaning.py
      training.py
      inference_graph.py
  frontend/
```

## Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Frontend Next.js (foundation)

El frontend oficial del proyecto esta en `../frontend`.

### Setup frontend

```bash
cd ../frontend
npm install
copy .env.local.example .env.local
```

Configura en `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`

### Correr frontend

```bash
cd ../frontend
npm run dev
```

Dashboard principal:

- `http://localhost:3000/dashboard` (o el puerto que use tu entorno)
- Desde ahi puedes:
  - crear agentes por organizacion,
  - subir documentos (`txt`, `md`, `csv`, `json`),
  - reconstruir indice RAG,
  - chatear con el agente y activar respuesta mas humana con OpenAI.

### Flujo local recomendado (backend + frontend)

1. Levanta backend:
    - `uvicorn backend.chat_api:app --host 0.0.0.0 --port 8080`
2. En otra terminal levanta frontend:
   - `cd ../frontend && npm run dev`

## Entrenamiento

### Opcion 1: dataset de ejemplo (rapido)

```bash
python -m clasificacion_langchain.cli.train_model --source csv --csv-path backend/data/sample_tweets.csv
```

### Opcion 2: desde MySQL (como tu flujo original)

1. Copia `.env.example` a `.env` y completa valores.
2. Ejecuta:

```bash
python -m clasificacion_langchain.cli.train_model --source mysql
```

## Demo

```bash
streamlit run backend/src/clasificacion_langchain/cli/streamlit_demo.py
```

## Nota tecnica

Esta version usa ML clasico para mantener costo cero de inferencia y velocidad en demo.
Si despues queres, se puede enchufar un LLM para explicaciones mas ricas sin tocar la parte de clasificacion.

## Extension: agente hibrido (Intent Router + RAG)

Se agrego una arquitectura modular para evolucionar el proyecto a casos multiempresa:

- `src/clasificacion_langchain/intent_router.py`: reutiliza el pipeline clasico para rutear intenciones.
- `src/clasificacion_langchain/rag/`: ingestion, chunking, indice TF-IDF vectorial y generacion.
- `src/clasificacion_langchain/agent_tools.py`: tools reutilizables para flows de agentes.
- `src/clasificacion_langchain/hybrid_agent_graph.py`: grafo LangGraph que decide entre RAG o fallback segun confianza.

Guia recomendada para escalar RAG a nivel SaaS (feedback loop, hybrid retrieval, vector DB, KPIs):

- `RAG_OPERATING_GUIDE.md`
- `RAG_KNOWLEDGE_INDEX_PLAYBOOK.md` (contrato homologado para conocimiento, indice, pruebas, setup y deploy)

### Estructura esperada de conocimiento

```text
knowledge_base/
  empresa_a/
    faq.md
    politicas.txt
  empresa_b/
    catalogo.csv
```

### Construir indice RAG

```bash
python -m clasificacion_langchain.cli.build_rag_index --knowledge-dir backend/knowledge_base --index-path backend/models/rag_index.joblib
```

Backends disponibles:

- `--backend auto`: usa `dense_openai` si existe `OPENAI_API_KEY`, si no usa `tfidf`.
- `--backend tfidf`: vectorizacion clasica local (sin costo externo).
- `--backend dense_openai`: embeddings densos con OpenAI (mejor calidad semantica).
- `--backend hybrid`: fusiona `tfidf + dense_openai` con ranking hibrido (RRF).

Ejemplo productivo recomendado (embeddings):

```bash
python -m clasificacion_langchain.cli.build_rag_index --knowledge-dir backend/knowledge_base --backend dense_openai --embedding-model text-embedding-3-small
```

### Entrenar router de intencion

```bash
python -m clasificacion_langchain.cli.train_model --task intent --source csv --csv-path backend/data/intent_router_dataset_template.csv --model-path backend/models/intent_router.joblib
```

### Probar agente hibrido por CLI

```bash
python -m clasificacion_langchain.cli.ask_hybrid_agent --question "Cual es el horario de soporte?" --company-id empresa_a --index-path backend/models/rag_index.joblib
```

## API `/chat` multiempresa

Se agrego un endpoint HTTP para usar el agente con sesiones por empresa.

### Levantar API

```bash
uvicorn chat_api:app --host 0.0.0.0 --port 8080
```

### Levantar stack Docker (API + Redis + worker evaluacion)

```bash
docker compose up --build
```

Servicios:

- API: `http://localhost:8080`
- Redis: `localhost:6379`
- Worker dedicado: `python -m clasificacion_langchain.cli.evaluation_worker` dentro de `clasi-eval-worker`

Para apagar:

```bash
docker compose down
```

### Levantar worker dedicado de evaluacion (opcional recomendado)

```bash
python -m clasificacion_langchain.cli.evaluation_worker
```

Si corres worker dedicado, puedes desactivar el worker embebido del API:

```bash
set EVAL_EMBEDDED_WORKER_ENABLED=false
```

### Variables de entorno soportadas

- `RAG_INDEX_PATH` (default: `models/rag_index.joblib`)
- `INTENT_MODEL_PATH` (default: `models/intent_router.joblib`)
- `PERSISTENCE_BACKEND` (`sqlite`, `postgres` o `memory`, default `sqlite`)
- `SQLITE_DB_PATH` (default `data/local_api.db`)
- `POSTGRES_DSN` (opcional; requerido si `PERSISTENCE_BACKEND=postgres`, fallback a `DATABASE_URL`)
- `DOC_STORAGE_BACKEND` (`local` o `s3`, default `local`) para documentos de agentes
- `AGENTS_KNOWLEDGE_ROOT` (default `knowledge_base/agents`) raiz local para fallback/migraciones
- `S3_BUCKET` (requerida si `DOC_STORAGE_BACKEND=s3`)
- `S3_REGION` (opcional)
- `S3_ENDPOINT_URL` (opcional, util para MinIO o S3 compatible)
- `S3_PREFIX` (default `agents`)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (segun proveedor)
- Alias RustFS soportados (tienen prioridad sobre `S3_*`/`AWS_*`):
  - `RUSTFS_ENDPOINT`, `RUSTFS_PUBLIC_ENDPOINT`
  - `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`
  - `RUSTFS_BUCKET`, `RUSTFS_REGION`
- Con `DOC_STORAGE_BACKEND=s3` los indices RAG (`.joblib`) tambien se suben al bucket bajo `<S3_PREFIX>/indexes/<agent_id>.joblib` y se descargan al disco local cuando faltan (filesystem efimero, p. ej. Railway). Endpoints S3-compatibles usan direccionamiento por path automaticamente.
- `AGENT_ORCHESTRATOR_USE_LLM` (`true` o `false`, default `true`) para clasificar intenciones con LLM antes de rutear
- `CHAT_USE_OPENAI` (`true` o `false`, default `false`) habilita generacion LLM (OpenAI/Claude segun provider)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)
- `OPENAI_API_KEY` (requerida para `CHAT_USE_OPENAI=true` y para backend `dense_openai`)
- `RAG_GENERATION_PROVIDER` (`auto`, `openai` o `anthropic`, default `auto`)
- `RAG_NO_CONTEXT_MODE` (`strict`, `balanced` o `open`, default `strict`) controla que tan conservador responde el agente cuando no hay documentos
- `RAG_NO_CONTEXT_UPLOAD_HINT` (`true` o `false`, default `true`) agrega/quita sugerencia de subir documentos al final de respuestas sin contexto
- `ANTHROPIC_API_KEY` (requerida para usar Claude en generacion)
- `ANTHROPIC_MODEL` (default: `claude-3-5-sonnet-latest`)
- `CHAT_CONFIDENCE_THRESHOLD` (default: `0.45`)
- `CHAT_RAG_INTENTS` (lista separada por comas)
- `CHAT_SESSION_BACKEND` (`memory` o `redis`, default `memory`)
- `CHAT_MAX_SESSION_TURNS` (default `12`)
- `REDIS_URL` (default `redis://localhost:6379/0`)
- `REDIS_KEY_PREFIX` (default `chat_session`)
- `REDIS_TTL_SECONDS` (default `86400`)
- `CHAT_AUTH_COMPAT_MODE` (`true` o `false`, default `true`) para migracion gradual de `/chat` a modo autenticado
- `AI_ENGINE_SHARED_SECRET` (opcional pero recomendado) firma HMAC para requests internas desde `platform-api` hacia `/internal/ai/*`
- `PUBLIC_WIDGET_SIGNING_SECRET` (recomendado) firma HMAC para exponer widgets publicos
- `PUBLIC_WIDGET_API_BASE_URL` (opcional, pero requerida en produccion) URL publica del AI Engine para generar el snippet embebible (`https://api.tudominio.com`). Sin ella, el widget cae en `http://localhost:8080` y el chat embebido en el sitio del integrador no funciona.
- `PUBLIC_WIDGET_ALLOW_ORIGINS` (default `*`) origins permitidos para `POST /public/widget/chat`
- `PUBLIC_WIDGET_RATE_LIMIT_WINDOW_SECONDS` (default `60`) ventana de rate limit del widget
- `PUBLIC_WIDGET_RATE_LIMIT_MAX_REQUESTS` (default `30`) maximo de requests por IP+widget en cada ventana
- `AGENT_CONVERSATION_POLICY_ENABLED` (default `true`) habilita politica de cierre/reintentos sin usar LLM
- `AGENT_CONVERSATION_STATE_BACKEND` (`memory` o `redis`, default `memory`)
- `AGENT_CONVERSATION_REDIS_URL` (opcional, fallback `REDIS_URL`)
- `AGENT_CONVERSATION_KEY_PREFIX` (default `agent_conv`)
- `AGENT_CONVERSATION_TTL_SECONDS` (default `86400`)
- `AGENT_REPEAT_GENERIC_THRESHOLD` (default `3`)
- `AGENT_REPEAT_CACHED_THRESHOLD` (default `4`)
- `CHAT_AUDIT_BACKEND` (`none`, `memory`, `postgres`, default `none`)
- `CHAT_AUDIT_POSTGRES_DSN` (obligatorio si `CHAT_AUDIT_BACKEND=postgres`)
- `CHAT_AUDIT_POSTGRES_SCHEMA` (default `public`)
- `RETRIEVAL_AUDIT_BACKEND` (`none` o `memory`, default `memory`) para metricas de retrieval por agente
- `RETRIEVAL_AUDIT_MAX_ROWS` (default `5000`) limite de eventos en memoria
- `AGENT_FEEDBACK_BACKEND` (`none` o `memory`, default `memory`) para feedback de calidad por agente
- `AGENT_FEEDBACK_MAX_ROWS` (default `5000`) limite de feedback en memoria
- `EVAL_LLM_JUDGE_ENABLED` (`true/false`, default `false`) activa scoring semantico opcional en evaluacion offline
- `EVAL_JUDGE_MODEL` (default `gpt-4o-mini`) modelo para judge semantico
- `EVAL_JUDGE_OPENAI_API_KEY` (opcional) key dedicada del judge; si no existe usa `OPENAI_API_KEY`
- `EVAL_STORAGE_BACKEND` (`file` o `postgres`, default `file`) persistencia de datasets/runs de evaluacion
- `EVAL_POSTGRES_DSN` (obligatorio si `EVAL_STORAGE_BACKEND=postgres`)
- `EVAL_POSTGRES_SCHEMA` (default `public`)
- `EVAL_JOB_STORAGE_BACKEND` (`auto`, `memory`, `sqlite`, `postgres`, default `auto`) persistencia de jobs async
- `EVAL_JOB_POSTGRES_DSN` (obligatorio si `EVAL_JOB_STORAGE_BACKEND=postgres`)
- `EVAL_JOB_POSTGRES_SCHEMA` (default `public`)
- `EVAL_JOB_QUEUE_BACKEND` (`auto`, `memory`, `redis`, default `auto`) cola de ejecucion de evaluaciones
- `EVAL_JOB_QUEUE_REDIS_URL` (opcional; si no se setea usa `REDIS_URL`)
- `EVAL_JOB_QUEUE_KEY` (default `eval_job_queue`)
- `EVAL_EMBEDDED_WORKER_ENABLED` (`true/false`, default `true`) ejecuta worker dentro del proceso API
- `CLUBHX_API_BASE_URL`, `CLUBHX_SERVICE_TOKEN` credenciales del backend de ClubHx (whsflow) para las tools de comercio
- La configuracion de ClubHx por agente vive en la BD: campos `clubhx_tenant_id` y `clubhx_shop_domain` del agente (`POST/PATCH /agents`, tambien via platform-api y el formulario de creacion de la consola). Es la fuente de verdad; las variables siguientes son solo fallback
- `CLUBHX_TENANT_MAP` JSON `{"<company_id>": {"tenant_id": "<uuid whsflow>", "shop_domain": "<dominio conectado>"}}`. ClubHx exige el UUID de su tenant y el header `X-Shop-Domain`; este mapa traduce la empresa de la plataforma a esos dos datos y permite varias tiendas por despliegue
- `CLUBHX_TENANT_ID`, `CLUBHX_SHOP_DOMAIN` fallback de una sola tienda cuando no hay mapa. Si el `company_id` ya es un UUID se usa tal cual
- Sin ClubHx configurado para la empresa, el chat del agente omite el flujo commerce y responde solo con RAG

### Auth + multi-tenant foundation (fase inicial)

Persistencia local:

- En `PERSISTENCE_BACKEND=sqlite`, la API crea automaticamente la base SQLite local en `SQLITE_DB_PATH` al iniciar.
- En `PERSISTENCE_BACKEND=postgres`, la API crea/actualiza schema base en `POSTGRES_DSN` o `DATABASE_URL` al iniciar.
- Si `PERSISTENCE_BACKEND` no esta definido pero existe `POSTGRES_DSN` o `DATABASE_URL`, la API usa Postgres automaticamente.
- Se persisten usuarios, refresh tokens, organizaciones, membresias, agentes, documentos de agente y settings LLM por tenant.

Importante:

- La persistencia real de agentes vive en este servicio AI engine. `platform-api` solo orquesta y proxyea; no almacena agentes por su cuenta.

Se agregaron endpoints base de identidad:

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`
- `POST /orgs` (crear organizacion + membresia owner)
- `GET /orgs` (listar organizaciones del usuario)

Endpoints de agentes (dashboard):

- `POST /agents` (crear agente en tenant activo)
- `GET /agents?company_id=...` (listar agentes por empresa)
- `POST /agents/{agent_id}/documents` (subir documento de conocimiento)
- `POST /agents/{agent_id}/tools/analyze-url` (traer y resumir una URL para acelerar el armado de conocimiento operativo)
- `POST /agents/{agent_id}/index/rebuild` (reconstruir indice RAG)
- `POST /agents/{agent_id}/chat` (consultar agente por RAG, con opcion OpenAI/Claude)
- `GET /agents/{agent_id}/widget-config` (obtener token + snippet HTML para webchat embebido)

Endpoint publico para webchat embebido:

- `POST /public/widget/chat` (consulta sin auth de usuario, valida `widget_token` + rate limit + origin)
- `GET /reports/chat/summary` (reporte agregado por tenant/agente para auditoria)
- `GET /reports/chat/cost-estimate` (estimacion de gasto/ahorro por uso de LLM vs respuestas cacheadas)
- `GET /reports/retrieval/summary` (calidad de retrieval: evidencia, fallback, score y latencia por agente)
- `GET /agents/{agent_id}/retrieval/compare` (compara backend actual vs baseline historico del agente)
- `POST /agents/{agent_id}/retrieval/decision` (guardar decision/recomendacion de backend)
- `GET /agents/{agent_id}/retrieval/decision-history` (historial de decisiones RAG del agente)
- `GET /agents/{agent_id}/evaluation/dataset` (dataset offline de evaluacion)
- `POST /agents/{agent_id}/evaluation/dataset` (guardar dataset offline)
- `POST /agents/{agent_id}/evaluation/run` (ejecutar corrida de evaluacion reproducible)
- `POST /agents/{agent_id}/evaluation/run-async` (encolar corrida asincrona y devolver `job_id`)
- `GET /agents/{agent_id}/evaluation/jobs/{job_id}` (estado del job: queued/running/succeeded/failed)
- `GET /agents/{agent_id}/evaluation/runs` (historial de corridas)
- `GET /agents/{agent_id}/evaluation/runs.csv` (exportar corridas en CSV)
- `GET /agents/{agent_id}/evaluation/compare-latest` (comparar ultima corrida vs baseline)
- `POST /agents/{agent_id}/feedback` (guardar feedback up/down de una respuesta)
- `GET /agents/{agent_id}/feedback/summary` (resumen de feedback por agente)

Campos opcionales recomendados para trazabilidad en web 3ra:

- `visitor_id`: id anonimo persistido en localStorage del widget
- `external_user_id`: id de usuario del sistema externo (si existe login)

Endpoint de configuracion LLM por tenant:

- `GET /settings/llm?company_id=...` (leer provider/modelos/estado de keys por empresa)
- `PUT /settings/llm` (guardar provider/modelos y API keys por empresa)

Notas de comportamiento en `POST /agents/{agent_id}/chat`:

- El agente aplica primero un orquestador de intenciones (company-specific vs conocimiento general) para decidir la ruta.
- Si no existe indice todavia, el agente responde igual en modo "conocimiento en vivo" leyendo documentos cargados.
- Los archivos subidos quedan versionados por metadata en BD y el contenido se lee desde el backend configurado (`local` o `s3`).
- Si todavia no hay documentos validos y hay LLM activo, responde de forma natural con conocimiento general (aclarando que es orientativo).
- Si todavia no hay documentos validos y no hay LLM activo, responde que no sabe sobre ese tema y sugiere cargar documentos.
- Si falla OpenAI o Claude/Anthropic durante la generacion, el agente hace fallback a respuesta extractiva con evidencia en lugar de devolver 500.
- Se puede forzar `generation_provider` y `generation_model` por request en `POST /agents/{agent_id}/chat`.
- En frontend (wizard/playground/settings), los providers y modelos se habilitan automaticamente segun si existen API keys de OpenAI/Anthropic para ese tenant.
- La politica conversacional corta gasto de tokens: en repeticion consecutiva #3 responde en modo generico sin LLM, y en #4+ reutiliza la ultima respuesta cacheada.

Notas de comportamiento en `POST /agents/{agent_id}/index/rebuild`:

- Si `rag_backend=auto` y falla Dense OpenAI (por ejemplo cuota/rate limit), se hace fallback automatico a `tfidf` para evitar error 500.

Migracion de documentos locales a object storage:

```bash
python -m clasificacion_langchain.cli.migrate_agent_documents --backend s3 --db-path data/local_api.db
```

Modo simulacion sin cambios:

```bash
python -m clasificacion_langchain.cli.migrate_agent_documents --backend s3 --db-path data/local_api.db --dry-run
```

Variables de entorno para auth:

- `AUTH_SECRET_KEY` (requerida)
- `AUTH_TOKEN_ALGORITHM` (default `HS256`)
- `AUTH_ACCESS_TTL_MINUTES` (default `15`)
- `AUTH_REFRESH_TTL_DAYS` (default `7`)

#### Modo de migracion de `/chat`

- Si `CHAT_AUTH_COMPAT_MODE=true` (default):
  - Se permite flujo legacy sin token (requiere `company_id` y `session_id` en payload).
  - Si viene bearer token, se valida tenant contra membresias del usuario.
- Si `CHAT_AUTH_COMPAT_MODE=false`:
  - `/chat` exige bearer token.
  - `company_id` se resuelve desde contexto autenticado (o valida mismatch si se envia).

### Request de ejemplo

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "empresa_a",
    "session_id": "sesion-001",
    "message": "Cual es el horario de soporte?",
    "top_k": 4
  }'
```

### Respuesta (campos clave)

- `trace_id`: identificador para trazabilidad.
- `route`: `rag` o `fallback`.
- `route_reason`: motivo del enrutamiento (`intent_confident`, `low_intent_confidence`, `empty_retrieval_context`, `no_intent_router`).
- `escalation_required`: `true` cuando conviene derivar a humano.
- `sources`: documentos usados para responder.

## WhatsApp Channel Boundary

El AI Engine ya no expone ni opera el webhook de WhatsApp. Esa responsabilidad vive en un Channel Gateway externo.

Este servicio conserva solo capacidades de IA reutilizables para ese gateway:

- `POST /internal/ai/media/transcriptions`: transcripcion de audio.
- `POST /internal/ai/agents/{agent_id}/chat`: resolucion conversacional del agente.

La configuracion y validacion de WhatsApp en esta API queda como metadata opcional del agente. No participa del runtime de IA ni requiere variables de entorno del canal.
