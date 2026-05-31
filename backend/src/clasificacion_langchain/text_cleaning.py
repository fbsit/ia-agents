import re
import unicodedata
from functools import lru_cache

import nltk
from nltk.corpus import stopwords
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import word_tokenize


def ensure_nltk_resources() -> None:
    resources = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
        ("corpora/stopwords", "stopwords"),
    ]
    for resource_path, download_name in resources:
        try:
            nltk.data.find(resource_path)
        except LookupError:
            nltk.download(download_name, quiet=True)


@lru_cache(maxsize=1)
def _spanish_stopwords() -> set[str]:
    ensure_nltk_resources()
    return set(stopwords.words("spanish"))


@lru_cache(maxsize=1)
def _stemmer() -> SnowballStemmer:
    return SnowballStemmer("spanish")


def _remove_url(text: str) -> str:
    return re.sub(r"http\S+", "", text)


def _remove_non_ascii(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("utf-8", "ignore")
    )


def _remove_punctuation(text: str) -> str:
    return re.sub(r"[^\w\s]", " ", text)


def normalize_text(text: str) -> str:
    ensure_nltk_resources()
    text = _remove_url(text or "")
    text = _remove_non_ascii(text)
    text = text.lower()
    text = _remove_punctuation(text)
    tokens = word_tokenize(text, language="spanish")

    stop_words = _spanish_stopwords()
    stemmer = _stemmer()

    clean_tokens = [
        stemmer.stem(token)
        for token in tokens
        if token.strip() and token not in stop_words and not token.isdigit()
    ]
    return " ".join(clean_tokens)
