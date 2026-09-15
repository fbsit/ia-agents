# CHAT_API_DIRECTIVE.md

Directriz de reconstruccion para el backend conversacional multi-tenant.

## 1. Objetivo real

`backend/chat_api.py` no debe contener logica de negocio.

Su unico rol final es:

- bootstrap del entorno Python
- importar la app FastAPI final
- no conocer workflows, checkout, canales, RAG, prompts ni reglas de dominio

El objetivo del proyecto no es exponer endpoints sueltos. El objetivo es operar una plataforma SaaS donde una empresa:

1. crea su workspace
2. crea uno o mas agentes
3. sube conocimiento
4. despliega el agente a un canal
5. recibe mensajes
6. el sistema resuelve contexto, canal y workflow
7. responde sin perder memoria ni aislamiento tenant
8. registra feedback, evaluacion y aprendizaje operativo

## 2. Principios obligatorios

### 2.1 Multi-tenant primero

- Todo flujo debe resolver `company_id` de forma explicita.
- Toda memoria, resumen, retrieval, auditoria y feedback debe estar scopeado por tenant.
- Toda clave de sesion debe ser tenant-aware y agent-aware.

### 2.2 El canal modifica el comportamiento

- El canal no es decoracion.
- `whatsapp`, `widget`, `api`, `internal` deben cambiar contrato de respuesta, tono operativo y workflow permitido.
- La resolucion de canal debe ocurrir antes de invocar la logica del agente.

### 2.3 El agente opera por workflow, no por prompt suelto

- Un agente vendedor no responde "lo que pinte".
- Debe detectar etapa, faltantes, siguiente accion y memoria operativa.
- El workflow es un modulo propio, no un if gigante en el entrypoint.

### 2.4 La memoria no puede depender del endpoint

- La memoria de conversacion y el summary operativo viven en stores/servicios.
- El endpoint solo pasa `company_id`, `agent_id`, `session_id`, `message`, `channel`.

### 2.5 Nada hardcodeado en el runtime HTTP

- No reglas de negocio inline en routers.
- No reglas de checkout inline.
- No listas de intents o canales escondidas en `chat_api.py`.
- No configuracion por tenant hardcodeada en código.

## 3. Resultado arquitectonico esperado

## 3.1 `backend/chat_api.py`

Estado final esperado:

```python
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from clasificacion_langchain.api.app import app
```

Nada mas.

## 3.2 `clasificacion_langchain.api.app`

Debe construir y registrar:

- `FastAPI`
- middlewares
- lifecycle hooks
- dependency providers
- routers

No debe resolver negocio conversacional.

## 3.3 `clasificacion_langchain.api.runtime`

Debe construir una sola vez los servicios compartidos:

- `AuthService`
- `TenancyService`
- `ChatService`
- `AgentService`
- `TenantLlmSettingsService`
- `ChatAuditService`
- `RetrievalAuditService`
- `AgentFeedbackService`
- queues/workers configurables

Debe devolver un container explicito. Nada de globals ocultos salvo donde un worker legacy lo exija temporalmente.

## 4. Flujo operativo objetivo del agente

## 4.1 Creacion del agente

Entrada:

- `org_id`
- `company_id`
- `name`
- `objective`
- `tone`
- `rag_backend`
- `generation_provider`
- `openai_model` u otro modelo configurable

Proceso:

1. validar ownership/tenant
2. persistir `AgentRecord`
3. preparar root de conocimiento del agente
4. sincronizar conocimiento compartido por rol
5. preparar index path y stores
6. dejar agente listo para recibir documentos y mensajes

Responsable:

- `agents.service.AgentService`

## 4.2 Ingestion de conocimiento

Entrada:

- archivo
- origen
- seccion operacional opcional
- `company_id`
- `agent_id`

Proceso:

1. persistir documento
2. marcar estado `uploaded -> processing -> indexed/failed`
3. chunking
4. indexacion
5. actualizacion de artefactos

Responsables:

- `agents.service`
- `rag.*`
- worker/job layer

## 4.3 Recepcion de mensaje

Entrada canonica:

- `company_id`
- `agent_id`
- `session_id`
- `message`
- `channel`
- `visitor_id | external_user_id | user_id` segun corresponda

Proceso canonico:

1. autenticar y resolver tenant
2. resolver acceso al agente
3. resolver canal efectivo
4. cargar `RoleContext`
5. cargar memoria reciente
6. cargar summary operativo
7. evaluar policy de repeticion/escalacion
8. decidir ruta de conocimiento/orquestacion
9. ejecutar workflow de venta o respuesta general
10. normalizar respuesta segun canal
11. persistir summary, turns y auditoria

Responsables:

- `api.routes.*` solo adaptan request/response
- `agents.service.AgentService.chat()` coordina
- `agents.orchestrator.AgentIntentOrchestrator` decide ruta base
- `agents.role_knowledge` construye contexto de rol
- `agents.commerce.*` resuelve workflow comercial
- `chat.session_store` guarda memoria y summary
- `analytics.*` registra observabilidad

## 4.4 Workflow del agente vendedor

Para `whatsapp_seller`, el comportamiento esperado es por etapas:

1. detectar necesidad
2. ubicar producto o categoria
3. confirmar producto relevante
4. pedir solo el dato faltante minimo
5. definir autenticacion si aplica
6. definir despacho
7. definir pago
8. cerrar siguiente accion concreta

Esto no debe vivir en routers ni en `chat_api.py`.

Debe vivir en:

- `agents.commerce.router`
- `agents.commerce.graph`
- `agents.commerce.resolver`
- `agents.commerce.state`
- `agents.commerce.persistence`
- `agents.commerce.checkout_resolver`
- `agents.commerce.prompting`

## 4.5 Memoria operativa

El sistema debe conservar dos niveles de memoria:

### Memoria corta

- ultimos turnos
- store backend memory/redis
- usada para continuidad conversacional inmediata

### Summary operativo

- funnel stage
- checkout stage
- pending next step
- awaiting slot
- selected products
- focused product
- shipping preference
- invoice/payment data
- auth status
- cart snapshot

El summary no es un detalle opcional. Es lo que evita perder el workflow.

## 4.6 Retroalimentacion y mejora

El sistema debe soportar:

- feedback del usuario
- auditoria de retrieval
- auditoria de chat
- datasets de evaluacion
- corridas de evaluacion
- comparacion de runs

Esto debe alimentar operaciones y mejora del agente, pero NO mezclarse con el endpoint HTTP.

## 5. Modulos backend esperados

La estructura objetivo dentro de `backend/src/clasificacion_langchain/` debe quedar asi:

### `api/`

- `app.py`: composicion FastAPI
- `runtime.py`: construccion de servicios
- `dependencies.py`: auth, tenant, agent access, request context
- `routes/auth.py`
- `routes/tenancy.py`
- `routes/chat.py`
- `routes/agents.py`
- `routes/widget.py`
- `routes/channels.py`
- `routes/settings.py`
- `routes/reports.py`
- `routes/evaluations.py`
- `routes/feedback.py`
- `routes/internal.py`

### `agents/`

- `service.py`: fachada de negocio del agente
- `orchestrator.py`: decision de ruta
- `role_knowledge.py`: contexto por rol/canal
- `conversation_policy.py`: repeticion, escalacion, throttling conversacional
- `commerce/`: workflow comercial completo

### `chat/`

- `service.py`: chat tenant-based general
- `session_store.py`: historial + summary
- `memory_store.py`
- `redis_store.py`
- `schemas.py`

### `channels/`

- `whatsapp.py`
- `meta_whatsapp_api.py`
- `idempotency.py`

### `rag/`

- loaders
- chunking
- index loaders
- dense/tfidf/hybrid index
- pipeline
- generation

### `analytics/`

- `chat_audit.py`
- `retrieval_audit.py`
- `feedback_audit.py`

### `settings/`

- configuracion tenant-aware de modelos y providers

### `persistence/`

- stores de identidad, tenancy y backing infra

### `evaluation/`

- jobs y coordinacion async

## 6. Contrato del request conversacional canonico

Todo canal debe convertirse a un request interno unico:

```python
{
    "company_id": "...",
    "agent_id": "...",
    "session_id": "...",
    "message": "...",
    "channel": "whatsapp|widget|api|internal",
    "visitor_id": "...",
    "external_user_id": "...",
    "metadata": {...}
}
```

Y toda respuesta del agente deberia salir de un contrato interno comun:

```python
{
    "answer": "...",
    "sources": [...],
    "intent_label": "...",
    "route": "...",
    "route_reason": "...",
    "response_mode": "...",
    "workflow_action": {...},
    "cart_action": {...},
    "products": [...],
}
```

Luego cada canal adapta eso a su formato publico.

## 7. Reglas de implementacion

### 7.1 Routers finos

Un router solo puede:

- validar payload HTTP
- resolver auth/tenant/access
- llamar un servicio
- serializar respuesta

Un router no puede:

- resolver checkout
- inspeccionar memoria interna del workflow
- transformar negocio con regexs ad hoc
- construir prompts

### 7.2 Servicios gordos, entrypoints finos

- `chat_api.py`: minimo
- `api.app`: composicion
- `api.routes`: adaptadores
- `agents.service`: orquestacion de negocio
- `agents.commerce.*`: workflow especializado

### 7.3 Config por entorno y tenant

Todo lo variable debe venir de:

- env vars
- tenant settings
- registros persistidos
- role knowledge files

No dejar:

- company ids hardcodeados
- verify tokens hardcodeados
- modelos LLM hardcodeados dentro de rutas
- reglas de canal hardcodeadas fuera de su modulo

### 7.4 Workers desacoplados

Los workers de evaluacion, recordatorios, indexacion o delivery deben arrancar desde lifecycle/runtime, no desde un endpoint.

## 8. Cutover total deseado

El cutover correcto no es migrar endpoint por endpoint desde el monolito legacy.

Es reconstruir la app final sobre estos ejes:

1. `api.app` como unica app oficial
2. `chat_api.py` como shim minimo
3. rutas agrupadas por dominio
4. `AgentService` como backend operativo principal del agente
5. `agents.commerce.*` como backend del workflow vendedor
6. stores de memoria/summary persistentes y tenant-aware
7. canales adaptados sobre un contrato conversacional comun

Luego, si algo falta, se reconstruye en su modulo correcto. No se rescata basura del monolito por nostalgia.

## 9. Decision concreta a partir de ahora

Queda prohibido seguir agregando logica nueva en:

- `backend/chat_api.py`
- cualquier `legacy_monolith.py`

Toda funcionalidad nueva o reconstruida debe ir a:

- `backend/src/clasificacion_langchain/api/*`
- `backend/src/clasificacion_langchain/agents/*`
- `backend/src/clasificacion_langchain/channels/*`
- `backend/src/clasificacion_langchain/chat/*`

## 10. Proximo objetivo tecnico

Construir la app final en `clasificacion_langchain.api.app` con:

- runtime container unico
- routers por dominio
- dependencia comun de auth/tenant/agent access
- request/response interno canonico
- integracion con `AgentService.chat()` como flujo principal del agente vendedor

Si algo del legacy no entra en esta estructura, se reescribe con criterio operativo. No se arrastra.
