#!/usr/bin/env python3
"""
LCM ↔ LACP Cross-Reference Linker

Bridges LCM session summaries to LACP's persistent knowledge graph.

Features:
- Extract facts from LCM summaries
- Find related LACP notes via keyword matching
- Create bidirectional wikilinks (LCM → LACP, LACP → LCM)
- Verify link integrity with cryptographic hashes
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class LCMLACPLinker:
    """Create and manage cross-references between LCM summaries and LACP notes."""

    def __init__(self, vault_path: Optional[str] = None, log_path: Optional[str] = None):
        self.vault_path = Path(vault_path) if vault_path else self._default_vault_path()
        self.log_path = Path(log_path) if log_path else self._default_log_path()
        self._links = []

    def _default_vault_path(self) -> Path:
        return Path.home() / ".openclaw" / "vault"

    def _default_log_path(self) -> Path:
        return Path.home() / ".openclaw" / "logs" / "linker.jsonl"

    def extract_topics(self, summary: dict) -> list:
        """Extract key topics from an LCM summary for matching."""
        content = summary.get("content", "")
        topics = []

        # Extract explicit tags
        tags = re.findall(r"#(\w[\w-]*)", content)
        topics.extend(tags)

        # Extract wikilink references
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        topics.extend(wikilinks)

        # Extract capitalized terms (likely proper nouns / system names)
        proper_nouns = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", content)
        # Filter out common sentence starters
        stopwords = {"The", "This", "That", "These", "Those", "When", "Where",
                      "What", "Which", "How", "Why", "For", "With", "From",
                      "Into", "After", "Before", "During", "Between", "About"}
        proper_nouns = [p for p in proper_nouns if p not in stopwords]
        topics.extend(proper_nouns)

        # Extract technical terms (snake_case, kebab-case, camelCase)
        technical = re.findall(r"\b([a-z]+[-_][a-z][-\w]*)\b", content)
        topics.extend(technical)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for t in topics:
            normalized = t.lower().strip()
            if normalized not in seen and len(normalized) > 2:
                seen.add(normalized)
                unique.append(t)

        return unique[:30]

    def find_related_notes(self, topics: list, max_results: int = 10) -> list:
        """Find LACP vault notes related to the given topics."""
        if not self.vault_path.exists():
            return []

        related = []
        md_files = list(self.vault_path.rglob("*.md"))

        for md_file in md_files:
            rel_path = md_file.relative_to(self.vault_path)
            filename = md_file.stem.lower()

            # Score by topic match in filename
            score = 0
            matched_topics = []
            for topic in topics:
                topic_lower = topic.lower()
                if topic_lower in filename:
                    score += 3
                    matched_topics.append(topic)
                elif topic_lower.replace("-", " ") in filename.replace("-", " "):
                    score += 2
                    matched_topics.append(topic)

            # Score by topic match in content (only if filename matched something)
            if score > 0 or len(topics) > 0:
                try:
                    content = md_file.read_text(encoding="utf-8", errors="replace")
                    content_lower = content.lower()
                    for topic in topics:
                        topic_lower = topic.lower()
                        if topic_lower in content_lower:
                            if topic not in matched_topics:
                                score += 1
                                matched_topics.append(topic)
                except (OSError, UnicodeDecodeError):
                    continue

            if score > 0:
                related.append({
                    "path": str(rel_path),
                    "title": md_file.stem,
                    "score": score,
                    "matched_topics": matched_topics,
                })

        # Sort by score descending
        related.sort(key=lambda x: x["score"], reverse=True)
        return related[:max_results]

    def create_cross_references(
        self,
        summary: dict,
        related_notes: list,
        facts: Optional[list] = None,
    ) -> list:
        """
        Create bidirectional cross-references.

        Returns list of CrossReference dicts with hashes for verification.
        """
        summary_id = summary.get("summary_id", "unknown")
        timestamp = datetime.now(timezone.utc).isoformat()
        refs = []

        for note in related_notes:
            ref = {
                "summary_id": summary_id,
                "note_path": note["path"],
                "note_title": note["title"],
                "direction": "bidirectional",
                "matched_topics": note["matched_topics"],
                "confidence": min(note["score"] / 5.0, 1.0),
                "created_at": timestamp,
                "facts": facts or [],
            }

            # Generate verification hash
            payload = json.dumps(
                {"summary_id": summary_id, "note_path": note["path"], "timestamp": timestamp},
                sort_keys=True,
            )
            ref["link_hash"] = hashlib.sha256(payload.encode()).hexdigest()

            refs.append(ref)

        self._links.extend(refs)
        return refs

    def write_lcm_to_lacp_link(self, note_path: str, summary_id: str, link_hash: str) -> bool:
        """Append a reference from LACP note back to LCM summary."""
        full_path = self.vault_path / note_path
        if not full_path.exists():
            return False

        link_block = (
            f"\n\n---\n"
            f"**LCM Reference:** `{summary_id}` | "
            f"Hash: `{link_hash[:12]}...` | "
            f"Linked: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        )

        try:
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(link_block)
            return True
        except OSError:
            return False

    def generate_summary_note(self, summary: dict, refs: list) -> str:
        """Generate an Obsidian-format note for the LCM summary with cross-references."""
        summary_id = summary.get("summary_id", "unknown")
        content = summary.get("content", "")
        project = summary.get("project", "unknown")
        timestamp = summary.get("timestamp", datetime.now(timezone.utc).isoformat())

        lines = [
            f"# LCM Summary: {summary_id}",
            f"",
            f"**Project:** {project}",
            f"**Timestamp:** {timestamp}",
            f"**Source:** LCM session summary",
            f"",
            f"## Content",
            f"",
            content,
            f"",
            f"## Cross-References",
            f"",
        ]

        for ref in refs:
            title = ref["note_title"]
            conf = ref["confidence"]
            topics = ", ".join(ref["matched_topics"][:5])
            lines.append(f"- [[{title}]] (confidence: {conf:.1f}, topics: {topics})")

        lines.append("")
        lines.append("---")
        lines.append(f"*Auto-linked by openclaw-lacp-promote v2.1.0*")

        return "\n".join(lines)

    def verify_link(self, ref: dict) -> bool:
        """Verify a cross-reference's integrity via its hash."""
        expected_payload = json.dumps(
            {
                "summary_id": ref["summary_id"],
                "note_path": ref["note_path"],
                "timestamp": ref["created_at"],
            },
            sort_keys=True,
        )
        expected_hash = hashlib.sha256(expected_payload.encode()).hexdigest()
        return ref.get("link_hash") == expected_hash

    def log_links(self, refs: list) -> bool:
        """Append cross-reference records to the linker log."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                for ref in refs:
                    f.write(json.dumps(ref, default=str) + "\n")
            return True
        except OSError:
            return False

    def get_links(self) -> list:
        """Return all links created in this session."""
        return list(self._links)


    def get_backend_summary_sources(self, backend=None) -> dict:
        """Report which backend is providing summaries.

        Args:
            backend: Optional ContextBackend instance. If provided, includes
                     backend-specific info.

        Returns:
            Dict with backend info including type, vault_path, and availability.
        """
        info = {
            "backend": backend.backend_name() if backend else "file",
            "vault_path": str(self.vault_path),
            "vault_exists": self.vault_path.exists(),
            "log_path": str(self.log_path),
        }
        if backend:
            info["backend_available"] = backend.is_available()
        return info

    def find_context_via_backend(self, backend, task: str, project: Optional[str] = None, limit: int = 10) -> list:
        """Find relevant context using a ContextBackend instead of file search.

        Args:
            backend: A ContextBackend instance (LCMBackend or FileBackend).
            task: Natural language task description.
            project: Optional project filter.
            limit: Maximum results.

        Returns:
            List of context result dicts from the backend.
        """
        return backend.find_context(task=task, project=project, limit=limit)


def link_summary_to_vault(
    summary: dict,
    vault_path: Optional[str] = None,
    log_path: Optional[str] = None,
) -> dict:
    """
    Convenience function: extract topics, find related notes, create cross-references.

    Returns dict with topics, related_notes, cross_references, and summary_note.
    """
    linker = LCMLACPLinker(vault_path=vault_path, log_path=log_path)

    topics = linker.extract_topics(summary)
    related = linker.find_related_notes(topics)
    refs = linker.create_cross_references(summary, related)
    note = linker.generate_summary_note(summary, refs)
    linker.log_links(refs)

    return {
        "topics": topics,
        "related_notes": related,
        "cross_references": refs,
        "summary_note": note,
        "link_count": len(refs),
    }
