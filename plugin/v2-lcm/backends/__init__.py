"""
Context Backend Abstraction — Config-driven context engine selection.

Provides a unified interface for fetching context from either:
  - lossless-claw native (LCMBackend): reads from ~/.openclaw/lcm.db SQLite DAG
  - file-based fallback (FileBackend): reads from --file paths, vault search

Usage:
    from backends import get_backend
    backend = get_backend(config)
    summaries = backend.discover_summaries(filters)
    context = backend.find_context(task="deploy treasury flow")
"""

from abc import ABC, abstractmethod
from typing import Optional


class ContextBackend(ABC):
    """Abstract interface for context retrieval backends.

    All backends must implement these methods to ensure Liskov substitution.
    The promotion scorer, linker, and CLI commands operate against this interface.
    """

    @abstractmethod
    def fetch_summary(self, summary_id: str) -> dict:
        """Fetch a single summary by ID.

        Args:
            summary_id: Unique identifier for the summary.

        Returns:
            Dict with keys: summary_id, content, source, citations, project,
            agent, timestamp. Returns empty dict if not found.
        """

    @abstractmethod
    def discover_summaries(self, filters: dict) -> list:
        """Discover summaries matching the given filters.

        Args:
            filters: Dict with optional keys:
                - since: ISO date string (e.g., "2026-03-18")
                - until: ISO date string
                - conversation_id: str
                - project: str
                - limit: int (default 50)

        Returns:
            List of summary dicts, sorted by timestamp descending.
        """

    @abstractmethod
    def find_context(self, task: str, project: Optional[str] = None, limit: int = 10) -> list:
        """Find summaries relevant to a task description.

        Args:
            task: Natural language description of the task.
            project: Optional project filter.
            limit: Maximum results to return.

        Returns:
            List of dicts with keys: summary_id, content, relevance_score, source.
        """

    @abstractmethod
    def traverse_dag(self, summary_id: str, depth: int = 3) -> dict:
        """Walk the parent chain of a summary in the DAG.

        Args:
            summary_id: Starting summary ID.
            depth: Maximum depth to traverse.

        Returns:
            Dict with keys: root, chain (list of summary dicts), depth_reached.
        """

    @abstractmethod
    def backend_name(self) -> str:
        """Return the name of this backend ('lossless-claw' or 'file')."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether this backend is operational (DB exists, files readable, etc.)."""


def get_backend(config: dict) -> ContextBackend:
    """Factory: return the appropriate backend based on config.

    Args:
        config: Dict with at least 'contextEngine' key.
            - contextEngine: "lossless-claw" | None

    Returns:
        ContextBackend instance.

    Raises:
        ValueError: If the requested backend is not available.
    """
    engine = config.get("contextEngine")

    if engine == "lossless-claw":
        from backends.lcm_backend import LCMBackend
        backend = LCMBackend(config)
        if not backend.is_available():
            raise ValueError(
                "lossless-claw backend requested but LCM database not found. "
                "Expected at: ~/.openclaw/lcm.db. "
                "Set contextEngine to null in your config to use file-based fallback."
            )
        return backend
    else:
        from backends.file_backend import FileBackend
        return FileBackend(config)
