from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


def normalize_generation_provider(value: str | None) -> str:
    provider = (value or "auto").strip().lower()
    if provider in {"auto", "openai", "anthropic"}:
        return provider
    return "auto"


@dataclass
class TenantLlmSettings:
    company_id: str
    generation_provider: str
    openai_model: str
    anthropic_model: str
    openai_api_key: str
    anthropic_api_key: str
    updated_at: datetime


class TenantLlmSettingsStore(Protocol):
    def get(self, company_id: str) -> TenantLlmSettings | None:
        ...

    def save(self, settings: TenantLlmSettings) -> TenantLlmSettings:
        ...


class InMemoryTenantLlmSettingsStore:
    def __init__(self) -> None:
        self._settings_by_company: dict[str, TenantLlmSettings] = {}

    def get(self, company_id: str) -> TenantLlmSettings | None:
        return self._settings_by_company.get(company_id.strip().lower())

    def save(self, settings: TenantLlmSettings) -> TenantLlmSettings:
        key = settings.company_id.strip().lower()
        self._settings_by_company[key] = settings
        return settings


class TenantLlmSettingsService:
    def __init__(
        self,
        store: TenantLlmSettingsStore,
        default_generation_provider: str = "auto",
        default_openai_model: str = "gpt-4o-mini",
        default_anthropic_model: str = "claude-sonnet-4-6",
    ) -> None:
        self.store = store
        self.default_generation_provider = normalize_generation_provider(
            default_generation_provider
        )
        self.default_openai_model = default_openai_model
        self.default_anthropic_model = default_anthropic_model

    def get(self, company_id: str) -> TenantLlmSettings:
        normalized_company_id = company_id.strip().lower()
        if not normalized_company_id:
            raise ValueError("company_id invalido")

        existing = self.store.get(normalized_company_id)
        if existing is not None:
            return existing

        return TenantLlmSettings(
            company_id=normalized_company_id,
            generation_provider=self.default_generation_provider,
            openai_model=self.default_openai_model,
            anthropic_model=self.default_anthropic_model,
            openai_api_key="",
            anthropic_api_key="",
            updated_at=datetime.now(UTC),
        )

    def update(
        self,
        company_id: str,
        generation_provider: str | None = None,
        openai_model: str | None = None,
        anthropic_model: str | None = None,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        clear_openai_api_key: bool = False,
        clear_anthropic_api_key: bool = False,
    ) -> TenantLlmSettings:
        current = self.get(company_id)

        provider = current.generation_provider
        if generation_provider is not None:
            provider = normalize_generation_provider(generation_provider)

        next_openai_model = current.openai_model
        if openai_model is not None and openai_model.strip():
            next_openai_model = openai_model.strip()

        next_anthropic_model = current.anthropic_model
        if anthropic_model is not None and anthropic_model.strip():
            next_anthropic_model = anthropic_model.strip()

        next_openai_key = current.openai_api_key
        if clear_openai_api_key:
            next_openai_key = ""
        elif openai_api_key is not None:
            next_openai_key = openai_api_key.strip()

        next_anthropic_key = current.anthropic_api_key
        if clear_anthropic_api_key:
            next_anthropic_key = ""
        elif anthropic_api_key is not None:
            next_anthropic_key = anthropic_api_key.strip()

        updated = TenantLlmSettings(
            company_id=current.company_id,
            generation_provider=provider,
            openai_model=next_openai_model,
            anthropic_model=next_anthropic_model,
            openai_api_key=next_openai_key,
            anthropic_api_key=next_anthropic_key,
            updated_at=datetime.now(UTC),
        )
        return self.store.save(updated)
