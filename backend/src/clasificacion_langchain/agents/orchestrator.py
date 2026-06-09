from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib import error, request


@dataclass
class OrchestrationDecision:
    intent: str
    route: str
    reason: str


class AgentIntentOrchestrator:
    def __init__(self, use_llm: bool | None = None, timeout_seconds: int = 12) -> None:
        if use_llm is None:
            use_llm = os.getenv("AGENT_ORCHESTRATOR_USE_LLM", "true").strip().lower() == "true"
        self.use_llm = use_llm
        self.timeout_seconds = timeout_seconds

    def _llm_classify_intent(
        self,
        message: str,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
    ) -> str | None:
        provider = (generation_provider or "auto").strip().lower()
        openai_key = (openai_api_key or "").strip()
        anthropic_key = (anthropic_api_key or "").strip()

        target_provider = ""
        if provider == "openai" and openai_key:
            target_provider = "openai"
        elif provider == "anthropic" and anthropic_key:
            target_provider = "anthropic"
        elif provider == "auto":
            if openai_key:
                target_provider = "openai"
            elif anthropic_key:
                target_provider = "anthropic"

        if not target_provider:
            return None

        prompt = (
            "Clasifica la consulta en una sola intencion valida: "
            "smalltalk_greeting | company_specific | general_knowledge | unknown.\n"
            "Devuelve SOLO JSON valido con shape exacto: {\"intent\":\"...\"}.\n"
            "Reglas:\n"
            "- greeting/saludo corto => smalltalk_greeting\n"
            "- datos/politicas internas de una empresa => company_specific\n"
            "- conocimiento publico general (leyes, conceptos generales, etc.) => general_knowledge\n"
            "- si no estas seguro => unknown\n"
            f"Consulta: {message}"
        )

        try:
            if target_provider == "openai":
                payload = {
                    "model": generation_model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "Eres un clasificador de intenciones."},
                        {"role": "user", "content": prompt},
                    ],
                }
                req = request.Request(
                    url="https://api.openai.com/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {openai_key}",
                    },
                )
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = str(
                    body.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
            else:
                payload = {
                    "model": anthropic_model,
                    "max_tokens": 120,
                    "temperature": 0,
                    "system": "Eres un clasificador de intenciones.",
                    "messages": [{"role": "user", "content": prompt}],
                }
                req = request.Request(
                    url="https://api.anthropic.com/v1/messages",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                blocks = body.get("content", [])
                texts: list[str] = []
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "text":
                        continue
                    texts.append(str(block.get("text", "")))
                content = "\n".join(texts)

            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if not json_match:
                return None
            parsed = json.loads(json_match.group(0))
            intent = str(parsed.get("intent", "")).strip().lower()
            if intent in {
                "smalltalk_greeting",
                "company_specific",
                "general_knowledge",
                "unknown",
            }:
                return intent
            return None
        except (ValueError, error.HTTPError, error.URLError, TimeoutError):
            return None

    def classify_intent(
        self,
        message: str,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        llm_requested: bool,
        llm_available: bool,
    ) -> str:
        text = (message or "").strip().lower()
        if not text:
            return "unknown"

        if self.use_llm and llm_requested and llm_available:
            llm_intent = self._llm_classify_intent(
                message=message,
                generation_provider=generation_provider,
                generation_model=generation_model,
                anthropic_model=anthropic_model,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
            )
            if llm_intent is not None:
                return llm_intent
        return "unknown"

    def decide(
        self,
        message: str,
        has_uploaded_documents: bool,
        has_index_artifact: bool,
        llm_requested: bool,
        llm_available: bool,
        generation_provider: str,
        generation_model: str,
        anthropic_model: str,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
    ) -> OrchestrationDecision:
        intent = self.classify_intent(
            message=message,
            generation_provider=generation_provider,
            generation_model=generation_model,
            anthropic_model=anthropic_model,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            llm_requested=llm_requested,
            llm_available=llm_available,
        )

        if intent == "smalltalk_greeting":
            return OrchestrationDecision(
                intent=intent,
                route="greeting",
                reason="smalltalk_greeting",
            )

        if has_uploaded_documents:
            return OrchestrationDecision(
                intent=intent,
                route="rag_live_docs",
                reason="uploaded_documents_present",
            )

        if has_index_artifact:
            return OrchestrationDecision(
                intent=intent,
                route="rag_index",
                reason="index_artifact_available",
            )

        if intent == "company_specific":
            return OrchestrationDecision(
                intent=intent,
                route="no_knowledge",
                reason="company_specific_without_knowledge",
            )

        if llm_requested and llm_available:
            return OrchestrationDecision(
                intent=intent,
                route="general_llm",
                reason="general_intent_without_knowledge_use_llm",
            )

        return OrchestrationDecision(
            intent=intent,
            route="no_knowledge",
            reason="no_knowledge_and_no_llm",
        )
