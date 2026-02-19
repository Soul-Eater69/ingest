"""
embeddings/sentence_transformer_embedder.py
============================================
Local embedding using HuggingFace sentence-transformers.

Why sentence-transformers?
  - No API key required
  - Fully private (data never leaves your machine)
  - Works offline
  - BAAI/bge-base-en-v1.5 is competitive with OpenAI ada-002 on code tasks

GPU acceleration
----------------
Set CIDX_ST_DEVICE=cuda (or "mps" on Apple Silicon) to use GPU.
Batch size should be increased when using GPU (default 64 is for CPU).

Normalisation
-------------
We call encode() with normalize_embeddings=True so all vectors are unit
length.  This makes cosine similarity equivalent to dot product, which is
what most vector stores optimise for.
"""

from __future__ import annotations

from typing import Optional

from ..config import settings
from ..utils.concurrency import run_in_executor
from ..utils.logging import get_logger
from .base import BaseEmbedder

logger = get_logger(__name__)


class SentenceTransformerEmbedder(BaseEmbedder):
    """
    Local embedding using sentence-transformers.

    The model is loaded lazily on first use so importing this module
    does not download anything.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        self._model_name = model_name or settings.st_model_name
        self._device     = device     or settings.st_device
        self._batch_size = batch_size or settings.st_batch_size
        self._model: object | None = None

    @property
    def dimensions(self) -> int:
        # Common model dimensions – actual value read from model at load time
        _DIM_MAP = {
            "BAAI/bge-base-en-v1.5":   768,
            "BAAI/bge-large-en-v1.5":  1024,
            "BAAI/bge-small-en-v1.5":  384,
            "all-MiniLM-L6-v2":        384,
            "all-mpnet-base-v2":       768,
        }
        return _DIM_MAP.get(self._model_name, 768)

    @property
    def model_name(self) -> str:
        return f"sentence-transformers/{self._model_name}"

    def _load_model(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
            logger.info("loading sentence-transformers model", extra={
                "model": self._model_name, "device": self._device
            })
            self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._load_model()
            vectors = model.encode(  # type: ignore[attr-defined]
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return vectors.tolist()

        # Run in thread pool – sentence-transformers is CPU/GPU bound
        return await run_in_executor(_encode)
