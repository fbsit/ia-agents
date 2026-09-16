from __future__ import annotations

"""
Nuevo chat_api: entrypoint fino, no centro de negocio.

Objetivo:
- Exponer HTTP para auth, tenancy y chat.
- Construir una sola vez el runtime de servicios.
- Delegar toda decision de negocio a servicios ya existentes.

Conexiones:
- Habla con AuthService para identidad.
- Habla con TenancyService para resolver company_id.
- Habla con ChatService para el chat legacy multi-tenant.
- Habla con AgentService para chat por agente y CRUD minimo.

Lo que SI hace:
- crea FastAPI
- registra middlewares
- inyecta dependencias
- monta routers

Lo que NO debe hacer ni en pedo:
- logica de checkout
- parseo de workflows
- routing commerce
- validaciones de dominio complejas
- acceso directo a storage salvo bootstrap
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from clasificacion_langchain.api.support.presenters import cors_allowed_origins
from clasificacion_langchain.api.support.widget import PUBLIC_API_PREFIX, PublicWidgetCORSMiddleware

from .routes.agents import router as agents_router
from .routes.auth import router as auth_router
from .routes.channels import router as channels_router
from .routes.chat import router as chat_router
from .routes.documents import router as documents_router
from .routes.evaluations import router as evaluations_router
from .routes.feedback import router as feedback_router
from .routes.indexing import router as indexing_router
from .routes.internal import router as internal_router
from .routes.jobs import router as jobs_router
from .routes.reports import router as reports_router
from .routes.retrieval import router as retrieval_router
from .routes.settings import router as settings_router
from .routes.setup import router as setup_router
from .routes.system import router as system_router
from .routes.tenancy import router as tenancy_router
from .routes.whatsapp_webhooks import router as whatsapp_webhooks_router
from .routes.widget import router as widget_router
from .runtime import build_runtime


def create_app() -> FastAPI:
    runtime = build_runtime()
    api_prefix = PUBLIC_API_PREFIX
    app = FastAPI(
        title="Clasificacion LangChain API",
        version="2.0.0-alpha",
        summary="HTTP facade minimalista para AI Engine multi-tenant",
    )
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Starlette apila los middlewares en orden inverso de registro (el ultimo
    # `add_middleware` queda mas afuera), por eso este va DESPUES de
    # CORSMiddleware: necesita quedar mas afuera para resolver el preflight y
    # los headers de esta ruta publica sin depender de la whitelist
    # restringida (localhost) de la API autenticada.
    app.add_middleware(PublicWidgetCORSMiddleware, path=f"{api_prefix}/public/widget/")
    app.include_router(system_router)
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(tenancy_router, prefix=api_prefix)
    app.include_router(chat_router, prefix=api_prefix)
    app.include_router(agents_router, prefix=api_prefix)
    app.include_router(settings_router, prefix=api_prefix)
    app.include_router(feedback_router, prefix=api_prefix)
    app.include_router(evaluations_router, prefix=api_prefix)
    app.include_router(jobs_router, prefix=api_prefix)
    app.include_router(reports_router, prefix=api_prefix)
    app.include_router(retrieval_router, prefix=api_prefix)
    app.include_router(setup_router, prefix=api_prefix)
    app.include_router(channels_router, prefix=api_prefix)
    app.include_router(documents_router, prefix=api_prefix)
    app.include_router(indexing_router, prefix=api_prefix)
    app.include_router(widget_router, prefix=api_prefix)
    app.include_router(internal_router, prefix=api_prefix)
    app.include_router(whatsapp_webhooks_router, prefix=api_prefix)
    return app


app = create_app()
