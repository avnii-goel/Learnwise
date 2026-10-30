"""Dense vector embedding components for LearnWise Recommender Engine.

Supports:
- Embedder Protocol interface with model_name and embed() returning L2-normalized vectors.
- FastEmbedEmbedder using ONNX runtime and local repository cache (.cache/fastembed).
- FakeEmbedder using deterministic hashing bag-of-words for zero-download test isolation.
- Factory get_embedder() switching on EMBEDDER_BACKEND env var.
- Text representation builders and SHA-256 fingerprinting.

Reference: docs/RECOMMENDER.md Section 3.
"""

import hashlib
import math
import os
import re
from typing import Any, Protocol, runtime_checkable

from app.recommender.config import (
    MODEL_NAME,
    FALLBACK_MODEL_NAME,
    EMBEDDING_DIM,
)

# Absolute path to .cache/fastembed inside repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
DEFAULT_CACHE_DIR = os.path.join(REPO_ROOT, ".cache", "fastembed")


@runtime_checkable
class Embedder(Protocol):
    """Protocol defining the embedding provider contract."""
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of texts into L2-normalized float vectors."""
        ...


def resolve_fastembed_model_name() -> str:
    """Verifies primary model support in fastembed, falling back if necessary."""
    try:
        from fastembed import TextEmbedding
        supported = [m["model"] for m in TextEmbedding.list_supported_models()]
        if MODEL_NAME in supported:
            return MODEL_NAME
        if FALLBACK_MODEL_NAME in supported:
            return FALLBACK_MODEL_NAME
    except Exception:
        pass
    return MODEL_NAME


class FastEmbedEmbedder:
    """Lazy-loaded FastEmbed ONNX embedding model with local cache."""

    _cached_model: Any = None
    _actual_model_name: str | None = None

    def __init__(self, model_name: str | None = None, cache_dir: str | None = None):
        self.model_name = model_name or resolve_fastembed_model_name()
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR

    def _get_model(self) -> Any:
        if (
            FastEmbedEmbedder._cached_model is None
            or FastEmbedEmbedder._actual_model_name != self.model_name
        ):
            from fastembed import TextEmbedding
            os.makedirs(self.cache_dir, exist_ok=True)
            FastEmbedEmbedder._cached_model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=self.cache_dir,
            )
            FastEmbedEmbedder._actual_model_name = self.model_name
        return FastEmbedEmbedder._cached_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of texts using fastembed ONNX runtime."""
        if not texts:
            return []
        model = self._get_model()
        raw_embeddings = model.embed(texts)
        results: list[list[float]] = []
        for emb in raw_embeddings:
            vec = emb.tolist() if hasattr(emb, "tolist") else list(emb)
            if len(vec) != EMBEDDING_DIM:
                raise ValueError(
                    f"Unexpected vector dimension: expected {EMBEDDING_DIM}, got {len(vec)}"
                )
            # Ensure strict L2-normalization
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            results.append(vec)
        return results


class FakeEmbedder:
    """Deterministic, hashing bag-of-words embedder for test isolation."""

    model_name: str = "fake-hash-384"

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch of texts into deterministic L2-normalized vectors."""
        return [self._embed_single(t) for t in texts]

    def _embed_single(self, text: str) -> list[float]:
        tokens = re.findall(r"\b\w+\b", text.lower())
        if not tokens:
            val = 1.0 / math.sqrt(EMBEDDING_DIM)
            return [val] * EMBEDDING_DIM

        vec = [0.0] * EMBEDDING_DIM
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
            vec[idx] += 1.0

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            return [x / norm for x in vec]
        val = 1.0 / math.sqrt(EMBEDDING_DIM)
        return [val] * EMBEDDING_DIM


# Cached embedder instances for get_embedder()
_singleton_fake: FakeEmbedder | None = None
_singleton_fastembed: FastEmbedEmbedder | None = None


def get_embedder() -> Embedder:
    """Returns active embedder based on EMBEDDER_BACKEND environment variable."""
    backend = os.getenv("EMBEDDER_BACKEND", "").strip().lower()
    if backend == "fake":
        global _singleton_fake
        if _singleton_fake is None:
            _singleton_fake = FakeEmbedder()
        return _singleton_fake

    global _singleton_fastembed
    if _singleton_fastembed is None:
        _singleton_fastembed = FastEmbedEmbedder()
    return _singleton_fastembed


def build_resource_text(topic_title: str, title: str, description: str) -> str:
    """Builds the canonical embedded representation for a learning resource."""
    return f"{topic_title.strip()}. {title.strip()}. {description.strip()}"


def embedding_hash(model_name: str, text: str) -> str:
    """Computes a SHA-256 fingerprint for model_name and text."""
    content = f"{model_name}\n{text}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()

