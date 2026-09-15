# CLI Strategy

Objetivo: dejar un solo punto de entrada CLI del backend.

Estado actual:

- existen modulos separados en `backend/src/clasificacion_langchain/cli/*`
- ya no existen scripts sueltos en `backend/`

Objetivo siguiente:

```bash
python -m clasificacion_langchain.cli <command> [...args]
```

Comandos objetivo:

- `train`
- `index`
- `ask`
- `migrate-docs`
- `eval-worker`
- `streamlit`

Beneficios:

- una sola interfaz operativa
- docs mas simples
- menos entrypoints historicos
- mejor integracion con Docker, CI y futuros jobs internos
