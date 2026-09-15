# Backend — AI Engine

FastAPI + LangChain/LangGraph + scikit-learn + RAG.
Lee también `../AGENTS.md` (arquitectura Option A, convenciones globales).

---

## Stack

| Componente | Tecnología |
|---|---|
| Framework API | FastAPI (entrypoint único: `chat_api.py`) |
| Orquestación AI | LangGraph (2 grafos: hybrid agent, commerce checkout) |
| ML clásico | scikit-learn: TF-IDF vectorizer, LinearSVC, LabelEncoder |
| Normalización texto | NLTK: SnowballStemmer("spanish"), stopwords español |
| RAG retrieval | TF-IDF vectorial / Dense OpenAI / Hybrid (RRF) |
| Generación LLM | OpenAI GPT / Anthropic Claude (vía urllib directo, SIN SDK) |
| Persistencia | SQLite (default) / PostgreSQL |
| Chat sessions | In-memory (default) / Redis con TTL |
| Document storage | Local filesystem / S3 / RustFS |
| Evaluación offline | Datasets por agente, scoring por términos, LLM judge opcional |
| Auth | JWT (access 15min + refresh 7d), HMAC para internal API |
| E-commerce tools | ClubHx API externa (productos, carrito, órdenes, OTP) |

---

## Flujo de una request de chat

```
POST /agents/{id}/chat  (o /chat legacy)
  → AgentIntentOrchestrator.decide()
     → opcional: LLM clasifica intent (smalltalk_greeting/company_specific/general_knowledge/unknown)
     → decide ruta: greeting | rag_live_docs | rag_index | no_knowledge | general_llm
  → si tiene ConversationPolicyEngine → evalúa repeticiones (fingerprint SHA1)
  → carga agent knowledge docs + shared role knowledge
  → construye RoleContext (system_rules según canal: whatsapp_seller | web_support_seller)
  → RAGPipeline.answer() → search() + generate()
     → si falla LLM remoto → fallback a ExtractiveAnswerGenerator
  → enforce_channel_response_contract() (acorta según canal: 420 chars WhatsApp)
  → log + audit trail
  → post-procesamiento commerce: si hay workflow activo, evalúa timeout/resume
```

---

## Estructura del proyecto

### Entry points (scripts CLI)

| Script | Función |
|---|---|
| `chat_api.py` | Entry point HTTP mínimo. Importa la app oficial modular de `src/clasificacion_langchain/api/app.py`. |
| `python -m clasificacion_langchain.cli.train_model` | Entrena clasificador (`--task sentiment`) o intent router (`--task intent`) desde CSV o MySQL |
| `python -m clasificacion_langchain.cli.build_rag_index` | Construye índice RAG desde `knowledge_base/<company_id>/` |
| `python -m clasificacion_langchain.cli.ask_hybrid_agent` | Consulta local al agente híbrido por CLI |
| `python -m clasificacion_langchain.cli.evaluation_worker` | Worker async dedicado para evaluación |
| `streamlit run src/clasificacion_langchain/cli/streamlit_demo.py` | Streamlit demo legacy de clasificación de tweets |
| `python -m clasificacion_langchain.cli.migrate_agent_documents` | Migra documentos locales a S3/RustFS (soporta `--dry-run`) |

### `src/clasificacion_langchain/` — Core modules

#### ML Pipeline (legacy clasificación)

- **`text_cleaning.py`**: `normalize_text()` → URLs out, NFKD ascii, lowercase, punctuation out, tokenize, stopwords out (ES), Snowball stem. Cachea stopwords y stemmer con `@lru_cache`.
- **`data_sources.py`**: `load_csv_dataset()` valida columnas `text`/`label`. `load_mysql_dataset()` conecta MySQL vía `mysql.connector`. `MySQLConfig` dataclass desde env.
- **`training.py`**: `train_classifier()` → train_test_split estratificado, TF-IDF uni+bigramas (max_features=5000), LinearSVC(C=1.0), LabelEncoder. Guarda artifact joblib con pipeline + encoder + metrics.
- **`ml_utils.py`**: `softmax()` numpy, `build_scores_from_decision()` → convierte decision_function de SVM a probabilidades vía softmax. Maneja caso binario (1 valor → 2 clases).
- **`inference_graph.py`**: LangGraph con 3 nodos: normalize → classify → explain. Usa `RunnableLambda`. State: `InferenceState` TypedDict.

#### Hybrid Agent (intent router + RAG)

- **`intent_router.py`**: `IntentRouter` class. Carga artifact joblib, expone `predict(text)` → `IntentPrediction(label, confidence, scores)`. Usa `decision_function()` o `predict_proba()` según el modelo.
- **`hybrid_agent_graph.py`**: LangGraph con 4 nodos: normalize → route → (rag | fallback). State: `HybridAgentState` TypedDict. `route_selector()` decide según threshold de confianza (default 0.45). Soporta `rag_intents` set para filtrar qué intents van a RAG.
- **`agent_tools.py`**: `AgentToolset` dataclass. `classify_intent()`, `answer_company_question()` (delega a RAGPipeline), `analyze_web_url()` (fetch + extract title/content/keypoints vía urllib directo).

#### RAG Pipeline (`rag/`)

- **`schemas.py`**: `KnowledgeDocument(company_id, source, text, metadata)`, `ChunkedDocument`, `RetrievedChunk(score)`, `RAGAnswer(answer, sources, retrieved_chunks, ...)`.
- **`loaders.py`**: `load_company_documents()` recorre `knowledge_base/<company_id>/*`. Soporta `.txt`, `.md`, `.csv`, `.json` (pypdf), `.pdf` (pypdf), `.docx` (python-docx). `load_text_content()` según extensión.
- **`chunking.py`**: `chunk_documents()` → para markdown usa `_chunk_markdown_semantic()` (divide por secciones `#`, luego agrupa párrafos hasta chunk_size). Para otros formatos usa `_chunk_text()` sliding window. Min length 50 chars. Genera chunk_id con SHA1.
- **`vector_index.py`**: `TfidfVectorIndex`. Build: TF-IDF vectorizer (max_features, ngram_range). Search: filtra por company_id, cosine_similarity, top_k por score. Save/load con joblib.
- **`dense_index.py`**: `DenseVectorIndex`. Build: OpenAIEmbeddingClient en batches. Search: normalize L2, producto punto. Save/load con joblib.
- **`hybrid_index.py`**: `HybridVectorIndex` = tfidf + dense + RRF (Reciprocal Rank Fusion, k=60). Search: consulta ambos indexes, fusiona scores con RRF, top_k final.
- **`embeddings.py`**: `OpenAIEmbeddingClient`. Llama a `api.openai.com/v1/embeddings` con urllib directo (sin pip install openai). Timeout configurable.
- **`generation.py`**: Tres generadores que implementan `AnswerGenerator` protocol:
  - `ExtractiveAnswerGenerator`: sin LLM, ranked chunks, summary extractivo.
  - `OpenAIAnswerGenerator`: prompt LangChain + `_openai_completion()` vía urllib directo.
  - `AnthropicAnswerGenerator`: similar con API Anthropic.
  - `build_remote_generator()`: elige proveedor según env. `tune_answer_style()`: limpia numeración, secciones, factoid queries. `enforce_channel_response_contract()`: trunca por canal (420 chars WhatsApp, 560 web). `_no_context_mode()`: strict/balanced/open según `RAG_NO_CONTEXT_MODE`.
- **`pipeline.py`**: `RAGPipeline` orquesta `index.search()` + `generator.generate()`. `from_artifact()` construye desde artifact. `answer()` soporta override de provider/model por request. Si falla LLM remoto → fallback extractivo con notice. `build_and_save_index()`: elige backend según `--backend` (auto → dense si hay key, sino tfidf). Fallback automático si falla dense/hybrid en modo auto.
- **`index_loader.py`**: `load_index()` detecta `index_type` del artifact y devuelve el tipo correcto.

#### Chat Service (`chat/`)

- **`schemas.py`**: `ChatRequest(company_id, session_id, message, top_k, ...)`, `ChatResponse(trace_id, route, route_reason, intent_label, sources, escalation_required)`.
- **`config.py`**: `ChatServiceConfig` dataclass con defaults desde env.
- **`session_store.py`**: `SessionStore` protocol. `SessionTurn(role, text)`. `SessionSummary` con **38 campos** (estado de checkout, preferencias, autenticación, etc.). `StoredSessionSummary(company_id, session_id, summary)`.
- **`memory_store.py`**: `InMemorySessionStore`. Cola por (company_id, session_id) con max_turns. Implementa `SessionStore` protocol.
- **`redis_store.py`**: `RedisSessionStore`. Keys con prefijo + company + session. TTL configurable.
- **`service.py`**: `ChatService`. Construye `RAGPipeline` + `IntentRouter` + `AgentToolset` + `hybrid_agent_graph`. `chat(request)` → formatea historial, invoca graph, trackea trace_id, guarda en memoria. Escala a `escalation_required` si route=fallback o rag sin sources.

#### Agent Service (`agents/`)

- **`repository.py`**: `AgentRecord(agent_id, org_id, company_id, name, objective, tone, rag_backend, ...)`. `AgentDocumentRecord`. `AgentRepository` protocol. `InMemoryAgentRepository` implementación in-memory.
- **`sqlite_repository.py`**: `SQLiteAgentRepository`. Tablas: `agents`, `agent_documents`, `agent_document_metadata`. CRUD completo. Marca documentos como indexed/failed.
- **`postgres_repository.py`**: `PostgresAgentRepository`. Similar a SQLite pero con Postgres + schema configurable.
- **`service.py`**: **`AgentService` (~1300 líneas)** — el módulo más grande. Responsabilidades:
  - CRUD agentes con validaciones (nombre ≥2 chars, objective ≥8, rag_backend válido, etc.)
  - Subida de documentos: validación extensión, checksum SHA256, dedup por filename/canonical name/checksum, storage en local/S3 vía `DocumentStorage`
  - Reconstrucción de índice RAG: carga knowledge docs + shared knowledge, chunking, build index según `agent.rag_backend` con fallback tfidf
  - Chat por agente: orquesta `AgentIntentOrchestrator` → `ConversationPolicyEngine` → `RoleContext` → RAGPipeline. Soporta sobreescribir provider/model por request
  - Evaluación offline: datasets (JSON file o Postgres), runs con scoring por términos + LLM judge opcional (gpt-4o-mini en JSON mode), historial de runs, comparativa contra baseline
  - Feedback: thumbs up/down con comentario opcional
  - Widget config: genera token + snippet HTML + rate limiting
  - WhatsApp channel config: phone_number_id, verify_token
  - Session summaries con estado de checkout completo (38 fields)
  - Retrieval audit + decision history
- **`orchestrator.py`**: `AgentIntentOrchestrator`. `decide()` → usa LLM (OpenAI/Anthropic vía urllib) para clasificar intent en: `smalltalk_greeting`, `company_specific`, `general_knowledge`, `unknown`. Si no hay LLM, retorna `unknown`. Según intent + documentos + índice + LLM disponible, decide ruta: greeting / rag_live_docs / rag_index / general_llm / no_knowledge.
- **`conversation_policy.py`**: `ConversationPolicyEngine`. Detecta mensajes repetidos por **fingerprint SHA1** del texto normalizado. Incrementa `repeat_count`. Dos stores: `InMemoryConversationStateStore` o `RedisConversationStateStore`. Thresholds: `AGENT_REPEAT_GENERIC_THRESHOLD` (default 3) y `AGENT_REPEAT_CACHED_THRESHOLD` (default 4). `build_conversation_policy_from_env()`.
- **`document_storage.py`**: `DocumentStorage` protocol. `LocalDocumentStorage` (guarda en `knowledge_dir/company_id/timestamp-uuid-filename`). `S3DocumentStorage` (boto3, soporta RustFS via env aliases). `RoutedDocumentStorage` (enruta lectura según `storage_provider` del documento). `build_document_storage_from_env()`.
- **`role_knowledge.py`**: `RoleContext(role_key, channel, objective, tone, system_rules, runtime_context)`. Dos roles: `whatsapp_seller`, `web_support_seller`. `build_role_context()` mergea role objective + agent objective. `sync_shared_knowledge()` copia archivos desde `knowledge/shared/` a cada agente. `load_local_knowledge_documents()` carga docs `_shared/` como KnowledgeDocuments.
- **`commerce_workflow.py`**: `CommerceWorkflowState` dataclass. `WORKFLOW_STAGES`: browsing, product_lookup, cart_building, shipping_selection, payment_selection, checkout_ready, post_sale_support, human_handoff. `resolve_transition()` valida si un paso es válido según estado actual. `normalize_stage()` mapea legacy stages a canónicos.

#### Commerce Checkout (`agents/commerce/`)

Checkout conversacional en WhatsApp con LangGraph. State = `WhatsAppCheckoutState` (23 campos).

- **`state.py`**: `WhatsAppCheckoutState` dataclass. `coerce_workflow_state()` construye desde dict legacy. `apply_payload_state()` mergea payload en state. `normalize_stage()` con aliases. `normalize_awaiting_slot()` similar.
- **`types.py`**: `CheckoutStage` y `AwaitingSlot` type aliases.
- **`graph.py`**: LangGraph con 4 nodos: plan → guard → execute_or_block → map. Usa `planner` (CommerceWorkflowRouter) + `resolver` (CheckoutWorkflowResolver). Guard condition evaluate_tool_guard. Map node aplica response_mapper.
- **`commands.py`**: `CheckoutCommand(requested_tool, slot_updates, ...)`. `parse_checkout_command()` desde LLM JSON output.
- **`slots.py`**: `align_command_to_stage()` asegura que el comando sea válido para la etapa. `merge_command_into_state()` aplica slot_updates al state.
- **`router.py`**: `CommerceWorkflowRouter`. `plan()` según intent del mensaje + workflow state actual.
- **`guards.py`**: `evaluate_tool_guard()` valida que la tool sea válida según etapa. Implementa `ToolGuardDecision`.
- **`resolver.py`**: `CheckoutWorkflowResolver`. `resolve()` ejecuta la lógica: lookup productos, cart management, shipping, payment, OTP auth, invoice, etc.
- **`tool_executor.py`**: `CanonicalCommerceToolExecutor`. Ejecuta tools contra ClubHx: get_product_availability, get_order_status, get_shipping_options, get_payment_options, create_payment_link, create_order_draft, get_addresses, send_verification_code, etc.
- **`tool_ports.py`**: interfaces de tools (abstracción).
- **`prompting.py`**: `build_commerce_intent_messages()`, `build_invoice_extraction_messages()`, `build_recipe_plan_messages()`. Prompts para LLM commerce.
- **`llm_json.py`**: `call_openai_json()` para responses estructuradas en JSON mode.
- **`lookup_cart.py`**: `LookupCartResolver`.
- **`persistence.py`**: `CheckoutSessionSummaryAdapter`. `from_summary()` → `WhatsAppCheckoutState`. `to_workflow_state_dict()` → dict legacy.
- **`cart_snapshot.py`**: snapshot del carrito como JSON.
- **`response_mapper.py`**: `map_checkout_response_payload()` post-procesa payloads.
- **`resume_timeout.py`**: lógica de timeout (5 min inactividad) y reanudación: describe_current_workflow, resolve_greeting_workflow_followup, resolve_legacy_preflight, resolve_workflow_resume_followup, timeout_message, workflow_state_has_active_checkout.
- **`recent_products.py`**: `serialize_recent_products_for_llm()`.

#### Auth (`auth/`)

- **`service.py`**: `AuthService`: register (valida email único), login (verify password + issue tokens), refresh (revoke old + issue new), logout (revoke), me.
- **`token_service.py`**: `TokenService`: create_access_token (15min), create_refresh_token (7d), validate. HMAC con `AUTH_SECRET_KEY`. Payload: user_id, org_id, roles, token_id, exp.
- **`schemas.py`**: `RegisterInput`, `LoginInput`, `TokenPair`, `AuthUserView`, `AuthPrincipal`.
- **`passwords.py`**: `hash_password()` / `verify_password()` con bcrypt.
- **`repository.py`**: `UserRepository` y `RefreshTokenRepository` protocols.

#### Tenancy (`tenancy/`)

- **`service.py`**: `TenancyService.onboard_organization()`: slug del company_id desde nombre. `resolve_company_id()`: 4 estrategias según requested_company_id, principal.active_org_id, única membership, o error.
- **`repository.py`**: `OrganizationRecord`, `MembershipRecord`. `OrganizationRepository`, `MembershipRepository` protocols.

#### Settings (`settings/`)

- **`service.py`**: `TenantLlmSettingsService`: get/set API keys de OpenAI/Anthropic, modelos, provider. Ofusca keys en responses (masked). Detecta source: tenant | env | none.
- **`sqlite_store.py`** / **`postgres_store.py`**: stores de settings.

#### Persistence (`persistence/`)

3 stores que implementan interfaces de auth + tenancy:
- `SQLiteIdentityStore`: tablas users, refresh_tokens, organizations, memberships
- `PostgresIdentityStore`: similar con schema configurable
- `InMemoryIdentityStore`: dicts en memoria

#### Analytics (`analytics/`)

- **`chat_audit.py`**: `ChatAuditRecord`, `ChatAuditCostRow`, `ChatAuditSummaryRow`. Stores: `InMemoryChatAuditStore` y `PostgresChatAuditStore`. Registra cada interacción de chat por tenant/agente.
- **`retrieval_audit.py`**: `RetrievalBackendMetrics`, `RetrievalComparisonRow`. Métricas de calidad de retrieval: score promedio, grounded rate, fallback rate, latencia.
- **`feedback_audit.py`**: `AgentFeedbackRecord`, `AgentFeedbackSummary`. Thumbs up/down, comentarios, expected_answer opcional.

#### Channels (`channels/`)

- **`whatsapp.py`**: parseo de mensajes entrantes WhatsApp (text, interactive buttons, etc.)
- **`meta_whatsapp_api.py`**: cliente para API Meta (send message, media upload, etc.)
- **`idempotency.py`**: `InMemoryIdempotencyStore` para dedup de webhooks por message_id.

#### Otros

- **`clubhx_tools_client.py`**: `ClubHxToolsClient`. POST a API externa con `X-Club-Service-Token`. Tools: get_product_availability, get_order_status, get_shipping_options, get_payment_options, create_payment_link, create_order_draft, get_addresses, create_address, send_verification_code.

### `tests/`

- `test_agent_service_upsert.py` — upsert de documentos
- `test_rag_knowledge_index_contract.py` — contrato del índice RAG
- `test_rag_response_tuning.py` — tune_answer_style
- `test_saas_auth_multitenant.py` — auth + tenancy
- `test_whatsapp_checkout_graph.py` — grafo LangGraph checkout
- `test_whatsapp_checkout_persistence.py` — persistencia checkout
- `test_whatsapp_checkout_resolver.py` — resolver
- `test_whatsapp_checkout_slots.py` — slots
- `test_whatsapp_checkout_tool_guards.py` — tool guards

---

## Entry points

### API (chat_api.py)
```bash
uvicorn backend.chat_api:app --host 0.0.0.0 --port 8080
```

Endpoints:
| Grupo | Endpoints |
|---|---|
| Auth | `POST /auth/register\|login\|refresh\|logout`, `GET /me` |
| Tenancy | `POST /orgs`, `GET /orgs` |
| Agentes | `POST /agents`, `GET /agents`, `DELETE /agents/{id}`, `PATCH /agents/{id}` |
| Agentes docs | `GET\|POST\|DELETE /agents/{id}/documents` |
| Agentes chat | `POST /agents/{id}/chat` |
| Agentes RAG | `POST /agents/{id}/index/rebuild`, `GET /agents/{id}/index/status` |
| Agentes setup | `GET /agents/{id}/setup-status` |
| Agentes WhatsApp | `GET\|PUT /agents/{id}/channels/whatsapp/config`, `POST .../validate` |
| Agentes widget | `GET /agents/{id}/widget-config` |
| Agentes feedback | `POST /agents/{id}/feedback`, `GET .../feedback/summary` |
| Agentes eval | `GET\|POST /agents/{id}/evaluation/dataset`, `POST .../run\|run-async`, `GET .../jobs/{id}`, `GET .../runs\|runs.csv`, `GET .../compare-latest` |
| Agentes retrieval | `GET /agents/{id}/retrieval/compare`, `POST .../decision`, `GET .../decision-history` |
| Agentes tools | `POST /agents/{id}/tools/analyze-url` |
| Chat legacy | `POST /chat` (compat mode) |
| Widget público | `POST /public/widget/chat` |
| Internal AI | `POST /internal/ai/media/transcriptions`, `POST /internal/ai/agents/{id}/chat` |
| Settings LLM | `GET\|PUT /settings/llm` (por tenant) |
| Reportes | `GET /reports/chat/summary\|cost-estimate`, `GET /reports/retrieval/summary` |

### CLIs

```bash
# Entrenar clasificador
python -m clasificacion_langchain.cli.train_model --source csv --csv-path backend/data/sample_tweets.csv

# Entrenar intent router
python -m clasificacion_langchain.cli.train_model --task intent --source csv --csv-path backend/data/intent_router_dataset_template.csv --model-path backend/models/intent_router.joblib

# Construir índice RAG
python -m clasificacion_langchain.cli.build_rag_index --knowledge-dir backend/knowledge_base --backend auto --index-path backend/models/rag_index.joblib

# Consultar agente híbrido
python -m clasificacion_langchain.cli.ask_hybrid_agent --question "consulta" --company-id empresa_a --index-path backend/models/rag_index.joblib

# Streamlit legacy
streamlit run backend/src/clasificacion_langchain/cli/streamlit_demo.py

# Migrar docs a S3
python -m clasificacion_langchain.cli.migrate_agent_documents --backend s3 --db-path data/local_api.db [--dry-run]
```

---

## Patrones de código

### `sys.path.insert(0, str(SRC))`
Todos los entrypoints insertan `backend/src/` en sys.path para importar `clasificacion_langchain.*`.

### `from __future__ import annotations`
En todos los módulos (evaluación diferida de type hints).

### Protocol classes para repositorios
Ej: `AgentRepository`, `SessionStore`, `DocumentStorage`, `UserRepository`. Implementaciones concretas: InMemory, SQLite, Postgres, Redis, Local, S3.

### LangGraph con TypedDict
Estados tipados con TypedDict (total=False). Nodos como `RunnableLambda`. Condicional edges para ruteo.

### urllib directo (sin SDK)
OpenAI y Anthropic se llaman con `urllib.request` directamente. No hay dependencias `openai` ni `anthropic` en requirements.txt.

### Logging estructurado
```python
logger.info("event_name key1=value1 key2=value2")
```
Patrón `_trace_route()` para trazabilidad de decisiones de ruteo commerce.

### Env vars con defaults tipados
`os.getenv("VAR", "default")` + parseo explícito de booleanos con `_env_bool()`.

### Estrategia de fallback en RAG
- `auto` → dense si hay key, tfidf si no
- Si falla dense/hybrid en modo auto → fallback a tfidf
- Si falla LLM remoto → fallback a extractivo con notice

---

## Variables de entorno clave

| Variable | Default | Descripción |
|---|---|---|
| `AUTH_SECRET_KEY` | — | **Requerida**. HMAC para JWT |
| `OPENAI_API_KEY` | — | Embeddings dense + generación OpenAI |
| `ANTHROPIC_API_KEY` | — | Generación Claude |
| `CHAT_USE_OPENAI` | `false` | Habilita generación LLM en chat |
| `PERSISTENCE_BACKEND` | `sqlite` | `sqlite` / `postgres` / `memory` |
| `CHAT_SESSION_BACKEND` | `memory` | `memory` / `redis` |
| `DOC_STORAGE_BACKEND` | `local` | `local` / `s3` |
| `AI_ENGINE_SHARED_SECRET` | — | HMAC para internal API |
| `CHAT_AUTH_COMPAT_MODE` | `true` | `/chat` legacy sin token |
| `AGENT_CONVERSATION_POLICY_ENABLED` | `true` | Política de repetición |
| `RAG_NO_CONTEXT_MODE` | `strict` | `strict` / `balanced` / `open` |
| `EVAL_LLM_JUDGE_ENABLED` | `false` | LLM judge en evaluación |
| `WHATSAPP_CHECKOUT_LANGGRAPH_ENABLED` | `true` | Grafo LangGraph checkout |

Lista completa (~280 vars) en `backend/README.md`.

---

## Testing

```bash
python -m pytest backend/tests -v
python -m pytest backend/tests/test_whatsapp_checkout_graph.py -v
python -m pytest backend/tests/test_saas_auth_multitenant.py -v
```

---

## Convenciones

- PEP 8 (4 spaces, UTF-8)
- Imports: stdlib → third-party → local (blank line entre grupos)
- `snake_case` funciones/vars, `PascalCase` clases, `UPPER_CASE` constantes
- Type hints en APIs públicas
- `random_state` explícito para ML determinista
- Fit transforms solo en train split (no leakage)
- CLI output conciso, Streamlit en español
- Sin debug prints en producción (usar logger)

---

## Links útiles

- `../AGENTS.md` — Option A, convenciones globales
- `backend/SAAS_PLAN.md` — plan de evolución a SaaS
- `backend/RAG_KNOWLEDGE_INDEX_PLAYBOOK.md` — playbook operativo RAG
- `backend/RAG_OPERATING_GUIDE.md` — operating guide RAG multi-tenant
- `backend/README.md` — docs detalladas (todos los endpoints + env vars)
- `docs/whatsapp-checkout-workflow.md` — workflow de checkout WhatsApp
- `knowledge/` — conocimiento compartido por rol (system_rules)
- `knowledge_templates/` — templates de conocimiento operativo
