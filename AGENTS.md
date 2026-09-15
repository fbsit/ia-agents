# AGENTS.md

Operational guide for coding agents in this repository.

## 1) Scope and priorities
- Project direction: evolve from ML demo into a SaaS-ready multi-tenant conversational agent platform.
- Core value: companies upload docs, system builds RAG context, and agents can be deployed to WhatsApp/chat quickly.
- Technical baseline: hybrid stack (ML intent routing + RAG retrieval + optional OpenAI generation).
- Priorities: correctness, tenant isolation (`company_id`), reproducibility, and operational reliability.
- Prefer minimal, targeted edits over broad refactors.
- Do not add tooling/framework complexity unless requested.

## 2) Repository map
- `backend/chat_api.py`: FastAPI service entrypoint. Imports the official modular app from `backend/src/clasificacion_langchain/api/app.py`.
- `backend/src/clasificacion_langchain/cli/train_model.py`: CLI training entrypoint.
- `backend/src/clasificacion_langchain/cli/build_rag_index.py`: CLI for building RAG index artifacts.
- `backend/src/clasificacion_langchain/cli/ask_hybrid_agent.py`: CLI for local hybrid-agent queries.
- `backend/src/clasificacion_langchain/cli/migrate_agent_documents.py`: CLI for storage migration of agent documents.
- `backend/src/clasificacion_langchain/cli/evaluation_worker.py`: Dedicated evaluation worker CLI.
- `backend/src/clasificacion_langchain/cli/streamlit_demo.py`: Legacy Streamlit demo module.
- `frontend/`: Next.js frontend project.
- `platform-api/`: Spring Boot API Gateway/BFF (Option A).
- `backend/src/clasificacion_langchain/text_cleaning.py`: normalization + NLTK resources.
- `backend/src/clasificacion_langchain/data_sources.py`: CSV/MySQL ingestion + env config.
- `backend/src/clasificacion_langchain/training.py`: split/train/evaluate/save model pipeline.
- `backend/src/clasificacion_langchain/inference_graph.py`: LangGraph inference flow.
- `backend/src/clasificacion_langchain/intent_router.py`: ML intent router for hybrid routing.
- `backend/src/clasificacion_langchain/hybrid_agent_graph.py`: graph that routes between RAG and fallback.
- `backend/src/clasificacion_langchain/chat/`: chat service, session stores (memory/redis), request/response schemas.
- `backend/src/clasificacion_langchain/channels/`: WhatsApp parsing, Meta API client, idempotency stores.
- `backend/src/clasificacion_langchain/agents/`: agent registry, knowledge docs, and per-agent RAG orchestration.
- `backend/src/clasificacion_langchain/rag/`: loaders, chunking, tfidf/dense indexes, retrieval pipeline.
- `backend/data/sample_tweets.csv`: sample dataset.
- `backend/data/intent_router_dataset_template.csv`: starter dataset template for intent routing.
- `backend/requirements.txt`: pinned dependencies.

## 3) Cursor/Copilot rule files
No additional IDE-agent rule files were found during analysis:
- `.cursor/rules/` not present.
- `.cursorrules` not present.
- `.github/copilot-instructions.md` not present.
If any appear later, treat them as extra constraints and update this file.

## 4) Environment setup
- Use Python 3.x (repo contains `cpython-313` cache artifacts).
- Create virtualenv and install dependencies (from `backend/`):
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
- For MySQL flow, copy `.env.example` to `.env` and fill DB values.
- Never commit `.env`, `models/`, secrets, or generated caches.

## 5) Build, lint, and test commands
This repo has no formal build script, no linter config, and no tests committed yet.
Use these commands as the default execution contract for agents.

### 5.1 Build/run commands
- Train from sample CSV (fast local path):
```bash
python -m clasificacion_langchain.cli.train_model --source csv --csv-path backend/data/sample_tweets.csv
```
- Train intent router from template dataset:
```bash
python -m clasificacion_langchain.cli.train_model --task intent --source csv --csv-path backend/data/intent_router_dataset_template.csv --model-path backend/models/intent_router.joblib
```
- Build RAG index (auto backend selection):
```bash
python -m clasificacion_langchain.cli.build_rag_index --knowledge-dir backend/knowledge_base --backend auto --index-path backend/models/rag_index.joblib
```
- Run FastAPI backend:
```bash
uvicorn backend.chat_api:app --host 0.0.0.0 --port 8000
```
- Run Next.js frontend (from `frontend`):
```bash
npm run dev
```
- Run Spring Boot API Gateway (from `platform-api`):
```bash
.\mvnw.cmd spring-boot:run
```
- Train from MySQL (`.env` required):
```bash
python -m clasificacion_langchain.cli.train_model --source mysql
```
- Run Streamlit demo:
```bash
streamlit run backend/src/clasificacion_langchain/cli/streamlit_demo.py
```

### 5.2 Lint/static checks
- Syntax check all project Python files:
```bash
python -m compileall backend/chat_api.py backend/src
```
- If available in your environment, run Ruff:
```bash
ruff check .
```
- Frontend lint (from `frontend`):
```bash
npm run lint
```

### 5.3 Test commands (pytest convention)
- Run entire test suite:
```bash
python -m pytest backend/tests
```
- Run one test file:
```bash
python -m pytest backend/tests/test_text_cleaning.py
```
- Run ONE test function (single-test command):
```bash
python -m pytest backend/tests/test_text_cleaning.py::test_normalize_text
```
- Run tests by keyword:
```bash
python -m pytest -k normalize
```
- If `pytest` is missing, install it in the active virtualenv.
- Keep tests under `backend/tests/` and use file pattern `test_*.py`.
- Frontend tests (from `frontend`):
```bash
npm run test
```

## 6) Code style and conventions

### 6.1 Imports
- Order imports as: standard library -> third-party -> local package.
- Use one blank line between import groups.
- Prefer explicit imports; avoid wildcard imports.
- Keep top-level side effects minimal.
- Existing entry scripts use `sys.path` insertion for `src/`; follow current pattern unless project packaging changes.

### 6.2 Formatting
- Follow PEP 8 defaults (4 spaces, clear spacing, readable line lengths).
- Prefer readable multiline expressions over dense one-liners.
- Keep functions focused and composable.
- Add comments only for non-obvious intent, not obvious mechanics.

### 6.3 Types
- Add type annotations for public functions, parameters, and returns.
- Prefer `from __future__ import annotations` in new modules.
- Use `TypedDict` for graph state payloads.
- Use `dataclass` for structured config/result objects.
- Avoid `Any` unless third-party APIs force it.

### 6.4 Naming
- Functions/variables/modules: `snake_case`.
- Classes/dataclasses: `PascalCase`.
- Constants: `UPPER_CASE`.
- Favor descriptive domain names (`normalize_text`, `train_classifier`, `load_csv_dataset`).
- Accept common ML abbreviations only when clear (`df`, `x_train`, `y_test`).

### 6.5 Error handling and validation
- Validate external inputs early (CSV columns, DB query output, empty text).
- Raise specific exceptions with actionable messages.
- Wrap optional imports and explain dependency installation in errors.
- Ensure cleanup for external resources (DB connection close in `finally`).
- Fail fast on missing model artifact in app startup.

### 6.6 Data and ML behavior
- Preserve no-leakage workflow: fit transforms only on train split.
- Keep deterministic settings explicit (`random_state`).
- Preserve expected schema (`text`, `label`) unless change request says otherwise.
- Save model + encoder + metrics together in one `joblib` artifact.
- Keep Spanish normalization behavior stable unless intentionally changed.

### 6.7 LangChain/LangGraph patterns
- Keep nodes single-purpose (`normalize`, `classify`, `explain`).
- Pass explicit keys in state objects; avoid implicit shared state.
- Keep prompts deterministic for reproducible demo output.
- Avoid hidden runtime side effects inside node functions.

### 6.8 SaaS architecture guidelines
- Enforce strict tenant isolation in retrieval, memory, logs, and channel routing.
- Keep session keys tenant-aware (`company_id + session_id`) for all stores.
- Keep channel integrations idempotent (dedup webhook events by message id).
- Prefer async/background delivery for external channel APIs when possible.
- Design modules as reusable services (ingestion, retrieval, generation, channels).

### 6.9 User output and messaging
- Keep CLI output concise and actionable.
- Keep Streamlit user-facing text aligned with existing Spanish UI style.
- Avoid noisy debug printing in normal execution paths.

## 7) Hygiene rules
- Do not commit generated files: `models/`, `__pycache__/`, `*.pyc`.
- Do not commit secrets (`.env`, credentials, tokens).
- Keep `.gitignore` aligned with generated artifacts.

## 8) Agent workflow expectations
- Read relevant files before editing.
- Change only what is necessary to satisfy the task.
- Preserve public behavior unless behavior change is explicitly requested.
- When behavior changes, add/update tests and README usage notes.
- If a command cannot be run locally, state exactly what was not verified.

## 9) Pre-handoff checklist
- Touched path executes (`python -m clasificacion_langchain.cli.*` and/or `chat_api.py` as relevant).
- Syntax check passes (`python -m compileall ...`).
- Tests pass, or clearly document why they were not run.
- Documentation reflects any command/argument/behavior changes.

## 10) Strategic architecture decision (Option A)
This repository adopts **Option A** as the target evolution path:

- Keep `backend/` Python as the **AI Engine** (LangChain/LangGraph, RAG, retrieval, hybrid routing, eval workers).
- Introduce Spring Boot as **API Gateway / BFF / SaaS domain layer** (auth policy, tenancy policy, billing-facing concerns, API governance).
- Avoid big-bang rewrites. Use a **strangler pattern**: migrate endpoint groups incrementally.

### 10.1 Boundary of responsibility
- Spring Boot owns: external API facade, auth enforcement policy, tenant policy orchestration, rate limiting, contract versioning.
- Python owns: intent routing, retrieval pipeline, document chunking/indexing, LLM orchestration, AI fallback logic.

### 10.2 Integration contract
- Spring must call Python AI capabilities via explicit internal contracts (HTTP/gRPC), versioned and tenant-aware.
- Tenant identity (`company_id`) must be propagated end-to-end without lossy mapping.
- Session and idempotency keys must preserve tenant scoping semantics.

### 10.3 Agent execution guidance
- Do **not** rewrite LangChain/LangGraph internals to Java unless explicitly requested.
- Prefer extracting clean Python service contracts first, then placing Spring in front.
- Any migration proposal should include risk, rollback, and coexistence plan.

This AGENTS.md is intentionally command-heavy so autonomous coding agents can work safely and consistently.
