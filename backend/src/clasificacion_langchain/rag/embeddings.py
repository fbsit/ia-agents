from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, request

import numpy as np


@dataclass
class OpenAIEmbeddingClient:
    model: str = "text-embedding-3-small"
    timeout_seconds: int = 60
    api_key: str | None = None

    def _api_key(self) -> str:
        token = self.api_key or os.getenv("OPENAI_API_KEY", "")
        if not token:
            raise ValueError(
                "OPENAI_API_KEY no esta configurada para embeddings. "
                "Setea la variable de entorno o usa backend tfidf."
            )
        return token

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([], dtype=np.float32)

        payload = {
            "model": self.model,
            "input": texts,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/embeddings",
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
            raise RuntimeError(f"Error HTTP de OpenAI embeddings: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"No se pudo conectar con OpenAI embeddings: {exc.reason}"
            ) from exc

        data = result.get("data", [])
        if not data:
            raise RuntimeError("OpenAI embeddings no devolvio vectores")

        vectors: list[list[float]] = []
        for item in sorted(data, key=lambda x: int(x.get("index", 0))):
            embedding = item.get("embedding", [])
            vectors.append([float(value) for value in embedding])

        return np.array(vectors, dtype=np.float32)
