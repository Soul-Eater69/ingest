"""embeddings/factory.py – create the configured embedder."""

from ..config import EmbedProvider, settings
from .base import BaseEmbedder
from .cache import EmbeddingCache
from .openai_embedder import OpenAIEmbedder
from .sentence_transformer_embedder import SentenceTransformerEmbedder


def get_embedder(use_cache: bool | None = None) -> BaseEmbedder:
    """
    Return the configured embedding provider, optionally wrapped in a cache.

    Parameters
    ----------
    use_cache: Override settings.embed_cache_enabled.  None = use config.
    """
    if settings.embed_provider == EmbedProvider.OPENAI:
        base: BaseEmbedder = OpenAIEmbedder()
    else:
        base = SentenceTransformerEmbedder()

    should_cache = use_cache if use_cache is not None else settings.embed_cache_enabled
    if should_cache:
        return EmbeddingCache(base)
    return base
