"""
File Backend — File-based context engine (default fallback).

Reads from --file paths, vault file search, and manual input.
This is the original v2.0.0 approach, extracted into the backend interface.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backends import ContextBackend


class FileBackend(ContextBackend):
    """Context backend that reads from local files and vault directories.

    This is the default backend when contextEngine is null or unset.
    It searches LACP vault directories, memory files, and manually-provided
    file paths for context.
    """

    def __init__(self, config: dict):
        """Initialize with config dict.

        Args:
            config: Dict with optional keys:
                - vaultPath: path to vault directory
                - memoryRoot: path to memory root
                - promotionThreshold: int (default: 70)
                - files: list of explicit file paths to include
        """
        self._vault_path = Path(
            config.get("vaultPath", os.path.expanduser("~/.openclaw/vault"))
        )
        self._memory_root = Path(
            config.get("memoryRoot", os.path.expanduser("~/.openclaw/memory"))
        )
        self._threshold = config.get("promotionThreshold", 70)
        self._files = config.get("files", [])

    def backend_name(self) -> str:
        """Return backend identifier."""
        return "file"

    def is_available(self) -> bool:
        """File backend is always available."""
        return True

    def fetch_summary(self, summary_id: str) -> dict:
        """Fetch a summary by searching files for matching ID.

        Args:
            summary_id: The summary identifier to search for.

        Returns:
            Summary dict or empty dict if not found.
        """
        # Search in explicit files first
        for file_path in self._files:
            result = self._search_file_for_summary(file_path, summary_id)
            if result:
                return result

        # Search in memory root
        if self._memory_root.exists():
            for md_file in self._memory_root.rglob("*.md"):
                result = self._search_file_for_summary(str(md_file), summary_id)
                if result:
                    return result

            for json_file in self._memory_root.rglob("*.json"):
                result = self._search_json_for_summary(str(json_file), summary_id)
                if result:
                    return result

        # Search vault
        if self._vault_path.exists():
            for md_file in self._vault_path.rglob("*.md"):
                result = self._search_file_for_summary(str(md_file), summary_id)
                if result:
                    return result

        return {}

    def discover_summaries(self, filters: dict) -> list:
        """Discover summaries from files matching filters.

        Args:
            filters: Dict with optional keys: since, until, project, limit.

        Returns:
            List of summary dicts.
        """
        summaries = []
        limit = filters.get("limit", 50)
        project_filter = filters.get("project")
        since = filters.get("since")
        until = filters.get("until")

        # Scan memory root
        search_dirs = []
        if project_filter and self._memory_root.exists():
            project_dir = self._memory_root / project_filter.lower().replace(" ", "-")
            if project_dir.exists():
                search_dirs.append(project_dir)
        elif self._memory_root.exists():
            search_dirs.append(self._memory_root)

        # Also scan vault
        if self._vault_path.exists():
            search_dirs.append(self._vault_path)

        # Also include explicit files
        for file_path in self._files:
            p = Path(file_path)
            if p.exists() and p.suffix == ".json":
                data = self._load_json_file(file_path)
                if data:
                    summaries.append(data)

        for search_dir in search_dirs:
            for json_file in search_dir.rglob("*.json"):
                data = self._load_json_file(str(json_file))
                if data and "content" in data:
                    # Apply date filters
                    ts = data.get("timestamp", "")
                    if since and ts and ts < since:
                        continue
                    if until and ts and ts > until:
                        continue
                    summaries.append(data)

            for md_file in search_dir.rglob("*.md"):
                data = self._parse_md_as_summary(str(md_file))
                if data:
                    ts = data.get("timestamp", "")
                    if since and ts and ts < since:
                        continue
                    if until and ts and ts > until:
                        continue
                    summaries.append(data)

        # Sort by timestamp descending
        summaries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Deduplicate by summary_id
        seen = set()
        unique = []
        for s in summaries:
            sid = s.get("summary_id", id(s))
            if sid not in seen:
                seen.add(sid)
                unique.append(s)

        return unique[:limit]

    def find_context(self, task: str, project: Optional[str] = None, limit: int = 10) -> list:
        """Find context relevant to a task using keyword search over files.

        Args:
            task: Natural language task description.
            project: Optional project filter.
            limit: Maximum results.

        Returns:
            List of scored context dicts.
        """
        keywords = self._extract_keywords(task)
        if not keywords:
            return []

        results = []

        # Search in memory root
        search_dirs = []
        if project and self._memory_root.exists():
            project_dir = self._memory_root / project.lower().replace(" ", "-")
            if project_dir.exists():
                search_dirs.append(project_dir)
            else:
                search_dirs.append(self._memory_root)
        elif self._memory_root.exists():
            search_dirs.append(self._memory_root)

        if self._vault_path.exists():
            search_dirs.append(self._vault_path)

        for search_dir in search_dirs:
            for md_file in search_dir.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8", errors="replace")
                    content_lower = content.lower()
                    score = sum(1 for kw in keywords if kw in content_lower)
                    if score > 0:
                        results.append({
                            "summary_id": md_file.stem,
                            "content": content[:2000],
                            "relevance_score": round(score / len(keywords) * 100, 1),
                            "source": "file",
                            "project": project or "",
                            "file_path": str(md_file),
                        })
                except (OSError, UnicodeDecodeError):
                    continue

        # Also search explicit files
        for file_path in self._files:
            p = Path(file_path)
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    content_lower = content.lower()
                    score = sum(1 for kw in keywords if kw in content_lower)
                    if score > 0:
                        results.append({
                            "summary_id": p.stem,
                            "content": content[:2000],
                            "relevance_score": round(score / len(keywords) * 100, 1),
                            "source": "file",
                            "project": project or "",
                            "file_path": str(p),
                        })
                except (OSError, UnicodeDecodeError):
                    continue

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:limit]

    def traverse_dag(self, summary_id: str, depth: int = 3) -> dict:
        """File backend does not support DAG traversal.

        Returns a single-node chain if the summary is found.
        """
        summary = self.fetch_summary(summary_id)
        if summary:
            return {
                "root": summary,
                "chain": [summary],
                "depth_reached": 1,
            }
        return {
            "root": {},
            "chain": [],
            "depth_reached": 0,
        }

    def _search_file_for_summary(self, file_path: str, summary_id: str) -> dict:
        """Search a markdown file for a summary ID reference."""
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            if summary_id in content:
                return {
                    "summary_id": summary_id,
                    "content": content[:2000],
                    "source": "file",
                    "file_path": file_path,
                    "timestamp": "",
                }
        except (OSError, UnicodeDecodeError):
            pass
        return {}

    def _search_json_for_summary(self, file_path: str, summary_id: str) -> dict:
        """Search a JSON file for a summary ID."""
        data = self._load_json_file(file_path)
        if data and data.get("summary_id") == summary_id:
            return data
        return {}

    def _load_json_file(self, file_path: str) -> dict:
        """Load and parse a JSON file, returning empty dict on failure."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
        return {}

    def _parse_md_as_summary(self, file_path: str) -> dict:
        """Parse a markdown file into a summary-like dict."""
        try:
            p = Path(file_path)
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content.strip()) < 10:
                return {}
            return {
                "summary_id": p.stem,
                "content": content[:2000],
                "source": "file",
                "file_path": file_path,
                "timestamp": datetime.fromtimestamp(
                    p.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        except (OSError, UnicodeDecodeError):
            return {}

    def _extract_keywords(self, text: str) -> list:
        """Extract meaningful keywords from text for search."""
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "out", "off", "over",
            "under", "again", "further", "then", "once", "here", "there", "when",
            "where", "why", "how", "all", "each", "every", "both", "few", "more",
            "most", "other", "some", "such", "no", "nor", "not", "only", "own",
            "same", "so", "than", "too", "very", "just", "because", "but", "and",
            "or", "if", "while", "about", "up", "it", "its", "this", "that",
            "these", "those", "what", "which", "who", "whom", "i", "me", "my",
            "we", "our", "you", "your", "he", "him", "his", "she", "her", "they",
            "them", "their",
        }
        words = re.findall(r"[a-zA-Z][\w-]*", text.lower())
        return [w for w in words if w not in stopwords and len(w) > 2]
