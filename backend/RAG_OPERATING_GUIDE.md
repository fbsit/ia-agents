# RAG Operating Guide (SaaS Multi-tenant)

Guia practica para evolucionar este proyecto desde MVP a un stack RAG de calidad productiva.

## 1) Estado actual del repo (hoy)

- Retrieval backend: `tfidf` o `dense_openai`.
- Seleccion backend: `auto` usa `dense_openai` si hay `OPENAI_API_KEY`, si no `tfidf`.
- Embeddings densos: generados localmente y guardados en artifact (`joblib`), no en vector DB.
- Multi-tenant: aislamiento por `company_id` durante carga y retrieval.
- Fallback: cuando falla LLM remoto, responde en modo extractivo con evidencia.

Referencias:
- `src/clasificacion_langchain/rag/pipeline.py`
- `src/clasificacion_langchain/rag/dense_index.py`
- `src/clasificacion_langchain/rag/vector_index.py`
- `src/clasificacion_langchain/agents/service.py`

## 2) Pregunta clave: conviene vector DB?

### Si estas en fase temprana (pocos tenants/docs)

Puedes seguir con artifacts locales (`joblib`) + backend `dense_openai`.

### Si estas escalando SaaS

Si cumples 2 o mas condiciones, conviene migrar a vector DB:

- >50k chunks totales o crecimiento rapido.
- Reindex incremental frecuente (no full rebuild nocturno).
- Necesidad de filtros por metadata (tenant, permisos, tipo doc, fecha).
- SLA de latencia y disponibilidad por tenant.
- Auditoria y trazabilidad de retrieval por request.

## 3) Como lo hacen equipos grandes (patron comun)

1. Ingestion robusta
- ETL por fuente (docs internos, tickets, wikis, DB).
- Limpieza, dedupe, versionado, y metadata obligatoria.

2. Indexado hibrido
- Sparse (BM25/TFIDF) + Dense (embeddings).
- Fusion de ranking (RRF o weighted fusion).

3. Filtrado estricto
- Filtro por `company_id` (y ACL) antes de responder.
- Nunca confiar solo en similitud semantica.

4. Reranking
- Recuperar top 20-50 y rerankear top 5-10.

5. Grounding
- Respuesta obligada a citar evidencia recuperada.
- Si no hay evidencia, responder explicitamente "no tengo base suficiente".

6. Feedback loop
- Capturar thumbs up/down + correccion esperada.
- Reentrenar retrieval/prompt/reranker con ese dataset.

7. Eval continua
- Dataset dorado por tenant.
- Gates de calidad antes de desplegar.

## 4) Arquitectura recomendada para este repo

## Capa A - Ingestion

- Mantener `upload document` por agente.
- Enriquecer cada documento con metadata:
  - `company_id`
  - `agent_id`
  - `operational_section`
  - `doc_type`
  - `updated_at`
  - `source_system`

## Capa B - Retrieval

- Introducir estrategia hibrida por feature flag:
  - `RAG_RETRIEVAL_MODE=tfidf|dense|hybrid`
- Implementar RRF (Reciprocal Rank Fusion):
  - score_final = sum(1 / (k + rank_i))

## Capa C - Reranker (fase 2)

- Top-20 -> reranker -> top-5 final.
- Activacion por tenant o por agente.

## Capa D - Generation y grounding

- Mantener output con fuentes.
- Si `sources=[]`, devolver mensaje de no evidencia y sugerencia de mejora de query.

## Capa E - Observabilidad

- Log por request:
  - tenant, agent, route, retrieved_k, min_score, source_count, fallback.
- Dashboard de salud de retrieval por agente.

## 5) Roadmap por fases

## Fase 0 (1 semana) - Baseline de calidad

Objetivo: medir antes de cambiar.

- Agregar metricas por query:
  - `retrieved_chunks`
  - `avg_score`
  - `answer_with_sources_ratio`
  - `fallback_ratio`
- Definir 50 preguntas reales por tenant para evaluacion offline.

## Fase 1 (1-2 semanas) - Feedback real

Objetivo: cerrar ciclo de mejora.

- Endpoints nuevos:
  - `POST /agents/{agent_id}/feedback`
  - `GET /agents/{agent_id}/feedback/summary`
- Guardar:
  - pregunta, respuesta, fuentes, rating, comentario, expected_answer opcional.

## Fase 2 (2 semanas) - Hybrid retrieval

Objetivo: subir recall y precision.

- Implementar fusion `tfidf + dense`.
- Flag por agente para rollout gradual.
- Evaluar recall@k y precision de fuente antes/despues.

## Fase 3 (2-3 semanas) - Vector DB

Objetivo: escalar sin degradar UX.

Opciones:
- `pgvector` (si ya centralizas en Postgres).
- `Qdrant` (si quieres motor dedicado de retrieval).

Plan:
1. Adapter `VectorStore` con interfaz comun.
2. Escribir en paralelo: artifact actual + vector DB.
3. Leer por flag de tenant.
4. Cortar artifact local cuando metricas esten estables.

## Fase 4 (continuo) - Rerank + eval gate

- Reranker opcional para queries complejas.
- CI de evaluacion offline para no degradar calidad.

## 6) Decision matrix: pgvector vs Qdrant

## pgvector

Pros:
- Menos componentes (si ya usas Postgres).
- Operacion simple para equipos backend tradicionales.

Contras:
- Tunear rendimiento vectorial puede costar mas.

## Qdrant

Pros:
- Excelente DX para vector search + filtros metadata.
- Muy bueno para RAG puro con alto volumen.

Contras:
- Nuevo servicio a operar.

Recomendacion para este proyecto:
- Corto plazo: continuar con backend actual + hybrid retrieval.
- Mediano plazo (SaaS real): Qdrant o pgvector segun stack operativo del equipo.

## 7) KPIs que importan de verdad

- `answer_grounded_rate`: % respuestas con evidencia valida.
- `no_evidence_rate`: % consultas sin evidencia recuperada.
- `fallback_rate`: % consultas que no pudieron usar contexto.
- `feedback_positive_rate`: % thumbs up.
- `time_to_first_valid_agent`: tiempo desde crear agente hasta primera respuesta util.

## 8) Riesgos y controles

- Riesgo: mezcla de datos entre tenants.
  - Control: filtros estrictos `company_id` + tests de aislamiento.

- Riesgo: alucinaciones por top-k debil.
  - Control: reranker + regla de no responder sin evidencia.

- Riesgo: latencia alta.
  - Control: cache de embeddings, batch ingest, top-k adaptativo.

## 9) Checklist de implementacion minima recomendada

1. Instrumentacion retrieval por request.
2. Endpoint de feedback y tabla de auditoria.
3. Hybrid retrieval por feature flag.
4. Suite de evaluacion offline por tenant.
5. Migracion progresiva a vector DB (si metricas y volumen lo justifican).

---

Si estas arrancando comercialmente, el orden correcto es:

1) observabilidad, 2) feedback, 3) hybrid retrieval, 4) vector DB.

No al reves.
