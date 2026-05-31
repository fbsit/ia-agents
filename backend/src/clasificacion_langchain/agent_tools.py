from __future__ import annotations

from dataclasses import dataclass
import re
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request

from clasificacion_langchain.intent_router import IntentRouter
from clasificacion_langchain.rag.pipeline import RAGPipeline
from clasificacion_langchain.rag.schemas import RAGAnswer


@dataclass
class AgentToolset:
    rag_pipeline: RAGPipeline
    intent_router: IntentRouter | None = None

    def classify_intent(self, text: str) -> dict[str, object]:
        if self.intent_router is None:
            return {
                "label": "sin_router",
                "confidence": 1.0,
                "scores": {},
            }

        prediction = self.intent_router.predict(text)
        return {
            "label": prediction.label,
            "confidence": prediction.confidence,
            "scores": prediction.scores,
        }

    def answer_company_question(
        self,
        query: str,
        company_id: str,
        top_k: int = 4,
        generation_provider: str | None = None,
        generation_model: str | None = None,
        use_openai_generation: bool | None = None,
    ) -> RAGAnswer:
        return self.rag_pipeline.answer(
            query=query,
            company_id=company_id,
            top_k=top_k,
            generation_provider=generation_provider,
            generation_model=generation_model,
            use_openai_generation=use_openai_generation,
        )

    @staticmethod
    def analyze_web_url(
        url: str,
        timeout_seconds: int = 15,
        max_chars: int = 18000,
        max_points: int = 5,
    ) -> dict[str, object]:
        cleaned_url = (url or "").strip()
        if not cleaned_url:
            raise ValueError("url vacia")

        parsed = urllib_parse.urlparse(cleaned_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("La URL debe usar http o https")

        req = urllib_request.Request(
            url=cleaned_url,
            method="GET",
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CHR-Agent/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=max(3, timeout_seconds)) as response:
                status_code = int(getattr(response, "status", 200) or 200)
                charset = "utf-8"
                try:
                    detected = response.headers.get_content_charset()  # type: ignore[attr-defined]
                    if detected:
                        charset = detected
                except Exception:
                    pass
                html = response.read().decode(charset, errors="replace")
        except urllib_error.HTTPError as exc:
            raise RuntimeError(f"Error HTTP al consultar URL: {exc.code}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"No se pudo consultar URL: {exc.reason}") from exc

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else "Sin titulo"

        no_script = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE)
        no_style = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", no_script, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", no_style)
        text = re.sub(r"\s+", " ", text).strip()
        content = text[: max(500, max_chars)]

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", content)
            if sentence.strip()
        ]
        key_points = sentences[: max(1, max_points)]

        return {
            "url": cleaned_url,
            "status_code": status_code,
            "title": title,
            "content_excerpt": content[:1200],
            "key_points": key_points,
            "word_count": len(content.split()),
        }
