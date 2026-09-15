from __future__ import annotations

import re
import unicodedata
from typing import Any


QUANTITY_WORDS: dict[str, int] = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


def normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"[^a-zA-Z0-9\s]+", " ", normalized).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def serialize_recent_products_for_llm(recent_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for index, product in enumerate(recent_products[:6], start=1):
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        if not name:
            continue
        serialized.append(
            {
                "position": index,
                "name": name,
                "price": str(product.get("price") or "").strip(),
                "stock": str(product.get("stock") or "").strip(),
            }
        )
    return serialized


def is_implicit_add_to_cart_message(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(
        phrase in normalized
        for phrase in [
            "agregalo",
            "agregala",
            "agregale",
            "agregamelo",
            "agregamela",
            "agregalos",
            "agregalas",
            "dale agregalo",
            "dale agregamelo",
            "dale agregale",
            "si agregalo",
            "si agregamelo",
            "si agregala",
            "agregalo al carrito",
            "agregamelo al carrito",
            "ponelo en el carrito",
            "ponela en el carrito",
            "metelo al carrito",
            "metela al carrito",
        ]
    ) or normalized in {"dale", "si", "ok", "oka", "va", "bueno"}


def has_explicit_add_to_cart_intent(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    if is_implicit_add_to_cart_message(message):
        return True
    return bool(
        re.search(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|añade|llevo)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def match_recent_product_from_message(message: str, recent_products: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_message = normalize_text(message)
    if not normalized_message or not recent_products:
        return None
    stripped_message = re.sub(
        r"\b(?:el|la|los|las|un|una|unos|unas|quiero|llevo|dame|me|porfa|por|favor)\b",
        " ",
        normalized_message,
        flags=re.IGNORECASE,
    )
    stripped_message = re.sub(r"\s+", " ", stripped_message).strip()
    for product in recent_products:
        if not isinstance(product, dict):
            continue
        product_name = str(product.get("name") or "").strip()
        normalized_name = normalize_text(product_name)
        if not normalized_name:
            continue
        if normalized_message == normalized_name or stripped_message == normalized_name:
            return product
        if stripped_message and stripped_message in normalized_name:
            return product
    return None


def is_quantity_only_followup(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    if normalized.isdigit() or normalized in QUANTITY_WORDS:
        return True
    return bool(re.fullmatch(r"(?:si\s+)?(?:quiero\s+)?\d+", normalized))


def parse_quantity(text: str) -> int:
    tokens = normalize_text(text).split()
    for token in tokens[:4]:
        if token.isdigit():
            return max(1, min(99, int(token)))
        if token in QUANTITY_WORDS:
            return QUANTITY_WORDS[token]
    return 1
