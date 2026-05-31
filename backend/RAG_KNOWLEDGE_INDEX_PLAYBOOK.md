# Playbook homologado: conocimiento, indice, pruebas, setup y deploy

Este documento define un contrato unico para operar RAG en este repo sin interpretaciones ambiguas.

## 1) Diseno homologado de conocimiento

Estructura canonica (obligatoria):

```text
backend/
  knowledge_base/
    <company_id>/
      facts-canonicos.md
      rules-decision-table.md
      contracts-action-schema.md
      permissions-limits-matrix.md
      feedback-execution-log.md
      *.txt|*.csv|*.json|*.pdf|*.docx
```

Reglas:

- `company_id` es el boundary de aislamiento tenant y no se mezcla entre carpetas.
- Nombre de archivos operativos base: usar los 5 templates de `knowledge_templates/operational/`.
- Formatos soportados por loader: `.txt`, `.md`, `.csv`, `.json`, `.pdf`, `.docx`.
- Si no hay texto valido extraible, el archivo no entra al indice.

## 2) Diseno homologado de indice

Artifact canonico:

- Ruta default: `backend/models/rag_index.joblib`
- Builder oficial: `backend/build_rag_index.py`
- Backends: `auto`, `tfidf`, `dense_openai`, `hybrid`

Contrato operativo:

- `auto`: usa `dense_openai` cuando existe `OPENAI_API_KEY`, si no baja a `tfidf`.
- `dense_openai` o `hybrid`: si fallan y el modo fue `auto`, el pipeline hace fallback a `tfidf`.
- Cada chunk mantiene `company_id` para filtro estricto en retrieval.

## 3) Setup homologado (local)

Desde `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Variables minimas recomendadas:

- `.env` con `AUTH_SECRET_KEY` para API autenticada.
- `OPENAI_API_KEY` solo si vas a usar `dense_openai`/`hybrid` o generacion remota.

## 4) Probar homologado (smoke + validacion)

Desde `backend/`:

```bash
python build_rag_index.py --knowledge-dir knowledge_base --index-path models/rag_index.joblib --backend auto
python -m pytest backend/tests
python -m compileall app.py train_model.py build_rag_index.py ask_hybrid_agent.py chat_api.py src
```

Smoke CLI (desde raiz del repo):

```bash
python backend/ask_hybrid_agent.py --question "Cual es el horario de soporte?" --company-id empresa_a --index-path backend/models/rag_index.joblib
```

Resultado esperado:

- El indice se genera sin mezclar tenants.
- Las respuestas incluyen evidencia cuando hay contexto recuperado.

## 5) Deploy homologado

### Opcion A: API Python directa

Desde raiz del repo:

```bash
backend/.venv/Scripts/python.exe -m uvicorn backend.chat_api:app --host 0.0.0.0 --port 8080
```

### Opcion B: stack Docker backend

Desde `backend/`:

```bash
docker compose up --build
```

### Opcion C: arquitectura objetivo (Option A)

- `platform-api` (Spring) expone fachada SaaS (auth/tenancy/gobierno API).
- `backend` (Python) queda como AI Engine (RAG/orquestacion/retrieval).
- Propagacion obligatoria de `company_id` end-to-end para tenancy.

## 6) Checklist pre-release

- Estructura `knowledge_base/<company_id>/...` valida.
- Indice reconstruido (`models/rag_index.joblib`) con backend esperado.
- Pruebas y sintaxis en verde.
- Variables de entorno criticas configuradas (`AUTH_SECRET_KEY`, `OPENAI_API_KEY` si aplica).
- Endpoint `/chat` y/o `/agents/{agent_id}/chat` validado con un `company_id` real.
