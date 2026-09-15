# Backend Architecture

Documentacion arquitectonica centralizada del backend.

Contenido recomendado:

- `CHAT_API_DIRECTIVE.md` — directriz de la capa HTTP y workflow del agente
- `SAAS_PLAN.md` — objetivo producto/arquitectura SaaS
- `RAG_OPERATING_GUIDE.md` — operacion RAG multi-tenant
- `RAG_KNOWLEDGE_INDEX_PLAYBOOK.md` — contrato operativo del conocimiento e indice
- `CLAUDE.md` — mapa tecnico detallado del backend

Siguiente paso recomendado:

- centralizar todos los entrypoints CLI bajo un launcher unico (`python -m clasificacion_langchain.cli`)
- exponer subcomandos consistentes: `train`, `index`, `ask`, `migrate-docs`, `eval-worker`, `streamlit`
