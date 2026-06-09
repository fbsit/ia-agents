from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib import error, request

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from clasificacion_langchain.rag.schemas import RetrievedChunk


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+")
CHECKBOX_PATTERN = re.compile(r"\[[ xX]\]")
NUMBERED_PREFIX_PATTERN = re.compile(r"^\s*\d+\)\s*")
INLINE_NUMBERED_PATTERN = re.compile(r"(?<=\S)\s+\d+\)\s*")
REFERENCE_LINE_PATTERN = re.compile(
    r"^\s*(referencias?( usadas)?|fuentes)\s*[:：-]",
    re.IGNORECASE,
)
INLINE_REFERENCE_PATTERN = re.compile(
    r"\b(referencias?( usadas)?|fuentes)\s*[:：-].*$",
    re.IGNORECASE,
)
SECTION_HEADER_PATTERN = re.compile(
    r"^\s*(respuesta breve|que aprendemos|aprendizajes clave|referencias usadas)\s*:?$",
    re.IGNORECASE,
)
PRESENTATION_PREFIXES = (
    "Respuesta directa:",
    "Detalle relevante:",
    "Dato adicional:",
    "Objetivo del agente aplicado:",
    "Tono configurado:",
)
FACTOID_QUERY_PATTERN = re.compile(
    r"\b(cu[aá]nt[oa]s?|cu[aá]l(?:es)?|que|q)\b.*\b(d[ií]as?|plazo|horario|precio|monto|fecha|email|correo|telefono|estado)\b",
    re.IGNORECASE,
)
EXTRACTIVE_NOTICE_PATTERN = re.compile(
    r"^nota:\s+el proveedor llm no estuvo disponible temporalmente",
    re.IGNORECASE,
)
WHITESPACE_PATTERN = re.compile(r"\s+")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "on", "si", "y"}


def _no_context_mode() -> str:
    mode = os.getenv("RAG_NO_CONTEXT_MODE", "strict").strip().lower()
    if mode in {"strict", "balanced", "open"}:
        return mode
    return "strict"


def _no_context_rules() -> str:
    mode = _no_context_mode()
    include_upload_hint = _env_bool("RAG_NO_CONTEXT_UPLOAD_HINT", True)

    if mode == "open":
        rules = [
            "1) Si la consulta se puede responder con conocimiento publico/general, responde de forma orientativa.",
            "2) Aclara explicitamente que es una respuesta general y que puede variar por pais/empresa.",
            "3) Si faltan datos internos, explicita la limitacion sin bloquear toda la respuesta.",
            "4) Nunca inventes politicas internas, numeros, fechas o reglas de una empresa especifica.",
        ]
    elif mode == "balanced":
        rules = [
            "1) Si la consulta se puede responder con conocimiento publico/general, responde de forma orientativa.",
            "2) Aclara explicitamente que es una respuesta general y que puede variar por pais/empresa.",
            "3) Si la consulta pide opinion tecnica y hay evidencia suficiente en la conversacion, podes responder con una recomendacion razonada.",
            "4) Si la consulta requiere datos internos no disponibles, deci que no lo sabes con certeza.",
            "5) Nunca inventes politicas internas, numeros, fechas o reglas de una empresa especifica.",
        ]
    else:
        rules = [
            "1) Si la consulta se puede responder con conocimiento publico/general, responde de forma orientativa.",
            "2) Aclara explicitamente que es una respuesta general y que puede variar por pais/empresa.",
            "3) Si la consulta requiere datos internos de la empresa y no hay contexto, deci que no lo sabes.",
            "4) Nunca inventes politicas internas, numeros, fechas o reglas de una empresa especifica.",
        ]

    rules.append(
        f"{len(rules) + 1}) Si el usuario saluda o pregunta quien eres, responde natural y breve sin mencionar que faltan documentos, salvo que te pidan informacion interna especifica."
    )

    if include_upload_hint:
        rules.append(
            f"{len(rules) + 1}) Cerra proponiendo cargar documentos para una respuesta con evidencia."
        )

    return "\n".join(rules)


def _sanitize_for_answer(text: str) -> str:
    sanitized = WINDOWS_PATH_PATTERN.sub("[ruta_local]", text)
    sanitized = sanitized.replace(" - [ ] ", " ; pendiente: ")
    sanitized = sanitized.replace(" - [x] ", " ; completado: ")
    return sanitized


def _is_factoid_query(query: str | None) -> bool:
    if not query:
        return False
    normalized = " ".join(query.split())
    return bool(FACTOID_QUERY_PATTERN.search(normalized))


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    for part in parts:
        candidate = part.strip()
        if candidate:
            return candidate
    return text.strip()


def tune_answer_style(answer: str, query: str | None = None) -> str:
    text = (answer or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    text = INLINE_NUMBERED_PATTERN.sub("\n", text)

    normalized_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        line = NUMBERED_PREFIX_PATTERN.sub("", line).strip()
        if not line:
            continue

        if SECTION_HEADER_PATTERN.match(line):
            continue

        if REFERENCE_LINE_PATTERN.match(line):
            continue

        for prefix in PRESENTATION_PREFIXES:
            if line.lower().startswith(prefix.lower()):
                line = line[len(prefix) :].strip()
                break

        line = INLINE_REFERENCE_PATTERN.sub("", line).strip()

        if not line:
            continue

        segments = [segment.strip(" -\t") for segment in re.split(r"\s+-\s+", line)]
        for segment in segments:
            if not segment:
                continue
            normalized_lines.append(segment)

    if not normalized_lines:
        return text

    deduped: list[str] = []
    seen: set[str] = set()
    for line in normalized_lines:
        marker = line.lower()
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(line)

    compact = " ".join(deduped)
    if _is_factoid_query(query):
        first = _first_sentence(compact)
        if EXTRACTIVE_NOTICE_PATTERN.match(first):
            remaining = compact[len(first) :].strip()
            if remaining:
                return _first_sentence(remaining)
        return first

    if len(deduped) <= 3 and all(not line.startswith("-") for line in deduped):
        return compact

    return "\n".join(deduped)


def enforce_channel_response_contract(
    answer: str,
    *,
    query: str | None = None,
    channel: str | None = None,
) -> str:
    normalized = tune_answer_style(answer, query=query)
    clean_channel = (channel or "").strip().lower()
    if not normalized:
        return ""

    max_chars = 700
    max_lines = 4
    if "whatsapp" in clean_channel:
        max_chars = 420
        max_lines = 3
    elif clean_channel in {"web", "widget_web", "widget_public"}:
        max_chars = 560
        max_lines = 4

    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    compacted: list[str] = []
    for line in lines[:max_lines]:
        sentence = WHITESPACE_PATTERN.sub(" ", line).strip()
        if sentence:
            compacted.append(sentence)

    text = "\n".join(compacted) if compacted else WHITESPACE_PATTERN.sub(" ", normalized).strip()
    if len(text) <= max_chars:
        return text

    truncated = text[: max_chars - 3].rstrip(" .,;:\n") + "..."
    if "\n" in truncated:
        kept = [line.strip() for line in truncated.split("\n") if line.strip()]
        return "\n".join(kept[:max_lines])
    return truncated


def _truncate(text: str, max_chars: int = 420) -> str:
    normalized = _normalize_text(_sanitize_for_answer(text))
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1].rstrip()}..."


def _presentation_score(chunk: RetrievedChunk) -> float:
    text = chunk.text
    heading_bonus = 0.08 if "##" in text or "# " in text else 0.0
    path_penalty = min(0.16, 0.04 * len(WINDOWS_PATH_PATTERN.findall(text)))
    checklist_penalty = min(0.08, 0.01 * len(CHECKBOX_PATTERN.findall(text)))
    return chunk.score + heading_bonus - path_penalty - checklist_penalty


def _fallback_no_context_answer(query: str) -> str:
    return (
        "No tengo conocimiento cargado suficiente en este momento. "
        "Si queres, subi documentos y te respondo con evidencia."
    )


def format_context(
    chunks: list[RetrievedChunk],
    max_chunks: int = 6,
    max_chars_per_chunk: int = 750,
) -> str:
    lines: list[str] = []
    for idx, chunk in enumerate(chunks[:max_chunks], start=1):
        excerpt = _truncate(chunk.text, max_chars=max_chars_per_chunk)
        lines.append(
            f"[{idx}] source={chunk.source} score={chunk.score:.4f} text={excerpt}"
        )
    return "\n".join(lines)


class AnswerGenerator(Protocol):
    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        objective: str | None = None,
        tone: str | None = None,
        system_rules: str | None = None,
    ) -> str:
        ...


@dataclass
class ExtractiveAnswerGenerator:
    openai_requested: bool = False
    openai_available: bool = True

    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        objective: str | None = None,
        tone: str | None = None,
        system_rules: str | None = None,
    ) -> str:
        if not chunks:
            lines = [_fallback_no_context_answer(query)]
            if self.openai_requested and not self.openai_available:
                lines.append(
                    "Nota: no hay un proveedor LLM activo, por eso respondo con el contexto disponible."
                )
            return tune_answer_style("\n".join(lines), query=query)

        ranked_chunks = sorted(chunks[:6], key=_presentation_score, reverse=True)
        top_chunks = ranked_chunks[:3]
        summary_parts = [_truncate(chunk.text, max_chars=250) for chunk in top_chunks]

        lines: list[str] = []
        if self.openai_requested and not self.openai_available:
            lines.append("Respondo en modo extractivo con evidencia del conocimiento cargado.")

        lines.append(summary_parts[0])
        if len(summary_parts) > 1:
            lines.append(f"Ademas, {summary_parts[1]}")
        if len(summary_parts) > 2:
            lines.append(f"Tambien, {summary_parts[2]}")

        return tune_answer_style("\n".join(lines), query=query)


@dataclass
class OpenAIAnswerGenerator:
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 60
    api_key: str | None = None
    _answer_chain: object | None = field(default=None, init=False, repr=False)

    def _api_key(self) -> str:
        token = self.api_key or os.getenv("OPENAI_API_KEY", "")
        if not token:
            raise ValueError(
                "OPENAI_API_KEY no esta configurada. "
                "Setea la variable de entorno o usa modo extractivo."
            )
        return token

    def _to_openai_messages(self, messages: list[BaseMessage]) -> list[dict[str, str]]:
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
        }
        formatted: list[dict[str, str]] = []
        for message in messages:
            raw_content = message.content
            if isinstance(raw_content, list):
                parts: list[str] = []
                for item in raw_content:
                    if isinstance(item, dict):
                        parts.append(str(item.get("text", "")))
                    else:
                        parts.append(str(item))
                content = " ".join(parts).strip()
            else:
                content = str(raw_content).strip()

            formatted.append(
                {
                    "role": role_map.get(message.type, "user"),
                    "content": content,
                }
            )
        return formatted

    def _openai_completion(self, messages: list[BaseMessage]) -> str:
        openai_messages = self._to_openai_messages(messages)
        payload = {
            "model": self.model,
            "temperature": 0.15,
            "messages": openai_messages,
        }

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Error HTTP de OpenAI: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"No se pudo conectar con OpenAI: {exc.reason}") from exc

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI no devolvio respuestas")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise RuntimeError("OpenAI devolvio contenido vacio")

        return str(content)

    def _build_answer_chain(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "Sos un asistente empresarial experto en capacitacion interna. "
                        "Responde SIEMPRE en espanol profesional, claro y didactico. "
                        "Usa solo la evidencia del contexto recuperado. "
                        "Si no alcanza la evidencia, dilo explicitamente y pedi mas contexto. "
                        "Objetivo del agente: {objective}. "
                        "Tono requerido: {tone}. "
                        "Reglas del rol y conocimiento compartido: {system_rules}."
                    ),
                ),
                (
                    "human",
                    (
                        "Pregunta del usuario:\n{query}\n\n"
                        "Contexto recuperado:\n{context_block}\n\n"
                        "Formato de salida obligatorio:\n"
                        "- Responde en espanol natural, en 1 o 2 parrafos breves.\n"
                        "- NO uses numeracion tipo 1), 2), 3) ni titulos de seccion.\n"
                        "- NO incluyas lineas de 'Fuentes' o 'Referencias'; se muestran por separado."
                    ),
                ),
            ]
        )

        llm_step = RunnableLambda(
            lambda prompt_value: self._openai_completion(prompt_value.to_messages())
        )
        return prompt | llm_step

    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        objective: str | None = None,
        tone: str | None = None,
        system_rules: str | None = None,
    ) -> str:
        if not chunks:
            rules = _no_context_rules()
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "Sos un asistente conversacional empresarial. "
                            "Responde SIEMPRE en espanol natural y cercano. "
                            "No repitas el contexto operativo ni el resumen como si fueran parte de la respuesta. "
                            "Reglas obligatorias:\n"
                            f"{rules}\n\n"
                            "Reglas del rol y conocimiento compartido:\n"
                            f"{system_rules or 'Sin reglas adicionales.'}"
                        ),
                    ),
                    (
                        "human",
                        (
                            "Consulta del usuario: {query}\n"
                            "Objetivo del agente: {objective}\n"
                            "Tono requerido: {tone}\n"
                            "No hay contexto recuperado para esta consulta. Responde igual de forma util si la consulta es un saludo, identidad o una pregunta operativa general."
                        ),
                    ),
                ]
            )
            messages = prompt.format_messages(
                query=query,
                objective=objective or "Resolver consultas de negocio con precision",
                tone=tone or "profesional",
                system_rules=system_rules or "Sin reglas adicionales.",
            )
            content = self._openai_completion(messages).strip()
            if not content:
                return _fallback_no_context_answer(query)
            return tune_answer_style(content, query=query)

        if self._answer_chain is None:
            self._answer_chain = self._build_answer_chain()

        context_block = format_context(chunks)
        response = self._answer_chain.invoke(
            {
                "query": query,
                "context_block": context_block,
                "objective": objective or "Resolver consultas de negocio con precision",
                "tone": tone or "profesional",
                "system_rules": system_rules or "Sin reglas adicionales.",
            }
        )

        content = str(response).strip()
        if not content:
            raise RuntimeError("OpenAI devolvio contenido vacio")

        return tune_answer_style(content, query=query)


@dataclass
class AnthropicAnswerGenerator:
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = 60
    api_key: str | None = None

    def _api_key(self) -> str:
        token = self.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not token:
            raise ValueError(
                "ANTHROPIC_API_KEY no esta configurada. "
                "Setea la variable de entorno o usa modo extractivo."
            )
        return token

    def _anthropic_completion(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 700,
            "temperature": 0.15,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url="https://api.anthropic.com/v1/messages",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key(),
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Error HTTP de Claude/Anthropic: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"No se pudo conectar con Claude/Anthropic: {exc.reason}"
            ) from exc

        blocks = result.get("content", [])
        texts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = str(block.get("text", "")).strip()
            if text:
                texts.append(text)

        content = "\n".join(texts).strip()
        if not content:
            raise RuntimeError("Claude/Anthropic devolvio contenido vacio")
        return content

    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        objective: str | None = None,
        tone: str | None = None,
        system_rules: str | None = None,
    ) -> str:
        if not chunks:
            rules = _no_context_rules()
            system_prompt = (
                "Sos un asistente conversacional empresarial. "
                "Responde SIEMPRE en espanol natural y cercano. "
                "No repitas el contexto operativo ni el resumen como si fueran parte de la respuesta. "
                "Reglas obligatorias:\n"
                f"{rules}\n\n"
                "Reglas del rol y conocimiento compartido:\n"
                f"{system_rules or 'Sin reglas adicionales.'}"
            )
            user_prompt = (
                f"Consulta del usuario: {query}\n"
                f"Objetivo del agente: {objective or 'Resolver consultas de negocio con precision'}\n"
                f"Tono requerido: {tone or 'profesional'}\n"
                "No hay contexto recuperado para esta consulta. Responde igual de forma util si la consulta es un saludo, identidad o una pregunta operativa general."
            )
            content = self._anthropic_completion(system_prompt=system_prompt, user_prompt=user_prompt)
            if not content:
                return _fallback_no_context_answer(query)
            return tune_answer_style(content, query=query)

        context_block = format_context(chunks)
        system_prompt = (
            "Sos un asistente empresarial experto en capacitacion interna. "
            "Responde SIEMPRE en espanol profesional, claro y didactico. "
            "Usa solo la evidencia del contexto recuperado. "
            "Si no alcanza la evidencia, dilo explicitamente y pedi mas contexto. "
            f"Objetivo del agente: {objective or 'Resolver consultas de negocio con precision'}. "
            f"Tono requerido: {tone or 'profesional'}. "
            f"Reglas del rol y conocimiento compartido: {system_rules or 'Sin reglas adicionales.'}."
        )
        user_prompt = (
            "Pregunta del usuario:\n"
            f"{query}\n\n"
            "Contexto recuperado:\n"
            f"{context_block}\n\n"
            "Formato de salida obligatorio:\n"
            "- Responde en espanol natural, en 1 o 2 parrafos breves.\n"
            "- NO uses numeracion tipo 1), 2), 3) ni titulos de seccion.\n"
            "- NO incluyas lineas de 'Fuentes' o 'Referencias'; se muestran por separado."
        )

        content = self._anthropic_completion(system_prompt=system_prompt, user_prompt=user_prompt)
        return tune_answer_style(content, query=query)


def normalize_generation_provider(provider: str | None) -> str:
    value = (provider or "auto").strip().lower()
    if value in {"openai", "anthropic", "auto"}:
        return value
    return "auto"


def build_remote_generator(
    model: str,
    generation_provider: str | None = None,
    anthropic_model: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
) -> AnswerGenerator | None:
    provider = normalize_generation_provider(generation_provider)
    effective_openai_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
    effective_anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
    openai_available = bool(effective_openai_key)
    anthropic_available = bool(effective_anthropic_key)

    if provider == "openai":
        if not openai_available:
            return None
        return OpenAIAnswerGenerator(model=model, api_key=effective_openai_key)

    if provider == "anthropic":
        if not anthropic_available:
            return None
        selected_model = anthropic_model or os.getenv(
            "ANTHROPIC_MODEL", "claude-sonnet-4-6"
        )
        return AnthropicAnswerGenerator(model=selected_model, api_key=effective_anthropic_key)

    if openai_available:
        return OpenAIAnswerGenerator(model=model, api_key=effective_openai_key)
    if anthropic_available:
        selected_model = anthropic_model or os.getenv(
            "ANTHROPIC_MODEL", "claude-sonnet-4-6"
        )
        return AnthropicAnswerGenerator(model=selected_model, api_key=effective_anthropic_key)
    return None


def is_remote_generator(generator: AnswerGenerator) -> bool:
    return isinstance(generator, (OpenAIAnswerGenerator, AnthropicAnswerGenerator))
