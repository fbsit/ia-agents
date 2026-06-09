from __future__ import annotations

import importlib
import tempfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _load_api(
    monkeypatch: pytest.MonkeyPatch,
    compat_mode: str = "true",
    orchestrator_use_llm: str = "false",
):
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("CHAT_AUTH_COMPAT_MODE", compat_mode)
    run_id = uuid4().hex
    temp_root = tempfile.gettempdir()
    monkeypatch.setenv("AGENTS_KNOWLEDGE_ROOT", f"{temp_root}/clasi_agents_knowledge_{run_id}")
    monkeypatch.setenv("AGENTS_INDEX_ROOT", f"{temp_root}/clasi_agents_index_{run_id}")
    monkeypatch.setenv("PERSISTENCE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_DB_PATH", f"{temp_root}/clasi_api_{run_id}.db")
    monkeypatch.setenv("AGENT_ORCHESTRATOR_USE_LLM", orchestrator_use_llm)

    import chat_api

    module = importlib.reload(chat_api)

    class FakeChatService:
        def chat(self, request):
            return SimpleNamespace(
                trace_id="trace123",
                company_id=request.company_id,
                session_id=request.session_id,
                answer="ok",
                route="rag",
                route_reason="intent_confident",
                intent_label="faq",
                intent_confidence=0.95,
                sources=["faq.md"],
                escalation_required=False,
            )

    module.chat_service = FakeChatService()
    client = TestClient(module.app)
    return module, client


def _register(client: TestClient, email: str = "owner@demo.com", password: str = "password123"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )


def _login(client: TestClient, email: str = "owner@demo.com", password: str = "password123"):
    return client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_register_success_and_no_password_in_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)

    response = _register(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "owner@demo.com"
    assert "password" not in payload


def test_register_duplicate_email_returns_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)

    first = _register(client)
    second = _register(client)

    assert first.status_code == 200
    assert second.status_code == 409


def test_login_invalid_credentials_returns_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)

    response = _login(client, password="wrongpass")

    assert response.status_code == 401


def test_login_success_returns_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)

    response = _login(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["tokens"]["access_token"]
    assert payload["tokens"]["refresh_token"]
    assert payload["tokens"]["token_type"] == "bearer"


def test_refresh_and_logout_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)
    login_response = _login(client)
    refresh_token = login_response.json()["tokens"]["refresh_token"]

    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != refresh_token

    logout = client.post("/auth/logout", json={"refresh_token": new_refresh})
    assert logout.status_code == 200

    revoked_try = client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert revoked_try.status_code == 401


def test_me_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)

    response = client.get("/me")

    assert response.status_code == 401


def test_me_with_valid_token_returns_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)
    login_response = _login(client)
    access_token = login_response.json()["tokens"]["access_token"]

    me_response = client.get("/me", headers=_bearer(access_token))

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "owner@demo.com"


def test_org_onboarding_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)
    login_response = _login(client)
    access_token = login_response.json()["tokens"]["access_token"]

    response = client.post(
        "/orgs",
        headers=_bearer(access_token),
        json={"organization_name": "Mi Empresa", "company_id": "mi-empresa"},
    )

    assert response.status_code == 200
    assert response.json()["company_id"] == "mi-empresa"


def test_org_onboarding_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch)
    _register(client)
    login_response = _login(client)
    access_token = login_response.json()["tokens"]["access_token"]

    response = client.post(
        "/orgs",
        headers=_bearer(access_token),
        json={"organization_name": ""},
    )

    assert response.status_code == 422


def test_chat_protected_mode_requires_auth_when_compat_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")

    response = client.post(
        "/chat",
        json={"company_id": "demo", "session_id": "s1", "message": "hola"},
    )

    assert response.status_code == 401


def test_chat_compat_mode_enabled_allows_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="true")

    response = client.post(
        "/chat",
        json={"company_id": "demo", "session_id": "s1", "message": "hola"},
    )

    assert response.status_code == 200
    assert response.json()["company_id"] == "demo"


def test_chat_resolves_single_membership_when_company_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client)
    login_response = _login(client)
    access_token = login_response.json()["tokens"]["access_token"]

    client.post(
        "/orgs",
        headers=_bearer(access_token),
        json={"organization_name": "Empresa Uno", "company_id": "empresa-uno"},
    )

    chat_response = client.post(
        "/chat",
        headers=_bearer(access_token),
        json={"message": "hola"},
    )

    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["company_id"] == "empresa-uno"


def test_chat_requires_company_when_user_has_multiple_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, client = _load_api(
        monkeypatch,
        compat_mode="false",
        orchestrator_use_llm="true",
    )
    _register(client)
    login_response = _login(client)
    access_token = login_response.json()["tokens"]["access_token"]

    first_org = client.post(
        "/orgs",
        headers=_bearer(access_token),
        json={"organization_name": "Empresa Uno", "company_id": "empresa-uno"},
    )
    second_org = client.post(
        "/orgs",
        headers=_bearer(access_token),
        json={"organization_name": "Empresa Dos", "company_id": "empresa-dos"},
    )
    assert first_org.status_code == 200
    assert second_org.status_code == 200

    org_two = second_org.json()["org_id"]
    user_id = login_response.json()["user_id"]
    module.tenancy_service.membership_repository.add_membership(  # type: ignore[union-attr]
        user_id=user_id,
        org_id=org_two,
        role="owner",
    )

    chat_response = client.post(
        "/chat",
        headers=_bearer(access_token),
        json={"message": "hola"},
    )

    assert chat_response.status_code == 400


def test_chat_rejects_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")

    _register(client, email="u1@demo.com")
    u1_login = _login(client, email="u1@demo.com")
    u1_access = u1_login.json()["tokens"]["access_token"]
    org_one = client.post(
        "/orgs",
        headers=_bearer(u1_access),
        json={"organization_name": "Empresa Uno", "company_id": "empresa-uno"},
    )
    assert org_one.status_code == 200

    _register(client, email="u2@demo.com")
    u2_login = _login(client, email="u2@demo.com")
    u2_access = u2_login.json()["tokens"]["access_token"]
    org_two = client.post(
        "/orgs",
        headers=_bearer(u2_access),
        json={"organization_name": "Empresa Dos", "company_id": "empresa-dos"},
    )
    assert org_two.status_code == 200

    mismatch = client.post(
        "/chat",
        headers=_bearer(u1_access),
        json={"company_id": "empresa-dos", "message": "hola"},
    )

    assert mismatch.status_code == 403


def test_expired_access_token_returns_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ACCESS_TTL_MINUTES", "-1")
    _module, client = _load_api(monkeypatch, compat_mode="false")

    _register(client)
    login_response = _login(client)
    expired_access_token = login_response.json()["tokens"]["access_token"]

    me_response = client.get("/me", headers=_bearer(expired_access_token))

    assert me_response.status_code == 401


def test_auth_flow_does_not_log_sensitive_credentials(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _module, client = _load_api(monkeypatch)
    secret_password = "password123"

    _register(client, password=secret_password)
    login_response = _login(client, password=secret_password)
    refresh_token = login_response.json()["tokens"]["refresh_token"]

    assert secret_password not in caplog.text
    assert refresh_token not in caplog.text


def test_agents_dashboard_flow_create_upload_index_and_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _raise_openai_quota_error(_self, _messages):
        raise RuntimeError("Error HTTP de OpenAI: insufficient_quota")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _raise_openai_quota_error,
    )
    _register(client, email="owner@agent.com")
    login_response = _login(client, email="owner@agent.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Agente Demo", "company_id": "agente-demo"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Soporte Agent",
            "description": "Responde preguntas frecuentes",
            "company_id": "agente-demo",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200
    uploaded_document = upload_response.json()
    assert uploaded_document["status"] == "uploaded"

    docs_response = client.get(f"/agents/{agent_id}/documents", headers=headers)
    assert docs_response.status_code == 200
    assert len(docs_response.json()) == 1

    index_response = client.post(
        f"/agents/{agent_id}/index/rebuild",
        headers=headers,
    )
    assert index_response.status_code == 200
    assert index_response.json()["total_chunks"] >= 1

    status_response = client.get(
        f"/agents/{agent_id}/index/status",
        headers=headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["documents_indexed"] == 1

    patch_response = client.patch(
        f"/agents/{agent_id}",
        headers=headers,
        json={
            "tone": "consultivo",
            "objective": "Resolver consultas frecuentes con contexto actualizado",
            "description": "Actualizado desde test",
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["tone"] == "consultivo"

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es el horario de soporte?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["company_id"] == "agente-demo"
    assert "Horario" in payload["answer"] or "horario" in payload["answer"]

    delete_response = client.delete(
        f"/agents/{agent_id}/documents/{uploaded_document['document_id']}",
        headers=headers,
    )
    assert delete_response.status_code == 200


def test_agents_chat_without_index_falls_back_to_live_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@live-knowledge.com")
    login_response = _login(client, email="owner@live-knowledge.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Agente Live", "company_id": "agente-live"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Agent Live",
            "description": "Prueba sin indice",
            "company_id": "agente-live",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    empty_chat = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={"message": "Cual es el horario?", "top_k": 4},
    )
    assert empty_chat.status_code == 200
    empty_payload = empty_chat.json()
    assert "No tengo conocimiento" in empty_payload["answer"]
    assert empty_payload["sources"] == []

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    live_chat = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={"message": "Cual es el horario de soporte?", "top_k": 4},
    )
    assert live_chat.status_code == 200
    live_payload = live_chat.json()
    assert "Horario" in live_payload["answer"] or "horario" in live_payload["answer"]
    assert any("faq.md" in source for source in live_payload["sources"])


def test_agent_analyze_web_url_returns_structured_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, client = _load_api(monkeypatch, compat_mode="true")
    _register(client, email="owner@web-analysis.com")
    login_response = _login(client, email="owner@web-analysis.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Web", "company_id": "org-web"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Web Analyzer Agent",
            "description": "Analiza URL para conocimiento operativo",
            "company_id": "org-web",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    def _fake_analyze(url: str, timeout_seconds: int = 15, max_chars: int = 18000, max_points: int = 5):
        assert url == "https://docs.empresa.com/runbook"
        assert timeout_seconds == 15
        assert max_chars == 15000
        assert max_points == 6
        return {
            "url": url,
            "status_code": 200,
            "title": "Runbook de operaciones",
            "content_excerpt": "Checklist operativo para escalar incidentes.",
            "key_points": [
                "Definir severidad antes de ejecutar accion.",
                "Registrar ticket con owner y ETA.",
            ],
            "word_count": 42,
        }

    monkeypatch.setattr(module.AgentToolset, "analyze_web_url", staticmethod(_fake_analyze))

    response = client.post(
        f"/agents/{agent_id}/tools/analyze-url",
        headers=headers,
        json={
            "url": "https://docs.empresa.com/runbook",
            "max_chars": 15000,
            "max_points": 6,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Runbook de operaciones"
    assert payload["status_code"] == 200
    assert len(payload["key_points"]) == 2


def test_agent_analyze_web_url_rejects_invalid_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@web-analysis-invalid.com")
    login_response = _login(client, email="owner@web-analysis-invalid.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Web Invalid", "company_id": "org-web-invalid"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Web Analyzer Invalid",
            "description": "Valida esquema de URL",
            "company_id": "org-web-invalid",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    response = client.post(
        f"/agents/{agent_id}/tools/analyze-url",
        headers=headers,
        json={"url": "ftp://docs.empresa.com/runbook"},
    )
    assert response.status_code == 400
    assert "http o https" in response.json()["detail"]


def test_upload_document_upsert_replaces_previous_by_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@upsert-name.com")
    login_response = _login(client, email="owner@upsert-name.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Upsert Name", "company_id": "org-upsert-name"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Upsert Name Agent",
            "description": "Prueba replace por filename",
            "company_id": "org-upsert-name",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    first_upload = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files={
            "file": (
                "faq.md",
                b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
                "text/markdown",
            )
        },
    )
    assert first_upload.status_code == 200
    first_document_id = first_upload.json()["document_id"]

    second_upload = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files={
            "file": (
                "faq.md",
                b"Horario de soporte actualizado: lunes a viernes de 10:00 a 19:00.",
                "text/markdown",
            )
        },
    )
    assert second_upload.status_code == 200
    second_document_id = second_upload.json()["document_id"]
    assert second_document_id != first_document_id

    docs_response = client.get(f"/agents/{agent_id}/documents", headers=headers)
    assert docs_response.status_code == 200
    documents = docs_response.json()
    assert len(documents) == 1
    assert documents[0]["filename"] == "faq.md"
    assert documents[0]["document_id"] == second_document_id

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={"message": "Cual es el horario de soporte?", "top_k": 4},
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "10:00 a 19:00" in payload["answer"]


def test_upload_document_upsert_replaces_previous_by_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@upsert-checksum.com")
    login_response = _login(client, email="owner@upsert-checksum.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={
            "organization_name": "Org Upsert Checksum",
            "company_id": "org-upsert-checksum",
        },
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Upsert Checksum Agent",
            "description": "Prueba replace por checksum",
            "company_id": "org-upsert-checksum",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    first_upload = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files={
            "file": (
                "facts-canonicos-v1.md",
                b"El plazo para devoluciones en Kronix es de 30 dias corridos.",
                "text/markdown",
            )
        },
    )
    assert first_upload.status_code == 200

    second_upload = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files={
            "file": (
                "facts-canonicos-v2.md",
                b"El plazo para devoluciones en Kronix es de 30 dias corridos.",
                "text/markdown",
            )
        },
    )
    assert second_upload.status_code == 200

    docs_response = client.get(f"/agents/{agent_id}/documents", headers=headers)
    assert docs_response.status_code == 200
    documents = docs_response.json()
    assert len(documents) == 1
    assert documents[0]["filename"] == "facts-canonicos-v2.md"


def test_agents_chat_without_docs_can_answer_general_with_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _mock_openai_general_answer(_self, _messages):
        return (
            "Respuesta general: en Chile normalmente son 15 dias habiles al ano, "
            "pero puede variar por contrato o pais. Si queres precision de tu empresa, "
            "subi la politica interna."
        )

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _mock_openai_general_answer,
    )

    _register(client, email="owner@general-llm.com")
    login_response = _login(client, email="owner@general-llm.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org General", "company_id": "org-general"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "General Agent",
            "description": "Sin docs pero con LLM",
            "company_id": "org-general",
            "rag_backend": "tfidf",
            "generation_provider": "openai",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es la politica de vacaciones?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Respuesta general" in payload["answer"]
    assert payload["sources"] == []


def test_agents_chat_with_docs_but_no_retrieval_falls_back_to_general_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_RAG_MIN_SCORE", "0.95")

    def _mock_openai_general_answer(_self, _messages):
        return (
            "Respuesta general: hoy el presidente de Chile es Gabriel Boric, "
            "pero valida siempre con fuentes oficiales actualizadas."
        )

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _mock_openai_general_answer,
    )

    _register(client, email="owner@hybrid-fallback.com")
    login_response = _login(client, email="owner@hybrid-fallback.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Hybrid", "company_id": "org-hybrid"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Hybrid Agent",
            "description": "Tiene docs no relacionados",
            "company_id": "org-hybrid",
            "rag_backend": "tfidf",
            "generation_provider": "openai",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "action-plan-ui-ux-pro-max-skill.md",
            b"P1 - Token Foundation\nP2 - Accessibility Hardening\n",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "presidente de chile?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Respuesta general" in payload["answer"]
    assert payload["sources"] == []
    assert payload["route"] == "rag_live_docs"
    assert payload["response_mode"] == "live_docs_general_fallback"
    assert payload["fallback_applied"] is True
    assert payload["retrieval_min_score"] == 0.95


def test_agents_chat_ignores_stale_index_when_documents_were_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _mock_openai_general_answer(_self, _messages):
        return "Respuesta general: esto sale de LLM cuando no hay evidencia valida en documentos."

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _mock_openai_general_answer,
    )

    _register(client, email="owner@stale-index.com")
    login_response = _login(client, email="owner@stale-index.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Stale", "company_id": "org-stale"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Stale Index Agent",
            "description": "Prueba indice viejo",
            "company_id": "org-stale",
            "rag_backend": "tfidf",
            "generation_provider": "openai",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files={
            "file": (
                "faq.md",
                (
                    b"Horario de soporte: lunes a viernes de 09:00 a 18:00. "
                    b"Canal de contacto: soporte@empresa.com. "
                    b"Tiempo de respuesta esperado: 24 horas habiles."
                ),
                "text/markdown",
            )
        },
    )
    assert upload_response.status_code == 200
    document_id = upload_response.json()["document_id"]

    rebuild_response = client.post(
        f"/agents/{agent_id}/index/rebuild",
        headers=headers,
    )
    assert rebuild_response.status_code == 200

    delete_response = client.delete(
        f"/agents/{agent_id}/documents/{document_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "presidente de chile?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Respuesta general" in payload["answer"]
    assert payload["sources"] == []
    assert payload["route"] == "general_llm"
    assert payload["response_mode"] == "general_llm"
    assert payload["fallback_applied"] is False


def test_agents_chat_greeting_without_docs_returns_natural_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@greeting.com")
    login_response = _login(client, email="owner@greeting.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Greeting", "company_id": "org-greeting"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Greeting Agent",
            "description": "Saludo sin docs",
            "company_id": "org-greeting",
            "rag_backend": "tfidf",
            "generation_provider": "auto",
            "use_openai_generation": False,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "hola",
            "top_k": 4,
            "use_openai_generation": False,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Hola" in payload["answer"] or "hola" in payload["answer"]
    assert payload["sources"] == []


def test_agents_chat_company_specific_without_docs_abstains_even_with_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _should_not_call_openai(_self, _messages):
        raise AssertionError("OpenAI no deberia ejecutarse para consulta company-specific sin docs")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _should_not_call_openai,
    )

    _register(client, email="owner@company-intent.com")
    login_response = _login(client, email="owner@company-intent.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Company", "company_id": "org-company"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Company Agent",
            "description": "Sin docs, company-specific",
            "company_id": "org-company",
            "rag_backend": "tfidf",
            "generation_provider": "openai",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es la politica interna de vacaciones de nuestra empresa?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "No tengo conocimiento" in payload["answer"]
    assert payload["sources"] == []


def test_agents_chat_without_index_falls_back_when_openai_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _raise_openai_quota_error(_self, _messages):
        raise RuntimeError("Error HTTP de OpenAI: insufficient_quota")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _raise_openai_quota_error,
    )
    _register(client, email="owner@live-openai.com")
    login_response = _login(client, email="owner@live-openai.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Agente Live OpenAI", "company_id": "agente-live-openai"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Agent Live OpenAI",
            "description": "Prueba fallback OpenAI sin indice",
            "company_id": "agente-live-openai",
            "rag_backend": "tfidf",
            "use_openai_generation": True,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es el horario de soporte?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Horario" in payload["answer"] or "horario" in payload["answer"]


def test_rebuild_index_auto_falls_back_to_tfidf_when_dense_openai_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _raise_quota_error(_self, _texts):
        raise RuntimeError("Error HTTP de OpenAI embeddings: insufficient_quota")

    monkeypatch.setattr(
        "clasificacion_langchain.rag.embeddings.OpenAIEmbeddingClient.embed_texts",
        _raise_quota_error,
    )

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@fallback-index.com")
    login_response = _login(client, email="owner@fallback-index.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Fallback", "company_id": "org-fallback"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Fallback Agent",
            "description": "Valida fallback de indexado",
            "company_id": "org-fallback",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]
    assert agent_response.json()["rag_backend"] == "auto"

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    index_response = client.post(
        f"/agents/{agent_id}/index/rebuild",
        headers=headers,
    )
    assert index_response.status_code == 200
    assert index_response.json()["backend"] == "tfidf"


def test_rebuild_index_dense_openai_returns_503_when_openai_quota_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _raise_quota_error(_self, _texts):
        raise RuntimeError("Error HTTP de OpenAI embeddings: insufficient_quota")

    monkeypatch.setattr(
        "clasificacion_langchain.rag.embeddings.OpenAIEmbeddingClient.embed_texts",
        _raise_quota_error,
    )

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@dense-fail.com")
    login_response = _login(client, email="owner@dense-fail.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Dense", "company_id": "org-dense"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Dense Agent",
            "description": "Valida manejo de error dense",
            "company_id": "org-dense",
            "rag_backend": "dense_openai",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    index_response = client.post(
        f"/agents/{agent_id}/index/rebuild",
        headers=headers,
    )
    assert index_response.status_code == 503
    assert "OpenAI embeddings" in index_response.json()["detail"]


def test_agents_chat_supports_claude_generation_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RAG_GENERATION_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import AnthropicAnswerGenerator

    def _mock_claude(_self, system_prompt: str, user_prompt: str) -> str:
        return "Respuesta Claude: horario de soporte 09:00 a 18:00.\nReferencias: [1]"

    monkeypatch.setattr(
        AnthropicAnswerGenerator,
        "_anthropic_completion",
        _mock_claude,
    )

    _register(client, email="owner@claude.com")
    login_response = _login(client, email="owner@claude.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Claude", "company_id": "org-claude"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Claude Agent",
            "description": "Prueba proveedor Claude",
            "company_id": "org-claude",
            "rag_backend": "tfidf",
            "generation_provider": "anthropic",
            "use_openai_generation": True,
            "openai_model": "claude-3-5-sonnet-latest",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es el horario de soporte?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Respuesta Claude" in payload["answer"]


def test_agents_chat_allows_provider_and_model_override_from_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RAG_GENERATION_PROVIDER", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import AnthropicAnswerGenerator

    def _mock_claude(self, system_prompt: str, user_prompt: str) -> str:
        return f"Modelo activo: {self.model}\nReferencias: [1]"

    monkeypatch.setattr(
        AnthropicAnswerGenerator,
        "_anthropic_completion",
        _mock_claude,
    )

    _register(client, email="owner@override.com")
    login_response = _login(client, email="owner@override.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Override", "company_id": "org-override"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Override Agent",
            "description": "Prueba override de provider/model",
            "company_id": "org-override",
            "rag_backend": "tfidf",
            "generation_provider": "auto",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    files = {
        "file": (
            "faq.md",
            b"Horario de soporte: lunes a viernes de 09:00 a 18:00.",
            "text/markdown",
        )
    }
    upload_response = client.post(
        f"/agents/{agent_id}/documents",
        headers=headers,
        files=files,
    )
    assert upload_response.status_code == 200

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Cual es el horario de soporte?",
            "top_k": 4,
            "use_openai_generation": True,
            "generation_provider": "anthropic",
            "generation_model": "claude-3-5-haiku-latest",
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Modelo activo: claude-3-5-haiku-latest" in payload["answer"]


def test_llm_settings_endpoints_store_keys_per_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@settings.com")
    login_response = _login(client, email="owner@settings.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Settings", "company_id": "org-settings"},
    )
    assert org_response.status_code == 200

    read_response = client.get("/settings/llm?company_id=org-settings", headers=headers)
    assert read_response.status_code == 200
    initial_payload = read_response.json()
    assert initial_payload["company_id"] == "org-settings"
    assert initial_payload["openai_key_source"] in {"env", "none"}
    assert initial_payload["anthropic_key_source"] in {"env", "none"}

    update_response = client.put(
        "/settings/llm",
        headers=headers,
        json={
            "company_id": "org-settings",
            "generation_provider": "anthropic",
            "openai_model": "gpt-4.1-mini",
            "anthropic_model": "claude-3-5-sonnet-latest",
            "openai_api_key": "sk-openai-1234567890",
            "anthropic_api_key": "sk-ant-1234567890",
        },
    )
    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["generation_provider"] == "anthropic"
    assert updated_payload["has_openai_api_key"] is True
    assert updated_payload["has_anthropic_api_key"] is True
    assert updated_payload["openai_key_source"] == "tenant"
    assert updated_payload["anthropic_key_source"] == "tenant"
    assert "..." in (updated_payload["openai_api_key_masked"] or "")
    assert "..." in (updated_payload["anthropic_api_key_masked"] or "")


def test_tenant_default_provider_and_model_override_agent_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _mock_openai_completion(self, _messages):
        return f"Modelo activo: {self.model}"

    _module, client = _load_api(monkeypatch, compat_mode="false")
    from clasificacion_langchain.rag.generation import OpenAIAnswerGenerator

    monkeypatch.setattr(
        OpenAIAnswerGenerator,
        "_openai_completion",
        _mock_openai_completion,
    )

    _register(client, email="owner@tenant-default.com")
    login_response = _login(client, email="owner@tenant-default.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Tenant Default", "company_id": "org-tenant-default"},
    )
    assert org_response.status_code == 200

    settings_response = client.put(
        "/settings/llm",
        headers=headers,
        json={
            "company_id": "org-tenant-default",
            "generation_provider": "openai",
            "openai_model": "gpt-4o-mini",
        },
    )
    assert settings_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Agent Tenant Default",
            "description": "Debe usar defaults tenant",
            "company_id": "org-tenant-default",
            "rag_backend": "tfidf",
            "generation_provider": "anthropic",
            "use_openai_generation": True,
            "openai_model": "claude-sonnet-4-6",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "quien es el presidente de chile?",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "Modelo activo: gpt-4o-mini" in payload["answer"]


def test_orchestrator_can_use_llm_intent_classifier_for_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_ORCHESTRATOR_USE_LLM", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    module, client = _load_api(monkeypatch, compat_mode="true")

    assert module.agent_service is not None

    def _mock_llm_intent(**_kwargs):
        return "company_specific"

    monkeypatch.setattr(
        module.agent_service.orchestrator,
        "_llm_classify_intent",
        _mock_llm_intent,
    )

    _register(client, email="owner@llm-orchestrator.com")
    login_response = _login(client, email="owner@llm-orchestrator.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org LLM", "company_id": "org-llm"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "LLM Orchestrator Agent",
            "description": "Prueba llm intent",
            "company_id": "org-llm",
            "rag_backend": "tfidf",
            "generation_provider": "openai",
            "use_openai_generation": True,
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    chat_response = client.post(
        f"/agents/{agent_id}/chat",
        headers=headers,
        json={
            "message": "Explicame vacaciones en Chile",
            "top_k": 4,
            "use_openai_generation": True,
        },
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert "No tengo conocimiento" in payload["answer"]


def test_widget_config_and_public_chat_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "http://localhost:3000")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget.com")
    login_response = _login(client, email="owner@widget.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget", "company_id": "org-widget"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Agent",
            "description": "Canal web publico",
            "company_id": "org-widget",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()
    assert widget_payload["widget_id"] == agent_id
    assert widget_payload["widget_token"]
    assert "/public/widget/chat" in widget_payload["endpoint_url"]
    assert "/public/widget/chat" in widget_payload["snippet_html"]
    assert "visitor_id" in widget_payload["snippet_html"]
    assert "external_user_id" in widget_payload["snippet_html"]

    public_chat_response = client.post(
        "/public/widget/chat",
        headers={"Origin": "http://localhost:3000"},
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "session_id": "public-session-1",
            "message": "hola",
        },
    )
    assert public_chat_response.status_code == 200
    public_payload = public_chat_response.json()
    assert public_payload["widget_id"] == agent_id
    assert public_payload["session_id"] == "public-session-1"
    assert "Hola" in public_payload["answer"]


def test_public_widget_chat_repeat_policy_uses_generic_then_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("AGENT_CONVERSATION_POLICY_ENABLED", "true")
    monkeypatch.setenv("AGENT_CONVERSATION_STATE_BACKEND", "memory")
    monkeypatch.setenv("AGENT_REPEAT_GENERIC_THRESHOLD", "3")
    monkeypatch.setenv("AGENT_REPEAT_CACHED_THRESHOLD", "4")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-repeat.com")
    login_response = _login(client, email="owner@widget-repeat.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Repeat", "company_id": "org-widget-repeat"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Repeat Agent",
            "description": "Prueba repeticiones",
            "company_id": "org-widget-repeat",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    base_payload = {
        "widget_id": widget_payload["widget_id"],
        "widget_token": widget_payload["widget_token"],
        "session_id": "repeat-session-1",
        "visitor_id": "visitor-abc",
        "message": "cuanto demora la devolucion?",
    }

    first = client.post("/public/widget/chat", json=base_payload)
    second = client.post("/public/widget/chat", json=base_payload)
    third = client.post("/public/widget/chat", json=base_payload)
    fourth = client.post("/public/widget/chat", json=base_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert fourth.status_code == 200

    third_payload = third.json()
    fourth_payload = fourth.json()
    assert third_payload["response_mode"] == "repeat_generic"
    assert fourth_payload["response_mode"] == "repeat_cached"
    assert fourth_payload["answer"] == third_payload["answer"]


def test_public_widget_chat_close_intent_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("AGENT_CONVERSATION_POLICY_ENABLED", "true")
    monkeypatch.setenv("AGENT_CONVERSATION_STATE_BACKEND", "memory")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-close.com")
    login_response = _login(client, email="owner@widget-close.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Close", "company_id": "org-widget-close"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Close Agent",
            "description": "Prueba cierre conversacion",
            "company_id": "org-widget-close",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    close_response = client.post(
        "/public/widget/chat",
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "session_id": "close-session-1",
            "message": "gracias, eso era todo",
        },
    )
    assert close_response.status_code == 200
    payload = close_response.json()
    assert payload["response_mode"] == "conversation_closed"
    assert "cerramos por ahora" in payload["answer"].lower()


def test_chat_report_summary_with_memory_audit_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("CHAT_AUDIT_BACKEND", "memory")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-report.com")
    login_response = _login(client, email="owner@widget-report.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Report", "company_id": "org-widget-report"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Report Agent",
            "description": "Prueba reportes auditoria",
            "company_id": "org-widget-report",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    public_chat_response = client.post(
        "/public/widget/chat",
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "session_id": "report-session-1",
            "visitor_id": "visitor-report-1",
            "message": "hola",
        },
    )
    assert public_chat_response.status_code == 200

    report_response = client.get(
        "/reports/chat/summary",
        headers=headers,
        params={"company_id": "org-widget-report", "days": 30},
    )
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert len(report_payload) >= 1

    row = next(item for item in report_payload if item["agent_id"] == agent_id)
    assert row["company_id"] == "org-widget-report"
    assert row["assistant_messages"] >= 1


def test_chat_report_cost_estimate_with_memory_audit_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("CHAT_AUDIT_BACKEND", "memory")
    monkeypatch.setenv("AGENT_CONVERSATION_POLICY_ENABLED", "true")
    monkeypatch.setenv("AGENT_CONVERSATION_STATE_BACKEND", "memory")
    monkeypatch.setenv("AGENT_REPEAT_GENERIC_THRESHOLD", "3")
    monkeypatch.setenv("AGENT_REPEAT_CACHED_THRESHOLD", "4")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-cost.com")
    login_response = _login(client, email="owner@widget-cost.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Cost", "company_id": "org-widget-cost"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Cost Agent",
            "description": "Prueba costo estimado",
            "company_id": "org-widget-cost",
            "rag_backend": "tfidf",
            "use_openai_generation": True,
            "generation_provider": "openai",
            "openai_model": "gpt-4o-mini",
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    repeated_payload = {
        "widget_id": widget_payload["widget_id"],
        "widget_token": widget_payload["widget_token"],
        "session_id": "cost-session-1",
        "visitor_id": "visitor-cost-1",
        "message": "que horarios tienen?",
    }

    assert client.post("/public/widget/chat", json=repeated_payload).status_code == 200
    assert client.post("/public/widget/chat", json=repeated_payload).status_code == 200
    assert client.post("/public/widget/chat", json=repeated_payload).status_code == 200
    assert client.post("/public/widget/chat", json=repeated_payload).status_code == 200

    report_response = client.get(
        "/reports/chat/cost-estimate",
        headers=headers,
        params={
            "company_id": "org-widget-cost",
            "days": 30,
            "avg_llm_cost_usd": 0.02,
        },
    )
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert len(report_payload) >= 1

    row = next(item for item in report_payload if item["agent_id"] == agent_id)
    assert row["company_id"] == "org-widget-cost"
    assert row["assistant_messages"] >= 4
    assert row["avoided_llm_calls"] >= 2
    assert row["estimated_saved_usd"] >= 0.04


def test_public_widget_chat_rejects_invalid_token_and_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "https://miempresa.com")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-security.com")
    login_response = _login(client, email="owner@widget-security.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Sec", "company_id": "org-widget-sec"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Security Agent",
            "description": "Prueba seguridad widget",
            "company_id": "org-widget-sec",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    invalid_token_response = client.post(
        "/public/widget/chat",
        headers={"Origin": "https://miempresa.com"},
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": "invalid-token",
            "message": "hola",
        },
    )
    assert invalid_token_response.status_code == 403

    disallowed_origin_response = client.post(
        "/public/widget/chat",
        headers={"Origin": "https://otro-dominio.com"},
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "message": "hola",
        },
    )
    assert disallowed_origin_response.status_code == 403


def test_public_widget_chat_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("PUBLIC_WIDGET_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("PUBLIC_WIDGET_RATE_LIMIT_MAX_REQUESTS", "1")

    _module, client = _load_api(monkeypatch, compat_mode="false")
    _register(client, email="owner@widget-rate.com")
    login_response = _login(client, email="owner@widget-rate.com")
    access_token = login_response.json()["tokens"]["access_token"]
    headers = _bearer(access_token)

    org_response = client.post(
        "/orgs",
        headers=headers,
        json={"organization_name": "Org Widget Rate", "company_id": "org-widget-rate"},
    )
    assert org_response.status_code == 200

    agent_response = client.post(
        "/agents",
        headers=headers,
        json={
            "name": "Widget Rate Agent",
            "description": "Prueba rate limit widget",
            "company_id": "org-widget-rate",
            "rag_backend": "tfidf",
            "use_openai_generation": False,
        },
    )
    assert agent_response.status_code == 200
    agent_id = agent_response.json()["agent_id"]

    widget_response = client.get(
        f"/agents/{agent_id}/widget-config",
        headers=headers,
    )
    assert widget_response.status_code == 200
    widget_payload = widget_response.json()

    first = client.post(
        "/public/widget/chat",
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "message": "hola",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/public/widget/chat",
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "message": "hola otra vez",
        },
    )
    assert second.status_code == 429


def test_public_widget_checkout_auth_flow_uses_otp_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_WIDGET_SIGNING_SECRET", "widget-secret")
    monkeypatch.setenv("PUBLIC_WIDGET_ALLOW_ORIGINS", "http://localhost:3000")

    module, client = _load_api(monkeypatch, compat_mode="true")
    agent = module.agent_service.repository.create_agent(  # type: ignore[attr-defined]
        org_id="org-widget-checkout",
        company_id="org-widget-checkout",
        name="Widget Checkout Agent",
        objective="Flujo checkout con OTP",
        tone="claro y comercial",
        description="Flujo checkout con OTP",
        rag_backend="tfidf",
        generation_provider="openai",
        use_openai_generation=False,
        openai_model="gpt-4o-mini",
        knowledge_dir="C:/tmp/widget-checkout-knowledge",
        index_path="C:/tmp/widget-checkout-index.joblib",
    )
    widget_payload = {
        "widget_id": agent.agent_id,
        "widget_token": module._public_widget_token(agent.agent_id, agent.company_id),  # type: ignore[attr-defined]
        "endpoint_url": "/public/widget/chat",
    }

    session_id = "checkout-session-1"
    module.agent_service.update_session_summary(  # type: ignore[attr-defined]
        company_id="org-widget-checkout",
        agent_id=agent.agent_id,
        session_id=session_id,
        selected_products=["Milo"],
        workflow_stage="checkout_ready",
        pending_next_step="auth_confirmation",
        checkout_stage="auth_pending",
        customer_authenticated=False,
    )

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeToolsClient:
        def execute_canonical(
            self,
            *,
            tenant_id: str,
            tool: str,
            channel: str,
            user_id: str,
            arguments: dict[str, str],
        ):
            calls.append((tool, arguments))
            if tool == "send_verification_code":
                return {"ok": True, "data": {"ok": True, "status": "sent", "sent": True}}
            if tool == "verify_verification_code":
                return {"ok": True, "data": {"ok": True, "status": "verified", "verified": True}}
            raise AssertionError(f"Unexpected tool: {tool}")

    monkeypatch.setattr(module, "_get_clubhx_tools_client", lambda: FakeToolsClient())

    first = client.post(
        "/public/widget/chat",
        headers={"Origin": "http://localhost:3000"},
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "session_id": session_id,
            "visitor_id": "visitor-1",
            "external_user_id": "user-1",
            "message": "ehl_piphe3@outlook.com",
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert "codigo de verificacion" in first_payload["answer"].lower()

    summary_after_first = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="org-widget-checkout",
        agent_id=agent.agent_id,
        session_id=session_id,
    )
    assert summary_after_first.checkout_stage == "otp_pending"
    assert summary_after_first.pending_next_step == "otp_verification"
    assert summary_after_first.otp_email == "ehl_piphe3@outlook.com"

    second = client.post(
        "/public/widget/chat",
        headers={"Origin": "http://localhost:3000"},
        json={
            "widget_id": widget_payload["widget_id"],
            "widget_token": widget_payload["widget_token"],
            "session_id": session_id,
            "visitor_id": "visitor-1",
            "external_user_id": "user-1",
            "message": "842384",
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["intent_label"] == "checkout_auth_confirmed"

    summary_after_second = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="org-widget-checkout",
        agent_id=agent.agent_id,
        session_id=session_id,
    )
    assert summary_after_second.customer_authenticated is True
    assert summary_after_second.checkout_stage == "shipping_method_pending"
    assert summary_after_second.pending_next_step == "shipping_selection"
    assert summary_after_second.authenticated_at
    assert calls == [
        ("send_verification_code", {"email": "ehl_piphe3@outlook.com"}),
        ("verify_verification_code", {"email": "ehl_piphe3@outlook.com", "code": "842384"}),
    ]


def test_payment_options_routes_to_cart_only_on_web(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: {
            "intent": "payment_options",
            "tool": "get_payment_options",
            "query": "mercado pago",
            "needs_clarification": False,
        },
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Web redirect should not call tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-web-1",
        message="mercado pago",
        channel="widget_public",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "stage": "payment_selection",
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "payment_preference": "mercado pago",
            "customer_authenticated": "true",
        },
    )

    assert payload is not None
    assert payload["redirect_to"] == "/cart"
    assert payload["checkout_stage"] == "web_checkout_redirect"


def test_payment_options_routes_to_payment_link_on_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: {
            "intent": "payment_options",
            "tool": "get_payment_options",
            "query": "mercado pago",
            "needs_clarification": False,
        },
    )

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeToolsClient:
        def execute_canonical(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, str]):
            calls.append((tool, arguments))
            if tool == "get_product_availability":
                return {
                    "ok": True,
                    "tool": "get_product_availability",
                    "data": {
                        "items": [
                            {"id": "1", "name": "Milo", "price": 5490, "available_units": 20},
                        ]
                    },
                }
            if tool == "create_payment_link":
                return {
                    "ok": True,
                    "tool": "create_payment_link",
                    "data": {"payment_url": "https://pay.example/link", "ok": True},
                }
            raise AssertionError(f"Unexpected tool: {tool}")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-wa-1",
        message="mercado pago",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "stage": "payment_selection",
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "payment_preference": "mercado pago",
            "selected_products": "Milo",
            "customer_authenticated": "true",
        },
    )

    assert payload is not None
    assert payload.get("redirect_to") == "https://pay.example/link"
    assert payload.get("checkout_stage") == "completed"
    assert calls[0][0] == "get_product_availability"
    assert calls[1][0] == "create_payment_link"


def test_payment_options_routes_to_order_draft_on_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: {
            "intent": "payment_options",
            "tool": "get_payment_options",
            "query": "transferencia",
            "needs_clarification": False,
        },
    )

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeToolsClient:
        def execute_canonical(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, str]):
            calls.append((tool, arguments))
            if tool == "get_product_availability":
                return {
                    "ok": True,
                    "tool": "get_product_availability",
                    "data": {
                        "items": [
                            {"id": "1", "name": "Milo", "price": 5490, "available_units": 20},
                        ]
                    },
                }
            if tool == "create_order_draft":
                return {
                    "ok": True,
                    "tool": "create_order_draft",
                    "data": {"order_reference": "draft-123", "ok": True},
                }
            raise AssertionError(f"Unexpected tool: {tool}")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-wa-2",
        message="transferencia",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "stage": "payment_selection",
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "payment_preference": "transferencia",
            "selected_products": "Milo",
            "customer_authenticated": "true",
        },
    )

    assert payload is not None
    assert payload.get("checkout_stage") == "completed"
    assert calls[0][0] == "get_product_availability"
    assert calls[1][0] == "create_order_draft"


def test_payment_options_requires_auth_before_checkout_on_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: {
            "intent": "payment_options",
            "tool": "get_payment_options",
            "query": "quiero pagar",
            "needs_clarification": False,
        },
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            if kwargs.get("tool") == "get_product_availability":
                return {
                    "ok": True,
                    "tool": "get_product_availability",
                    "data": {
                        "items": [
                            {"id": "1", "name": "Milo", "price": 5490, "available_units": 20},
                        ]
                    },
                }
            raise AssertionError("Checkout should stop before payment tools when auth is missing")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-wa-auth-1",
        message="quiero pagar",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "stage": "payment_selection",
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "payment_preference": "mercado pago",
            "selected_products": "Milo",
            "customer_authenticated": False,
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "checkout_auth_needed"
    assert payload["checkout_stage"] == "auth_pending"
    assert payload["pending_next_step"] == "auth_confirmation"
    assert "inicies sesion" in payload["answer"].lower()


def test_greeting_without_active_workflow_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Greeting should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Greeting should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={},
    )

    assert payload is None


def test_greeting_with_stale_product_context_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Greeting should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Greeting should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-stale-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "selected_products": "Milo",
        },
    )

    assert payload is None


def test_greeting_with_auth_pending_workflow_returns_contextual_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Active greeting followup should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Active greeting followup should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-auth-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "checkout_stage": "auth_pending",
            "pending_next_step": "auth_confirmation",
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "checkout_auth_needed"
    assert payload["checkout_stage"] == "auth_pending"
    assert "correo" in payload["answer"].lower()


def test_greeting_with_otp_pending_workflow_returns_contextual_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Active greeting followup should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Active greeting followup should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-otp-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "checkout_stage": "otp_pending",
            "pending_next_step": "otp_verification",
            "otp_email": "ehl_piphe3@outlook.com",
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "checkout_otp_pending"
    assert payload["checkout_stage"] == "otp_pending"
    assert "codigo" in payload["answer"].lower()


def test_greeting_with_shipping_workflow_returns_contextual_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Active greeting followup should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Active greeting followup should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-shipping-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "checkout_stage": "shipping_method_pending",
            "pending_next_step": "shipping_selection",
            "selected_products": "Milo",
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "shipping_options"
    assert payload["checkout_stage"] == "shipping_method_pending"
    assert "despacho" in payload["answer"].lower() or "retiro" in payload["answer"].lower()


def test_greeting_with_order_summary_workflow_returns_contextual_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Active greeting followup should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Active greeting followup should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        user_id="user-1",
        session_id="session-greeting-summary-1",
        message="Hola",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "checkout_stage": "order_summary_pending",
            "pending_next_step": "order_confirmation",
            "selected_products": "Milo",
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "order_summary_pending"
    assert payload["checkout_stage"] == "order_summary_pending"
    assert "resumen" in payload["answer"].lower()


def test_workflow_status_question_returns_specific_active_process(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    monkeypatch.setattr(
        module,
        "_parse_commerce_intent_with_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Workflow status question should not reach the commerce LLM")),
    )

    class FakeToolsClient:
        def execute_canonical(self, **kwargs):
            raise AssertionError("Workflow status question should not call commerce tools")

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="496df3f6-46d4-4929-a352-5135e7ddae6c",
        agent_id="demo-agent",
        user_id="user-1",
        session_id="session-status-1",
        message="Que proceso es ?",
        channel="api_internal",
        clubhx_tools_client=FakeToolsClient(),
        intent_label=None,
        response_style_context="",
        workflow_state={
            "checkout_stage": "auth_pending",
            "pending_next_step": "auth_confirmation",
        },
    )

    assert payload is not None
    assert payload["intent_label"] == "checkout_auth_needed"
    assert "verificacion de acceso" in payload["answer"].lower()
    assert "correo" in payload["answer"].lower()


def test_expired_workflow_requests_confirmation_before_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    module.agent_service.update_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="expired-session",
        workflow_stage="payment_selection",
        checkout_stage="otp_pending",
        pending_next_step="otp_verification",
        selected_products=["Milo"],
        otp_email="ehl_piphe3@outlook.com",
        customer_authenticated=True,
        authenticated_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    summary = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="expired-session",
    )
    summary.updated_at = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()

    workflow_state = module._agent_workflow_state("demo-company", "demo-agent", "expired-session")  # type: ignore[attr-defined]
    assert workflow_state.get("workflow_timeout_confirmation") == "true"
    assert workflow_state.get("workflow_expired", "") == ""

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        user_id="user-1",
        session_id="expired-session",
        message="hola",
        channel="api_internal",
        clubhx_tools_client=object(),
        intent_label=None,
        response_style_context="",
        workflow_state=workflow_state,
    )

    assert payload is not None
    assert payload["intent_label"] == "workflow_resume_confirmation"
    assert "3 minutos" in payload["answer"].lower()

    summary_after = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="expired-session",
    )
    assert summary_after.checkout_stage == "otp_pending"
    assert summary_after.pending_next_step == "otp_verification"
    assert summary_after.selected_products == "Milo"
    assert summary_after.customer_authenticated is True
    assert summary_after.otp_email == "ehl_piphe3@outlook.com"
    assert summary_after.workflow_reset_started_at != ""


def test_recent_workflow_does_not_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    module.agent_service.update_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="fresh-session",
        workflow_stage="checkout_ready",
        checkout_stage="auth_pending",
        pending_next_step="auth_confirmation",
    )
    summary = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="fresh-session",
    )
    summary.updated_at = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()

    workflow_state = module._agent_workflow_state("demo-company", "demo-agent", "fresh-session")  # type: ignore[attr-defined]

    assert workflow_state.get("workflow_expired", "") == ""
    assert workflow_state["checkout_stage"] == "auth_pending"
    assert workflow_state["pending_next_step"] == "auth_confirmation"


def test_timeout_confirmation_can_resume_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    module.agent_service.update_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="resume-session",
        workflow_stage="checkout_ready",
        checkout_stage="auth_pending",
        pending_next_step="auth_confirmation",
        workflow_reset_started_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )

    workflow_state = module._agent_workflow_state("demo-company", "demo-agent", "resume-session")  # type: ignore[attr-defined]
    assert workflow_state.get("workflow_timeout_confirmation") == "true"

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        user_id="user-1",
        session_id="resume-session",
        message="si",
        channel="api_internal",
        clubhx_tools_client=object(),
        intent_label=None,
        response_style_context="",
        workflow_state=workflow_state,
    )

    assert payload is not None
    assert payload["intent_label"] == "checkout_auth_needed"
    assert "correo" in payload["answer"].lower()

    summary_after = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="resume-session",
    )
    assert summary_after.workflow_reset_started_at == ""


def test_timeout_confirmation_resets_after_additional_three_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    module.agent_service.update_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="hard-reset-session",
        workflow_stage="payment_selection",
        checkout_stage="order_summary_pending",
        pending_next_step="order_confirmation",
        selected_products=["Milo"],
        workflow_reset_started_at=(datetime.now(UTC) - timedelta(minutes=4)).isoformat(),
    )

    workflow_state = module._agent_workflow_state("demo-company", "demo-agent", "hard-reset-session")  # type: ignore[attr-defined]
    assert workflow_state == {"workflow_expired": "true"}

    payload = module._resolve_shared_commerce_payload(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        user_id="user-1",
        session_id="hard-reset-session",
        message="hola",
        channel="api_internal",
        clubhx_tools_client=object(),
        intent_label=None,
        response_style_context="",
        workflow_state=workflow_state,
    )

    assert payload is not None
    assert payload["intent_label"] == "workflow_reset"

    summary_after = module.agent_service.get_session_summary(  # type: ignore[attr-defined]
        company_id="demo-company",
        agent_id="demo-agent",
        session_id="hard-reset-session",
    )
    assert summary_after.checkout_stage == ""
    assert summary_after.pending_next_step == ""
    assert summary_after.selected_products == ""
    assert summary_after.workflow_reset_started_at == ""


def test_checkout_followup_sends_otp_and_persists_email(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeToolsClient:
        def execute_canonical(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, str]):
            calls.append((tool, arguments))
            return {"ok": True, "data": {"ok": True, "status": "sent", "sent": True}}

    payload = module._resolve_checkout_workflow_followup(  # type: ignore[attr-defined]
        message="ehl_piphe3@outlook.com",
        session_id="session-otp-1",
        workflow_state={
            "checkout_stage": "auth_pending",
            "pending_next_step": "auth_confirmation",
            "customer_authenticated": "",
            "otp_email": "",
        },
        company_id="company-1",
        channel="widget_public",
        user_id="user-1",
        clubhx_tools_client=FakeToolsClient(),
    )

    assert payload is not None
    assert payload["checkout_stage"] == "otp_pending"
    assert payload["pending_next_step"] == "otp_verification"
    assert payload["otp_email"] == "ehl_piphe3@outlook.com"
    assert calls == [("send_verification_code", {"email": "ehl_piphe3@outlook.com"})]


def test_checkout_followup_verifies_otp_success(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeToolsClient:
        def execute_canonical(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, str]):
            calls.append((tool, arguments))
            return {"ok": True, "data": {"ok": True, "status": "verified", "verified": True}}

    payload = module._resolve_checkout_workflow_followup(  # type: ignore[attr-defined]
        message="842384",
        session_id="session-otp-2",
        workflow_state={
            "checkout_stage": "otp_pending",
            "pending_next_step": "otp_verification",
            "customer_authenticated": "",
            "otp_email": "ehl_piphe3@outlook.com",
        },
        company_id="company-1",
        channel="widget_public",
        user_id="user-1",
        clubhx_tools_client=FakeToolsClient(),
    )

    assert payload is not None
    assert payload["checkout_stage"] == "shipping_method_pending"
    assert payload["pending_next_step"] == "shipping_selection"
    assert payload["intent_label"] == "checkout_auth_confirmed"
    assert calls == [("verify_verification_code", {"email": "ehl_piphe3@outlook.com", "code": "842384"})]


def test_checkout_followup_verifies_otp_rejects_invalid_code(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _client = _load_api(monkeypatch, compat_mode="false")

    class FakeToolsClient:
        def execute_canonical(self, *, tenant_id: str, tool: str, channel: str, user_id: str, arguments: dict[str, str]):
            return {"ok": True, "data": {"ok": False, "status": "invalid_code", "verified": False}}

    payload = module._resolve_checkout_workflow_followup(  # type: ignore[attr-defined]
        message="842384",
        session_id="session-otp-3",
        workflow_state={
            "checkout_stage": "otp_pending",
            "pending_next_step": "otp_verification",
            "customer_authenticated": "",
            "otp_email": "ehl_piphe3@outlook.com",
        },
        company_id="company-1",
        channel="widget_public",
        user_id="user-1",
        clubhx_tools_client=FakeToolsClient(),
    )

    assert payload is not None
    assert payload["checkout_stage"] == "otp_pending"
    assert payload["pending_next_step"] == "otp_verification"
    assert payload["intent_label"] == "checkout_otp_invalid"
