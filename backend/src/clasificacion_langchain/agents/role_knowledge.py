from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from clasificacion_langchain.agents.repository import AgentRecord
from clasificacion_langchain.rag.loaders import load_text_content
from clasificacion_langchain.rag.schemas import KnowledgeDocument


BACKEND_ROOT = Path(__file__).resolve().parents[3]
SHARED_KNOWLEDGE_ROOT = BACKEND_ROOT / "knowledge" / "shared"


@dataclass(frozen=True)
class RoleContext:
    role_key: str
    channel: str
    objective: str
    tone: str
    system_rules: str
    runtime_context: str


def role_for_channel(channel: str | None) -> str:
    normalized = (channel or "api").strip().lower()
    if "whatsapp" in normalized:
        return "whatsapp_seller"
    return "web_support_seller"


def build_role_context(agent: AgentRecord, channel: str | None) -> RoleContext:
    role_key = role_for_channel(channel)
    system_rules = _load_role_rules(role_key)
    channel_name = (channel or "api").strip() or "api"

    if role_key == "whatsapp_seller":
        role_objective = (
            "Cerrar ventas por WhatsApp siguiendo etapas claras: detectar necesidad, "
            "confirmar producto, autenticar si hace falta, definir despacho, definir pago y "
            "cerrar el siguiente paso concreto."
        )
        runtime_context = (
            "Canal actual: whatsapp. Rol operativo: vendedor conversacional por WhatsApp. "
            "Debes avanzar por etapas, pedir solo el dato minimo faltante y evitar respuestas vagas."
        )
    else:
        role_objective = (
            "Asistir la venta web resolviendo dudas, mostrando productos reales y empujando "
            "al usuario a carrito, login o checkout cuando corresponda."
        )
        runtime_context = (
            f"Canal actual: {channel_name}. Rol operativo: support/web seller. "
            "Debes responder con precision comercial, usar tools primero y orientar la compra web sin "
            "inventar un cierre conversacional fuera del canal."
        )

    base_objective = (agent.objective or "").strip()
    merged_objective = role_objective if not base_objective else f"{role_objective} Objetivo adicional del tenant: {base_objective}"

    base_tone = (agent.tone or "").strip() or "amable_directo"
    return RoleContext(
        role_key=role_key,
        channel=channel_name,
        objective=merged_objective,
        tone=base_tone,
        system_rules=system_rules,
        runtime_context=runtime_context,
    )


def sync_shared_knowledge(agent_root: Path, company_id: str) -> None:
    company_root = agent_root / company_id
    company_root.mkdir(parents=True, exist_ok=True)
    shared_targets = [
        (SHARED_KNOWLEDGE_ROOT / "common", company_root / "_shared" / "common"),
        (SHARED_KNOWLEDGE_ROOT / "roles" / "web_support_seller", company_root / "_shared" / "roles" / "web_support_seller"),
        (SHARED_KNOWLEDGE_ROOT / "roles" / "whatsapp_seller", company_root / "_shared" / "roles" / "whatsapp_seller"),
        (SHARED_KNOWLEDGE_ROOT / "learning_memory", company_root / "_shared" / "learning_memory"),
    ]
    for source_root, target_root in shared_targets:
        if not source_root.exists():
            continue
        target_root.mkdir(parents=True, exist_ok=True)
        for source in source_root.rglob("*"):
            if not source.is_file():
                continue
            target = target_root / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or source.read_bytes() != target.read_bytes():
                shutil.copyfile(source, target)


def load_local_knowledge_documents(agent_root: Path, company_id: str) -> list[KnowledgeDocument]:
    company_root = agent_root / company_id
    if not company_root.exists():
        return []

    documents: list[KnowledgeDocument] = []
    for path in sorted(company_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(company_root)
        except ValueError:
            continue
        if not str(relative).startswith("_shared"):
            continue
        try:
            text = load_text_content(path.name, path.read_bytes())
        except (OSError, RuntimeError, ValueError):
            continue
        if not text.strip():
            continue
        documents.append(
            KnowledgeDocument(
                company_id=company_id,
                source=f"shared/{relative.as_posix()}",
                text=text,
                metadata={
                    "extension": path.suffix.lower(),
                    "filename": path.name,
                    "source_type": "shared_role_knowledge",
                },
            )
        )
    return documents


def _load_role_rules(role_key: str) -> str:
    common_rules = _read_markdown_group(SHARED_KNOWLEDGE_ROOT / "common")
    role_rules = _read_markdown_group(SHARED_KNOWLEDGE_ROOT / "roles" / role_key)
    learning_rules = _read_markdown_group(SHARED_KNOWLEDGE_ROOT / "learning_memory")
    return "\n\n".join(part for part in [common_rules, role_rules, learning_rules] if part).strip()


def _read_markdown_group(root: Path) -> str:
    if not root.exists():
        return ""
    parts: list[str] = []
    for path in sorted(root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content:
            parts.append(content)
    return "\n\n".join(parts).strip()
