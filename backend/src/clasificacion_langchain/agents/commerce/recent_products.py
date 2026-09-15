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
    ) or normalized in {
        "dale", "si", "ok", "oka", "va", "bueno",
        "ese", "esa", "eso", "ese mismo", "esa misma", "el mismo", "la misma", "ya ese", "ya esa",
        "si ese", "si esa", "dale ese", "dale esa", "ese porfa", "esa porfa", "ese por favor", "el primero", "la primera",
    }


def has_explicit_add_to_cart_intent(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    if is_implicit_add_to_cart_message(message):
        return True
    return bool(
        re.search(
            r"\b(?:agrega|agregame|agregar|suma|sumame|sumar|pon|poneme|poner|mete|meteme|anade|añade|llevo|dame|damelo|dejame|mejor|cambia|cambialo)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


_ORDINALS = {
    "primero": 0, "primera": 0, "primer": 0, "1": 0, "uno": 0,
    "segundo": 1, "segunda": 1, "2": 1,
    "tercero": 2, "tercera": 2, "tercer": 2, "3": 2,
    "cuarto": 3, "cuarta": 3, "4": 3,
    "quinto": 4, "quinta": 4, "5": 4,
    "ultimo": -1, "ultima": -1,
}


def ordinal_choice_from_message(message: str) -> int | None:
    """'la segunda', 'el 3', 'opcion 2', 'la ultima' -> indice en la lista de opciones mostrada.

    Un numero suelto ("2", "quiero 2") es una cantidad, no una eleccion: solo cuenta como
    ordinal si viene con articulo o con la palabra opcion/numero.
    """
    normalized = normalize_text(message)
    if not normalized:
        return None
    digit_choice = re.fullmatch(r"(?:dale |si |ok )?(?:el|la|opcion|numero|nro|la de|el de)\s+([1-5])", normalized)
    if digit_choice:
        return int(digit_choice.group(1)) - 1
    tokens = re.sub(r"\b(?:el|la|los|las|ese|esa|quiero|dale|si|ok|opcion|numero|nro)\b", " ", normalized).split()
    if not tokens or len(tokens) > 3:
        return None
    for token in tokens:
        if token in _ORDINALS and not token.isdigit():
            return _ORDINALS[token]
    return None


def confident_product_match(query: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Elige un item sin preguntar solo cuando la coincidencia es clara: un unico resultado, o
    exactamente un resultado cuyo nombre contiene todas las palabras pedidas. Si hay varias
    variantes plausibles ("confort" -> Confort Noble, Confort Swan, Manga Confort...) devuelve None
    para que el agente ofrezca las opciones y el cliente confirme.
    """
    safe_items = [item for item in items if isinstance(item, dict) and str(item.get("id") or "").strip()]
    if not safe_items:
        return None
    if len(safe_items) == 1:
        return safe_items[0]
    query_tokens = [token for token in normalize_text(query).split() if len(token) > 2 and not token.isdigit()]
    if not query_tokens:
        return None
    exact = [item for item in safe_items if normalize_text(str(item.get("name") or "")) == " ".join(query_tokens)]
    if len(exact) == 1:
        return exact[0]
    containing = [
        item for item in safe_items
        if all(token in normalize_text(str(item.get("name") or "")) for token in query_tokens)
    ]
    if len(containing) == 1:
        return containing[0]
    return None


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
