# clasificacion-langchain-demo

Monorepo con proyectos separados para backend Python y frontend Next.js.

## Estructura

```text
clasificacion-langchain-demo/
  backend/   # API FastAPI + ML/RAG + scripts de entrenamiento
  frontend/  # App Next.js
  platform-api/ # Spring Boot API Gateway / BFF
  archive/   # Artefactos legacy (incluye apps/web previo)
```

## Backend

- Ubicacion: `backend/`
- Guia principal: `backend/README.md`
- Playbook homologado de conocimiento/indice/pruebas/setup/deploy: `backend/RAG_KNOWLEDGE_INDEX_PLAYBOOK.md`
- Run rapido:

```bash
uvicorn backend.chat_api:app --host 0.0.0.0 --port 8080
```

## Frontend

- Ubicacion: `frontend/`
- Variable base URL: `NEXT_PUBLIC_PLATFORM_API_BASE_URL` (default `http://localhost:8081`)
- Run rapido (desde `frontend/`):

```bash
npm run dev
```

## Spring Boot (API Gateway/BFF)

- Ubicacion: `platform-api/`
- Run rapido (desde `platform-api/`):

```bash
./mvnw spring-boot:run
```

En Windows PowerShell tambien podes usar:

```bash
.\mvnw.cmd spring-boot:run
```

Endpoints de auth migrados en Spring:

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /me`

Endpoints de tenancy ya expuestos en Spring:

- `POST /orgs`
- `GET /orgs`

Endpoints de catalogo (MVP draft) en Spring:

- `POST /skills`
- `GET /skills?org_id=...&company_id=...`
- `PATCH /skills/{skillId}`
- `POST /skills/{skillId}/publish`
- `POST /skills/{skillId}/execute`
- `POST /flows`
- `GET /flows?org_id=...&company_id=...`
- `PATCH /flows/{flowId}`
- `POST /flows/{flowId}/publish`
- `POST /flows/{flowId}/execute`

Nota: `execute` actualmente usa contrato interno con AI Engine y retorna stub de runtime (base para conectar ejecucion LangChain/LangGraph en siguientes iteraciones).

## Nota

Se conservo una copia del frontend anterior en `archive/apps-web-legacy/` para referencia/migracion.

## Decision de arquitectura (Option A)

Para alinear futuros prompts/agentes, la evolucion definida es:

- `backend/` (Python) se mantiene como **AI Engine**: LangChain/LangGraph, RAG, retrieval, workers y fallback.
- Spring Boot se agrega como **API Gateway/BFF y capa SaaS**: auth (migrada), tenancy policy, billing-facing concerns y gobierno de API.
- Migracion incremental con **strangler pattern**, evitando reescritura total de IA en Java.

Frontend debe consumir `platform-api` para auth/tenancy y usar Python para capacidades de IA via gateway.
