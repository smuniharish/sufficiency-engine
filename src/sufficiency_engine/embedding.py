"""Optional embedding extension point; no embedding implementation is required."""

from abc import ABC, abstractmethod


class EmbeddingModelABC(ABC):
    """Application-owned embedding model for conservative duplicate detection."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one finite, nonzero vector per text."""
