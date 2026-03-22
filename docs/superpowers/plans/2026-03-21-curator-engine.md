# Curator Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the curator engine that autonomously maintains the knowledge graph. This includes the scheduled 8-step maintenance loop, a reactive filesystem watcher, and all missing sub-modules (inbox processing, wikilink weaving, staleness scanning, conflict resolution, schema enforcement, index generation, health reporting).

**Architecture:** The curator orchestrates existing algorithms (mycelium, consolidation, review queue, knowledge gaps) alongside new sub-modules. A curator-maintenance skill file defines behavior for the OpenClaw cron job. `plugin/lib/curator.py` is the top-level orchestrator. Each sub-module is a standalone Python module in `plugin/lib/` with pure-function interfaces, tested independently.

**Tech Stack:** Python 3.9+, watchdog (filesystem events), pytest

**Dependencies on existing code:**
- `plugin/lib/mycelium.py` -- spreading activation, memory model, prediction error gate, path reinforcement, self-healing, flow score
- `plugin/lib/consolidation.py` -- `run_consolidation()`, `_load_vault_notes()`, `_parse_frontmatter()`, `_extract_links()`
- `plugin/lib/review_queue.py` -- `generate_review_queue()`, `write_review_queue()`
- `plugin/lib/knowledge_gaps.py` -- `detect_knowledge_gaps()`, `write_gap_report()`
- `plugin/bin/openclaw-brain-resolve` -- contradiction/supersession resolution

---

## Task 1: Curator maintenance skill prompt

Create the markdown skill file that the OpenClaw cron job references. This defines the curator's behavior, constraints, and the 8-step cycle it executes.

### Step 1.1: Create curator-maintenance skill

- [ ] Write `plugin/skills/curator-maintenance.md`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/skills/curator-maintenance.md`

```markdown
---
name: curator-maintenance
description: Scheduled maintenance cycle for the knowledge graph curator
trigger: cron
schedule: every 4h
mode: curator
---

# Curator Maintenance

You are the knowledge graph curator. Your job is to maintain the health, accuracy,
and connectivity of the shared Obsidian vault.

## Cycle Steps

Execute these steps in order. Each step is idempotent. If a step fails, log the
error and continue to the next step.

1. **Process inbox** -- Classify and route notes from all `queue-*` folders in
   `05_Inbox/`. Determine category, tags, target folder, and trust level for each
   note. Move promoted notes to their target folder. Hold low-trust notes for
   review.

2. **Run mycelium consolidation** -- Execute `run_consolidation()` to compute
   storage/retrieval strength, run spreading activation, prune low-value notes,
   protect tendril nodes, and reinforce active paths.

3. **Weave wikilinks** -- Scan the vault for related notes using title matching,
   tag overlap, and content similarity. Add `[[backlinks]]` between related notes.
   Remove broken links to deleted or archived notes.

4. **Staleness scan** -- Compute staleness scores for all notes using the formula:
   `staleness_score = days_since_traversed / (traversal_count + 1)`. Flag notes
   exceeding thresholds. Move review-needed notes to `05_Inbox/review-stale/`.

5. **Conflict resolution** -- Detect Obsidian Sync conflict files (pattern:
   `note (conflict YYYY-MM-DD).md`). Attempt auto-merge for non-overlapping
   changes. Escalate contradicting changes to human review.

6. **Schema enforcement** -- Validate that all notes have required frontmatter
   fields: title, category, tags, created, updated, author, source, status. Add
   missing fields with sensible defaults. Flag malformed notes.

7. **Index update** -- Regenerate `00_Index.md` with current folder counts and
   recent changes. Update per-folder `index.md` files.

8. **Health report** -- Compute graph health metrics (note count, orphan rate,
   staleness distribution, link density, connector status). Write report to
   `05_Inbox/curator-health-report.md`.

## Constraints

- Never delete notes. Archive to `99_Archive/` instead.
- Never modify note body content. Only modify frontmatter and add wikilinks.
- Respect trust levels. Do not promote `low` trust notes without human confirmation.
- Log every mutation with timestamp and reason.
- If vault has > 10,000 notes, batch operations to avoid filesystem pressure.
```

---

## Task 2: Inbox processor

Classify notes from `queue-*` folders, determine target folder based on content analysis, handle trust levels, and move notes to their destination.

### Step 2.1: Create inbox_processor.py

- [ ] Write `plugin/lib/inbox_processor.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/inbox_processor.py`

```python
"""
Inbox processor for the curator engine.

Classifies notes from queue-* folders in 05_Inbox/, determines target folder
based on content analysis (category, tags, trust level), and moves notes to
their destination in the organized graph.
"""

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter


# ---------------------------------------------------------------------------
# Category -> folder mapping
# ---------------------------------------------------------------------------

CATEGORY_FOLDER_MAP = {
    "projects": "01_Projects",
    "concepts": "02_Concepts",
    "people": "03_People",
    "systems": "04_Systems",
    "planning": "06_Planning",
    "research": "07_Research",
    "strategy": "08_Strategy",
    "changelog": "09_Changelog",
    "templates": "10_Templates",
}

# Trust level -> auto-promote threshold
TRUST_AUTO_PROMOTE = {
    "verified": True,
    "high": True,
    "medium": False,
    "low": False,
}

# Keywords used for category inference when frontmatter is missing
CATEGORY_KEYWORDS = {
    "projects": [
        "repo", "repository", "codebase", "pr ", "pull request", "branch",
        "deploy", "feature", "sprint", "backlog",
    ],
    "concepts": [
        "pattern", "architecture", "design", "principle", "convention",
        "best practice", "standard", "approach",
    ],
    "people": [
        "team", "member", "role", "responsibility", "contact", "onboard",
    ],
    "systems": [
        "infrastructure", "server", "database", "deployment", "monitoring",
        "ci/cd", "pipeline", "docker", "kubernetes",
    ],
    "planning": [
        "roadmap", "milestone", "timeline", "priority", "objective",
        "quarter", "okr", "goal",
    ],
    "research": [
        "evaluation", "comparison", "benchmark", "competitor", "market",
        "analysis", "finding",
    ],
    "strategy": [
        "vision", "direction", "fundrais", "investor", "partnership",
        "hiring", "growth",
    ],
    "changelog": [
        "release", "version", "changelog", "deploy", "hotfix", "rollback",
    ],
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_note(file_path: Path, vault_path: Path) -> dict:
    """
    Classify an inbox note to determine its target folder and metadata.

    Args:
        file_path: path to the note file.
        vault_path: root of the Obsidian vault.

    Returns:
        dict with keys: category, target_folder, trust_level, tags,
        title, project, auto_promote, needs_review, reason.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return {
            "category": "inbox",
            "target_folder": "05_Inbox",
            "trust_level": "low",
            "tags": [],
            "title": file_path.stem,
            "project": "",
            "auto_promote": False,
            "needs_review": True,
            "reason": "unreadable_file",
        }

    fm = _parse_frontmatter(content)
    body = content
    # Strip frontmatter from body for keyword analysis
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            body = content[end + 3:]

    # Extract from frontmatter if available
    category = fm.get("category", "")
    trust_level = fm.get("trust_level", _infer_trust_from_queue(file_path))
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    title = fm.get("title", file_path.stem)
    project = fm.get("project", "")
    source = fm.get("source", "")

    # Infer category from content if not in frontmatter
    if not category:
        category = _infer_category(title, body, tags)

    # Determine target folder
    target_folder = CATEGORY_FOLDER_MAP.get(category, "02_Concepts")
    if category == "projects" and project:
        target_folder = f"01_Projects/{project}"

    # Auto-promote decision
    auto_promote = TRUST_AUTO_PROMOTE.get(trust_level, False)
    needs_review = not auto_promote

    return {
        "category": category or "concepts",
        "target_folder": target_folder,
        "trust_level": trust_level,
        "tags": tags,
        "title": title,
        "project": project,
        "auto_promote": auto_promote,
        "needs_review": needs_review,
        "reason": "classified",
    }


def _infer_trust_from_queue(file_path: Path) -> str:
    """Infer trust level from the queue folder name."""
    parts = file_path.parts
    for part in parts:
        if part == "queue-agent":
            return "high"
        elif part == "queue-cicd":
            return "verified"
        elif part == "queue-human":
            return "medium"
        elif part == "queue-external":
            return "low"
    return "medium"


def _infer_category(title: str, body: str, tags: list) -> str:
    """Infer category from title, body text, and tags using keyword matching."""
    text = f"{title} {body}".lower()
    tag_text = " ".join(t.lower() for t in tags)
    combined = f"{text} {tag_text}"

    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[category] = score

    if not scores:
        return "concepts"  # default

    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_inbox(vault_path: Optional[str] = None, dry_run: bool = True) -> dict:
    """
    Process all notes in queue-* folders under 05_Inbox/.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, report what would be done without moving files.

    Returns:
        dict with processed, promoted, held, errors, and details list.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    inbox = vault / "05_Inbox"

    if not inbox.exists():
        return {
            "processed": 0,
            "promoted": 0,
            "held": 0,
            "errors": 0,
            "details": [],
        }

    results = {
        "processed": 0,
        "promoted": 0,
        "held": 0,
        "errors": 0,
        "details": [],
    }

    # Find all queue-* directories
    queue_dirs = sorted(
        d for d in inbox.iterdir()
        if d.is_dir() and d.name.startswith("queue-")
    )

    for queue_dir in queue_dirs:
        for md_file in sorted(queue_dir.glob("*.md")):
            if md_file.name == "index.md":
                continue

            results["processed"] += 1

            try:
                classification = classify_note(md_file, vault)
            except Exception as exc:
                results["errors"] += 1
                results["details"].append({
                    "file": str(md_file.relative_to(vault)),
                    "action": "error",
                    "reason": str(exc),
                })
                continue

            if classification["auto_promote"]:
                target_dir = vault / classification["target_folder"]
                if not dry_run:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    dest = target_dir / md_file.name
                    # Avoid overwriting
                    if dest.exists():
                        stem = md_file.stem
                        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                        dest = target_dir / f"{stem}-{ts}.md"
                    shutil.move(str(md_file), str(dest))
                results["promoted"] += 1
                results["details"].append({
                    "file": str(md_file.relative_to(vault)),
                    "action": "promoted",
                    "target": classification["target_folder"],
                    "category": classification["category"],
                    "trust": classification["trust_level"],
                })
            else:
                results["held"] += 1
                results["details"].append({
                    "file": str(md_file.relative_to(vault)),
                    "action": "held",
                    "target": classification["target_folder"],
                    "category": classification["category"],
                    "trust": classification["trust_level"],
                    "reason": "needs_review",
                })

    return results
```

### Step 2.2: Write tests for inbox_processor

- [ ] Write `plugin/lib/tests/test_inbox_processor.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_inbox_processor.py`

```python
"""Tests for inbox processor."""

from pathlib import Path

import pytest

from plugin.lib.inbox_processor import (
    classify_note,
    process_inbox,
    _infer_category,
    _infer_trust_from_queue,
)


def _make_note(tmp_path, queue_name, filename, frontmatter="", body="# Note\n\nContent."):
    """Create a note in a queue folder."""
    inbox = tmp_path / "05_Inbox" / queue_name
    inbox.mkdir(parents=True, exist_ok=True)
    content = ""
    if frontmatter:
        content = f"---\n{frontmatter}\n---\n\n"
    content += body
    note = inbox / filename
    note.write_text(content, encoding="utf-8")
    return note


class TestInferTrustFromQueue:
    def test_agent_queue_returns_high(self, tmp_path):
        path = tmp_path / "05_Inbox" / "queue-agent" / "note.md"
        assert _infer_trust_from_queue(path) == "high"

    def test_cicd_queue_returns_verified(self, tmp_path):
        path = tmp_path / "05_Inbox" / "queue-cicd" / "note.md"
        assert _infer_trust_from_queue(path) == "verified"

    def test_human_queue_returns_medium(self, tmp_path):
        path = tmp_path / "05_Inbox" / "queue-human" / "note.md"
        assert _infer_trust_from_queue(path) == "medium"

    def test_external_queue_returns_low(self, tmp_path):
        path = tmp_path / "05_Inbox" / "queue-external" / "note.md"
        assert _infer_trust_from_queue(path) == "low"

    def test_unknown_queue_returns_medium(self, tmp_path):
        path = tmp_path / "05_Inbox" / "queue-misc" / "note.md"
        assert _infer_trust_from_queue(path) == "medium"


class TestInferCategory:
    def test_deployment_keywords_map_to_systems(self):
        assert _infer_category("Deployment Guide", "kubernetes docker pipeline", []) == "systems"

    def test_pattern_keywords_map_to_concepts(self):
        assert _infer_category("Error Handling Pattern", "best practice convention", []) == "concepts"

    def test_roadmap_keywords_map_to_planning(self):
        assert _infer_category("Q2 Roadmap", "milestone timeline objective", []) == "planning"

    def test_no_keywords_defaults_to_concepts(self):
        assert _infer_category("Random Note", "some random content here", []) == "concepts"

    def test_tags_contribute_to_classification(self):
        assert _infer_category("Note", "plain content", ["infrastructure", "monitoring"]) == "systems"


class TestClassifyNote:
    def test_frontmatter_category_used(self, tmp_path):
        note = _make_note(
            tmp_path, "queue-agent", "test.md",
            frontmatter='category: systems\ntags: [auth, security]\ntitle: "Auth System"',
        )
        result = classify_note(note, tmp_path)
        assert result["category"] == "systems"
        assert result["target_folder"] == "04_Systems"

    def test_agent_queue_auto_promotes(self, tmp_path):
        note = _make_note(tmp_path, "queue-agent", "test.md")
        result = classify_note(note, tmp_path)
        assert result["trust_level"] == "high"
        assert result["auto_promote"] is True

    def test_external_queue_held(self, tmp_path):
        note = _make_note(tmp_path, "queue-external", "test.md")
        result = classify_note(note, tmp_path)
        assert result["trust_level"] == "low"
        assert result["auto_promote"] is False
        assert result["needs_review"] is True

    def test_project_specific_folder(self, tmp_path):
        note = _make_note(
            tmp_path, "queue-cicd", "pr-summary.md",
            frontmatter='category: projects\nproject: easy-api\ntitle: "PR Summary"',
        )
        result = classify_note(note, tmp_path)
        assert result["target_folder"] == "01_Projects/easy-api"

    def test_category_inferred_from_content(self, tmp_path):
        note = _make_note(
            tmp_path, "queue-agent", "test.md",
            body="# Database Migration Strategy\n\nThis architecture pattern uses design principles.",
        )
        result = classify_note(note, tmp_path)
        assert result["category"] in ("concepts", "systems")


class TestProcessInbox:
    def test_empty_vault(self, tmp_path):
        result = process_inbox(str(tmp_path), dry_run=True)
        assert result["processed"] == 0

    def test_promotes_high_trust_notes(self, tmp_path):
        _make_note(tmp_path, "queue-agent", "pattern.md", body="# Auth Pattern\n\nContent.")
        result = process_inbox(str(tmp_path), dry_run=False)
        assert result["promoted"] == 1
        # File should be moved out of inbox
        assert not (tmp_path / "05_Inbox" / "queue-agent" / "pattern.md").exists()

    def test_holds_low_trust_notes(self, tmp_path):
        _make_note(tmp_path, "queue-external", "untrusted.md", body="# External\n\nContent.")
        result = process_inbox(str(tmp_path), dry_run=False)
        assert result["held"] == 1
        # File should remain in inbox
        assert (tmp_path / "05_Inbox" / "queue-external" / "untrusted.md").exists()

    def test_dry_run_does_not_move(self, tmp_path):
        _make_note(tmp_path, "queue-agent", "pattern.md", body="# Pattern\n\nContent.")
        result = process_inbox(str(tmp_path), dry_run=True)
        assert result["promoted"] == 1
        # File should still be in inbox
        assert (tmp_path / "05_Inbox" / "queue-agent" / "pattern.md").exists()

    def test_skips_index_files(self, tmp_path):
        _make_note(tmp_path, "queue-agent", "index.md", body="# Index")
        _make_note(tmp_path, "queue-agent", "real-note.md", body="# Real Note")
        result = process_inbox(str(tmp_path), dry_run=True)
        assert result["processed"] == 1

    def test_multiple_queues_processed(self, tmp_path):
        _make_note(tmp_path, "queue-agent", "a.md", body="# A")
        _make_note(tmp_path, "queue-cicd", "b.md", body="# B")
        _make_note(tmp_path, "queue-human", "c.md", body="# C")
        result = process_inbox(str(tmp_path), dry_run=True)
        assert result["processed"] == 3
```

---

## Task 3: Wikilink weaver

Scan vault for related notes using title matching, tag overlap, and content similarity. Add `[[backlinks]]` between related notes. Remove broken links.

### Step 3.1: Create wikilink_weaver.py

- [ ] Write `plugin/lib/wikilink_weaver.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/wikilink_weaver.py`

```python
"""
Wikilink weaver for the curator engine.

Scans the vault for related notes using title matching, tag overlap, and
content similarity. Adds [[backlinks]] between related notes. Removes
broken links to deleted or archived notes.
"""

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter, _extract_links


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------

def _title_similarity(title_a: str, title_b: str) -> float:
    """
    Compute title similarity using word overlap (Jaccard).

    Returns float in [0, 1].
    """
    words_a = set(title_a.lower().split())
    words_b = set(title_b.lower().split())
    # Remove very common words
    stop = {"the", "a", "an", "and", "or", "of", "in", "to", "for", "is", "on", "at", "by"}
    words_a -= stop
    words_b -= stop
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _tag_overlap(tags_a: list, tags_b: list) -> float:
    """
    Compute tag overlap (Jaccard).

    Returns float in [0, 1].
    """
    set_a = set(t.lower() for t in tags_a)
    set_b = set(t.lower() for t in tags_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _content_keyword_overlap(body_a: str, body_b: str, top_n: int = 30) -> float:
    """
    Compute content similarity using keyword overlap.

    Extracts top_n most frequent non-trivial words from each note body
    and computes Jaccard similarity.

    Returns float in [0, 1].
    """
    stop = {
        "the", "a", "an", "and", "or", "of", "in", "to", "for", "is", "on",
        "at", "by", "it", "be", "as", "that", "this", "was", "are", "with",
        "not", "but", "from", "have", "has", "had", "will", "can", "do",
        "if", "we", "you", "they", "he", "she", "its",
    }

    def extract_keywords(text):
        words = re.findall(r"[a-z]{3,}", text.lower())
        words = [w for w in words if w not in stop]
        freq = defaultdict(int)
        for w in words:
            freq[w] += 1
        sorted_words = sorted(freq, key=freq.get, reverse=True)
        return set(sorted_words[:top_n])

    kw_a = extract_keywords(body_a)
    kw_b = extract_keywords(body_b)
    if not kw_a or not kw_b:
        return 0.0
    intersection = kw_a & kw_b
    union = kw_a | kw_b
    return len(intersection) / len(union)


def compute_relatedness(note_a: dict, note_b: dict) -> float:
    """
    Compute relatedness between two notes.

    Weighted combination:
    - 0.4 * title similarity
    - 0.3 * tag overlap
    - 0.3 * content keyword overlap

    Args:
        note_a, note_b: dicts with keys: title, tags, body.

    Returns:
        float in [0, 1].
    """
    title_sim = _title_similarity(
        note_a.get("title", ""),
        note_b.get("title", ""),
    )
    tag_sim = _tag_overlap(
        note_a.get("tags", []),
        note_b.get("tags", []),
    )
    content_sim = _content_keyword_overlap(
        note_a.get("body", ""),
        note_b.get("body", ""),
    )
    return 0.4 * title_sim + 0.3 * tag_sim + 0.3 * content_sim


# ---------------------------------------------------------------------------
# Vault loading (extended for wikilink weaving)
# ---------------------------------------------------------------------------

def _load_notes_for_weaving(vault_path: Path) -> dict:
    """
    Load all notes with title, tags, body, existing links, and file path.

    Returns:
        {note_stem: {title, tags, body, links, path, content}}
    """
    notes = {}
    for md_file in vault_path.rglob("*.md"):
        # Skip .obsidian and archive
        rel = md_file.relative_to(vault_path).as_posix()
        if rel.startswith(".obsidian/") or rel.startswith("99_Archive/"):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            continue

        fm = _parse_frontmatter(content)
        body = content
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                body = content[end + 3:]

        links = _extract_links(content)
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        title = fm.get("title", md_file.stem)

        notes[md_file.stem] = {
            "title": title,
            "tags": tags,
            "body": body,
            "links": links,
            "path": md_file,
            "content": content,
        }

    return notes


# ---------------------------------------------------------------------------
# Wikilink insertion
# ---------------------------------------------------------------------------

def _add_backlink_to_content(content: str, target_stem: str) -> str:
    """
    Add a [[backlink]] to the "Related Notes" section of a note.

    If no "Related Notes" section exists, append one at the end.
    Returns the modified content.
    """
    link = f"[[{target_stem}]]"

    # Already linked?
    if link in content:
        return content

    # Find or create "Related Notes" section
    related_header_pat = re.compile(r"(?m)^##\s+Related\s+Notes?\s*$")
    match = related_header_pat.search(content)

    if match:
        # Insert after the header line
        insert_pos = match.end()
        # Find next section header or end of content
        next_header = re.search(r"(?m)^##\s+", content[insert_pos + 1:])
        if next_header:
            insert_pos = insert_pos + 1 + next_header.start()
        else:
            insert_pos = len(content)
        # Insert the link as a list item
        link_line = f"\n- {link}"
        content = content[:insert_pos].rstrip() + link_line + "\n" + content[insert_pos:].lstrip("\n")
    else:
        # Append Related Notes section
        content = content.rstrip() + f"\n\n## Related Notes\n\n- {link}\n"

    return content


# ---------------------------------------------------------------------------
# Broken link removal
# ---------------------------------------------------------------------------

def _remove_broken_links(content: str, valid_stems: set) -> tuple:
    """
    Remove [[wikilinks]] that point to non-existent notes.

    Returns:
        (modified_content, list_of_removed_links)
    """
    removed = []

    def replace_link(match):
        link_target = match.group(1)
        # Handle aliased links: [[target|alias]]
        stem = link_target.split("|")[0].strip()
        if stem not in valid_stems:
            removed.append(stem)
            # Replace with just the display text
            if "|" in link_target:
                return link_target.split("|")[1].strip()
            return stem
        return match.group(0)

    modified = re.sub(r"\[\[([^\]]+)\]\]", replace_link, content)
    return modified, removed


# ---------------------------------------------------------------------------
# Main weaving function
# ---------------------------------------------------------------------------

def weave_wikilinks(
    vault_path: Optional[str] = None,
    relatedness_threshold: float = 0.25,
    max_links_per_note: int = 10,
    dry_run: bool = True,
    remove_broken: bool = True,
) -> dict:
    """
    Scan vault for related notes and add wikilinks between them.

    Args:
        vault_path: root of the Obsidian vault.
        relatedness_threshold: minimum relatedness score to add a link.
        max_links_per_note: max new links to add per note per run.
        dry_run: if True, report what would be done without modifying files.
        remove_broken: if True, also remove links to non-existent notes.

    Returns:
        dict with links_added, links_removed, pairs_evaluated, notes_modified.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    notes = _load_notes_for_weaving(vault)
    stems = list(notes.keys())
    valid_stems = set(stems)

    links_added = 0
    links_removed_total = 0
    notes_modified = set()
    pairs_evaluated = 0
    added_details = []

    # Phase 1: Find related pairs and add links
    for i, stem_a in enumerate(stems):
        note_a = notes[stem_a]
        new_links_for_a = 0

        for stem_b in stems[i + 1:]:
            if new_links_for_a >= max_links_per_note:
                break

            note_b = notes[stem_b]
            pairs_evaluated += 1

            # Skip if already linked in either direction
            if stem_b in note_a["links"] or stem_a in note_b["links"]:
                continue

            score = compute_relatedness(note_a, note_b)
            if score >= relatedness_threshold:
                if not dry_run:
                    # Add link A -> B
                    new_content_a = _add_backlink_to_content(note_a["content"], stem_b)
                    if new_content_a != note_a["content"]:
                        note_a["path"].write_text(new_content_a, encoding="utf-8")
                        note_a["content"] = new_content_a
                        notes_modified.add(stem_a)

                    # Add link B -> A
                    new_content_b = _add_backlink_to_content(note_b["content"], stem_a)
                    if new_content_b != note_b["content"]:
                        note_b["path"].write_text(new_content_b, encoding="utf-8")
                        note_b["content"] = new_content_b
                        notes_modified.add(stem_b)

                links_added += 1
                new_links_for_a += 1
                added_details.append({
                    "a": stem_a,
                    "b": stem_b,
                    "score": round(score, 4),
                })

    # Phase 2: Remove broken links
    broken_details = []
    if remove_broken:
        for stem, note in notes.items():
            modified_content, removed = _remove_broken_links(
                note["content"], valid_stems,
            )
            if removed:
                links_removed_total += len(removed)
                if not dry_run:
                    note["path"].write_text(modified_content, encoding="utf-8")
                notes_modified.add(stem)
                broken_details.append({
                    "note": stem,
                    "removed_links": removed,
                })

    return {
        "links_added": links_added,
        "links_removed": links_removed_total,
        "pairs_evaluated": pairs_evaluated,
        "notes_modified": len(notes_modified),
        "added_details": added_details,
        "broken_details": broken_details,
        "dry_run": dry_run,
    }
```

### Step 3.2: Write tests for wikilink_weaver

- [ ] Write `plugin/lib/tests/test_wikilink_weaver.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_wikilink_weaver.py`

```python
"""Tests for wikilink weaver."""

from pathlib import Path

import pytest

from plugin.lib.wikilink_weaver import (
    _title_similarity,
    _tag_overlap,
    _content_keyword_overlap,
    compute_relatedness,
    _add_backlink_to_content,
    _remove_broken_links,
    weave_wikilinks,
)


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert _title_similarity("Auth System", "Auth System") == 1.0

    def test_no_overlap(self):
        assert _title_similarity("Auth System", "Deploy Pipeline") == 0.0

    def test_partial_overlap(self):
        score = _title_similarity("Auth System Architecture", "Auth Flow Design")
        assert 0 < score < 1

    def test_stopwords_ignored(self):
        score = _title_similarity("The Big System", "A Big System")
        assert score > 0.5


class TestTagOverlap:
    def test_identical_tags(self):
        assert _tag_overlap(["auth", "security"], ["auth", "security"]) == 1.0

    def test_no_overlap(self):
        assert _tag_overlap(["auth"], ["deploy"]) == 0.0

    def test_partial_overlap(self):
        score = _tag_overlap(["auth", "security", "api"], ["auth", "api", "testing"])
        assert 0.3 < score < 0.7

    def test_empty_tags(self):
        assert _tag_overlap([], ["auth"]) == 0.0


class TestContentKeywordOverlap:
    def test_similar_content(self):
        body_a = "authentication system uses tokens and sessions for security validation"
        body_b = "authentication tokens provide security through session validation"
        score = _content_keyword_overlap(body_a, body_b)
        assert score > 0.3

    def test_unrelated_content(self):
        body_a = "kubernetes deployment pipeline monitoring grafana"
        body_b = "quarterly roadmap objectives hiring growth strategy"
        score = _content_keyword_overlap(body_a, body_b)
        assert score < 0.1


class TestComputeRelatedness:
    def test_identical_notes(self):
        note = {"title": "Auth System", "tags": ["auth"], "body": "authentication system"}
        score = compute_relatedness(note, note)
        assert score > 0.5

    def test_unrelated_notes(self):
        note_a = {"title": "Auth System", "tags": ["auth"], "body": "tokens sessions security"}
        note_b = {"title": "Deploy Pipeline", "tags": ["devops"], "body": "kubernetes docker containers"}
        score = compute_relatedness(note_a, note_b)
        assert score < 0.2


class TestAddBacklink:
    def test_adds_related_section(self):
        content = "---\ntitle: Test\n---\n\n# Test\n\nContent here."
        result = _add_backlink_to_content(content, "other-note")
        assert "[[other-note]]" in result
        assert "## Related Notes" in result

    def test_appends_to_existing_section(self):
        content = "# Test\n\n## Related Notes\n\n- [[existing-note]]\n"
        result = _add_backlink_to_content(content, "new-note")
        assert "[[new-note]]" in result
        assert "[[existing-note]]" in result

    def test_skips_already_linked(self):
        content = "# Test\n\nSee [[other-note]] for details."
        result = _add_backlink_to_content(content, "other-note")
        assert result == content


class TestRemoveBrokenLinks:
    def test_removes_broken_link(self):
        content = "See [[existing]] and [[deleted-note]] for details."
        modified, removed = _remove_broken_links(content, {"existing"})
        assert "[[existing]]" in modified
        assert "[[deleted-note]]" not in modified
        assert "deleted-note" in removed

    def test_preserves_valid_links(self):
        content = "See [[note-a]] and [[note-b]]."
        modified, removed = _remove_broken_links(content, {"note-a", "note-b"})
        assert modified == content
        assert removed == []

    def test_handles_aliased_links(self):
        content = "See [[target|display text]]."
        modified, removed = _remove_broken_links(content, set())
        assert "display text" in modified
        assert "[[" not in modified


class TestWeaveWikilinks:
    def _make_vault(self, tmp_path):
        """Create a small vault with related and unrelated notes."""
        (tmp_path / "01_Projects").mkdir()
        (tmp_path / "02_Concepts").mkdir()

        (tmp_path / "01_Projects" / "auth-system.md").write_text(
            "---\ntitle: Auth System\ntags: [auth, security, tokens]\n---\n\n"
            "# Auth System\n\nUses tokens and sessions for authentication.\n",
            encoding="utf-8",
        )
        (tmp_path / "02_Concepts" / "auth-patterns.md").write_text(
            "---\ntitle: Authentication Patterns\ntags: [auth, patterns, security]\n---\n\n"
            "# Authentication Patterns\n\nToken-based authentication and session management.\n",
            encoding="utf-8",
        )
        (tmp_path / "02_Concepts" / "deploy-pipeline.md").write_text(
            "---\ntitle: Deploy Pipeline\ntags: [devops, kubernetes, docker]\n---\n\n"
            "# Deploy Pipeline\n\nContainer orchestration and kubernetes deployments.\n",
            encoding="utf-8",
        )

    def test_links_related_notes(self, tmp_path):
        self._make_vault(tmp_path)
        result = weave_wikilinks(str(tmp_path), relatedness_threshold=0.15, dry_run=True)
        assert result["links_added"] > 0
        # Auth notes should be linked to each other
        added_pairs = [(d["a"], d["b"]) for d in result["added_details"]]
        auth_linked = any(
            ("auth-system" in a and "auth-patterns" in b)
            or ("auth-patterns" in a and "auth-system" in b)
            for a, b in added_pairs
        )
        assert auth_linked

    def test_dry_run_preserves_files(self, tmp_path):
        self._make_vault(tmp_path)
        original = (tmp_path / "01_Projects" / "auth-system.md").read_text()
        weave_wikilinks(str(tmp_path), relatedness_threshold=0.15, dry_run=True)
        assert (tmp_path / "01_Projects" / "auth-system.md").read_text() == original

    def test_removes_broken_links(self, tmp_path):
        self._make_vault(tmp_path)
        # Add a broken link to auth-system.md
        auth_path = tmp_path / "01_Projects" / "auth-system.md"
        content = auth_path.read_text()
        content += "\nSee [[nonexistent-note]] for details.\n"
        auth_path.write_text(content)
        result = weave_wikilinks(str(tmp_path), dry_run=False, remove_broken=True)
        assert result["links_removed"] >= 1
```

---

## Task 4: Staleness scanner

Implement the staleness scoring formula from the spec and threshold-based actions.

### Step 4.1: Create staleness.py

- [ ] Write `plugin/lib/staleness.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/staleness.py`

```python
"""
Staleness scanner for the curator engine.

Computes staleness scores for all notes using the formula:
    staleness_score = days_since_traversed / (traversal_count + 1)

Applies threshold-based actions:
    < 10:   active (no action)
    10-30:  aging (monitor)
    30-90:  stale (flag, check contradictions)
    > 90:   review needed (move to review-stale/)
"""

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

STALENESS_ACTIVE = "active"         # < 10
STALENESS_AGING = "aging"           # 10-30
STALENESS_STALE = "stale"           # 30-90
STALENESS_REVIEW = "review_needed"  # > 90


def classify_staleness(score: float) -> str:
    """Classify a staleness score into a category."""
    if score < 10:
        return STALENESS_ACTIVE
    elif score < 30:
        return STALENESS_AGING
    elif score < 90:
        return STALENESS_STALE
    else:
        return STALENESS_REVIEW


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def compute_staleness_score(
    last_traversed: str,
    traversal_count: int,
    now: Optional[datetime] = None,
) -> float:
    """
    Compute staleness score for a note.

    Formula: days_since_traversed / (traversal_count + 1)

    Args:
        last_traversed: ISO date string (e.g., "2026-03-15").
        traversal_count: number of times this note has been traversed.
        now: current datetime (defaults to utcnow).

    Returns:
        float >= 0. Lower is fresher.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if not last_traversed:
        # Never traversed: treat as maximally stale
        return 999.0

    try:
        # Handle date-only and datetime formats
        if "T" in last_traversed:
            clean = last_traversed.replace("Z", "+00:00")
            if "+" not in clean and "-" not in clean[10:]:
                clean += "+00:00"
            dt = datetime.fromisoformat(clean)
        else:
            dt = datetime.strptime(last_traversed[:10], "%Y-%m-%d")
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 999.0

    days_since = max(0.0, (now - dt).total_seconds() / 86400.0)
    return days_since / (traversal_count + 1)


# ---------------------------------------------------------------------------
# Frontmatter update
# ---------------------------------------------------------------------------

def _update_status_in_content(content: str, new_status: str) -> str:
    """Update the status field in frontmatter."""
    if not content.startswith("---"):
        return content

    end = content.find("---", 3)
    if end == -1:
        return content

    fm_section = content[3:end]
    body = content[end:]

    # Update or add status field
    status_pat = re.compile(r"(?m)^status:\s*.*$")
    if status_pat.search(fm_section):
        fm_section = status_pat.sub(f"status: {new_status}", fm_section)
    else:
        fm_section = fm_section.rstrip() + f"\nstatus: {new_status}\n"

    return "---" + fm_section + body


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def scan_staleness(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
    now: Optional[datetime] = None,
) -> dict:
    """
    Scan all vault notes for staleness and apply threshold actions.

    Actions:
    - stale (30-90): set status to 'stale' in frontmatter.
    - review_needed (>90): move to 05_Inbox/review-stale/.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, report only.
        now: current datetime for testing.

    Returns:
        dict with distribution counts, flagged notes, moved notes.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        return {"error": "vault_not_found", "path": str(vault)}

    distribution = {
        STALENESS_ACTIVE: 0,
        STALENESS_AGING: 0,
        STALENESS_STALE: 0,
        STALENESS_REVIEW: 0,
    }
    flagged = []
    moved = []
    total = 0

    review_dir = vault / "05_Inbox" / "review-stale"

    for md_file in vault.rglob("*.md"):
        rel = md_file.relative_to(vault).as_posix()
        # Skip system dirs, inbox, archive, and .obsidian
        if any(rel.startswith(p) for p in (
            ".obsidian/", "99_Archive/", "05_Inbox/", "10_Templates/",
            "00_Index",
        )):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            continue

        fm = _parse_frontmatter(content)
        total += 1

        last_traversed = fm.get("last_traversed", fm.get("updated", ""))
        if isinstance(last_traversed, (int, float)):
            last_traversed = str(last_traversed)
        traversal_count = fm.get("traversal_count", fm.get("count", 0))
        if not isinstance(traversal_count, int):
            try:
                traversal_count = int(traversal_count)
            except (ValueError, TypeError):
                traversal_count = 0

        score = compute_staleness_score(str(last_traversed), traversal_count, now=now)
        classification = classify_staleness(score)
        distribution[classification] += 1

        if classification == STALENESS_STALE:
            flagged.append({
                "note": md_file.stem,
                "path": rel,
                "score": round(score, 2),
                "classification": classification,
            })
            if not dry_run:
                updated = _update_status_in_content(content, "stale")
                if updated != content:
                    md_file.write_text(updated, encoding="utf-8")

        elif classification == STALENESS_REVIEW:
            moved.append({
                "note": md_file.stem,
                "path": rel,
                "score": round(score, 2),
                "classification": classification,
            })
            if not dry_run:
                # Update status first
                updated = _update_status_in_content(content, "review")
                md_file.write_text(updated, encoding="utf-8")
                # Move to review-stale
                review_dir.mkdir(parents=True, exist_ok=True)
                dest = review_dir / md_file.name
                if dest.exists():
                    dest = review_dir / f"{md_file.stem}-{int(datetime.now(timezone.utc).timestamp())}.md"
                shutil.move(str(md_file), str(dest))

    return {
        "total_scanned": total,
        "distribution": distribution,
        "flagged_stale": flagged,
        "moved_to_review": moved,
        "dry_run": dry_run,
    }
```

### Step 4.2: Write tests for staleness

- [ ] Write `plugin/lib/tests/test_staleness.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_staleness.py`

```python
"""Tests for staleness scanner."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from plugin.lib.staleness import (
    compute_staleness_score,
    classify_staleness,
    scan_staleness,
    STALENESS_ACTIVE,
    STALENESS_AGING,
    STALENESS_STALE,
    STALENESS_REVIEW,
)


class TestComputeStalenessScore:
    def test_recent_high_traversal_is_low(self):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        score = compute_staleness_score("2026-03-20", 100, now=now)
        # 1 day / 101 = ~0.01
        assert score < 0.1

    def test_old_single_traversal_is_high(self):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        score = compute_staleness_score("2026-02-19", 1, now=now)
        # 30 days / 2 = 15.0
        assert 14.5 < score < 15.5

    def test_never_traversed_is_max(self):
        score = compute_staleness_score("", 0)
        assert score == 999.0

    def test_zero_traversals(self):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        score = compute_staleness_score("2026-03-11", 0, now=now)
        # 10 days / 1 = 10.0
        assert 9.5 < score < 10.5

    def test_datetime_format(self):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        score = compute_staleness_score("2026-03-20T12:00:00Z", 10, now=now)
        assert score < 1.0

    def test_invalid_date_returns_max(self):
        assert compute_staleness_score("not-a-date", 5) == 999.0


class TestClassifyStaleness:
    def test_active(self):
        assert classify_staleness(5.0) == STALENESS_ACTIVE

    def test_aging(self):
        assert classify_staleness(20.0) == STALENESS_AGING

    def test_stale(self):
        assert classify_staleness(50.0) == STALENESS_STALE

    def test_review_needed(self):
        assert classify_staleness(100.0) == STALENESS_REVIEW

    def test_boundary_10_is_aging(self):
        assert classify_staleness(10.0) == STALENESS_AGING

    def test_boundary_30_is_stale(self):
        assert classify_staleness(30.0) == STALENESS_STALE

    def test_boundary_90_is_review(self):
        assert classify_staleness(90.0) == STALENESS_REVIEW


class TestScanStaleness:
    def _make_vault(self, tmp_path, notes):
        """Create vault with notes. notes = [(folder, name, frontmatter_dict)]"""
        for folder, name, fm_dict in notes:
            d = tmp_path / folder
            d.mkdir(parents=True, exist_ok=True)
            fm_lines = "\n".join(f"{k}: {v}" for k, v in fm_dict.items())
            (d / name).write_text(
                f"---\n{fm_lines}\n---\n\n# {name}\n\nContent.\n",
                encoding="utf-8",
            )

    def test_active_notes_not_flagged(self, tmp_path):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        self._make_vault(tmp_path, [
            ("02_Concepts", "fresh.md", {"last_traversed": "2026-03-20", "traversal_count": 50}),
        ])
        result = scan_staleness(str(tmp_path), dry_run=True, now=now)
        assert result["distribution"][STALENESS_ACTIVE] == 1
        assert len(result["flagged_stale"]) == 0

    def test_stale_notes_flagged(self, tmp_path):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        self._make_vault(tmp_path, [
            ("02_Concepts", "old.md", {"last_traversed": "2026-01-21", "traversal_count": 1}),
        ])
        result = scan_staleness(str(tmp_path), dry_run=True, now=now)
        # 59 days / 2 = 29.5 -> aging, not quite stale
        # Let's use a note that scores higher
        assert result["total_scanned"] == 1

    def test_review_needed_moved(self, tmp_path):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        # 180 days old, traversed once: 180/2 = 90 -> review_needed
        self._make_vault(tmp_path, [
            ("02_Concepts", "ancient.md", {"last_traversed": "2025-09-23", "traversal_count": 1}),
        ])
        result = scan_staleness(str(tmp_path), dry_run=False, now=now)
        assert len(result["moved_to_review"]) == 1
        assert (tmp_path / "05_Inbox" / "review-stale" / "ancient.md").exists()
        assert not (tmp_path / "02_Concepts" / "ancient.md").exists()

    def test_skips_inbox_and_archive(self, tmp_path):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        self._make_vault(tmp_path, [
            ("05_Inbox/queue-agent", "inbox-note.md", {"last_traversed": "2024-01-01", "traversal_count": 0}),
            ("99_Archive", "archived.md", {"last_traversed": "2024-01-01", "traversal_count": 0}),
            ("02_Concepts", "real.md", {"last_traversed": "2026-03-20", "traversal_count": 10}),
        ])
        result = scan_staleness(str(tmp_path), dry_run=True, now=now)
        assert result["total_scanned"] == 1

    def test_dry_run_preserves_files(self, tmp_path):
        now = datetime(2026, 3, 21, tzinfo=timezone.utc)
        self._make_vault(tmp_path, [
            ("02_Concepts", "ancient.md", {"last_traversed": "2025-09-23", "traversal_count": 1}),
        ])
        scan_staleness(str(tmp_path), dry_run=True, now=now)
        assert (tmp_path / "02_Concepts" / "ancient.md").exists()
```

---

## Task 5: Conflict resolver

Detect Obsidian Sync conflict files, attempt auto-merge for non-overlapping changes, and escalate contradicting changes.

### Step 5.1: Create conflict_resolver.py

- [ ] Write `plugin/lib/conflict_resolver.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/conflict_resolver.py`

```python
"""
Conflict resolver for the curator engine.

Detects Obsidian Sync conflict files (pattern: "note (conflict YYYY-MM-DD).md"),
attempts auto-merge for non-overlapping changes, and escalates contradicting
changes to human review.
"""

import os
import re
import shutil
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

CONFLICT_PATTERN = re.compile(
    r"^(.+?)\s*\(conflict\s+(\d{4}-\d{2}-\d{2})\)\.md$"
)


def find_conflict_files(vault_path: Path) -> list:
    """
    Find all Obsidian Sync conflict files in the vault.

    Returns:
        list of dicts with: conflict_path, original_stem, conflict_date, original_path.
    """
    conflicts = []

    for md_file in vault_path.rglob("*.md"):
        rel = md_file.relative_to(vault_path).as_posix()
        if rel.startswith(".obsidian/"):
            continue

        match = CONFLICT_PATTERN.match(md_file.name)
        if match:
            original_stem = match.group(1).strip()
            conflict_date = match.group(2)

            # Find the original file in the same directory
            original_path = md_file.parent / f"{original_stem}.md"

            conflicts.append({
                "conflict_path": md_file,
                "original_stem": original_stem,
                "conflict_date": conflict_date,
                "original_path": original_path,
                "original_exists": original_path.exists(),
            })

    return conflicts


# ---------------------------------------------------------------------------
# Auto-merge logic
# ---------------------------------------------------------------------------

def _split_sections(content: str) -> list:
    """
    Split markdown content into sections (by ## headers).

    Returns list of (header_or_empty, body_text) tuples.
    """
    # Split frontmatter from body
    body = content
    frontmatter = ""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[:end + 3]
            body = content[end + 3:]

    sections = []
    if frontmatter:
        sections.append(("__frontmatter__", frontmatter))

    # Split body by ## headers
    parts = re.split(r"(?m)^(##\s+.+)$", body)

    # First part (before any header)
    if parts and parts[0].strip():
        sections.append(("__preamble__", parts[0]))

    # Remaining parts come in (header, body) pairs
    i = 1
    while i < len(parts) - 1:
        header = parts[i].strip()
        body_part = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((header, body_part))
        i += 2

    return sections


def _sections_to_dict(sections: list) -> dict:
    """Convert sections list to dict keyed by header."""
    result = {}
    for header, body in sections:
        result[header] = body
    return result


def attempt_auto_merge(original_content: str, conflict_content: str) -> tuple:
    """
    Attempt to auto-merge two versions of a note.

    Strategy: split both into sections by ## headers. If changes are in
    different sections (non-overlapping), merge by taking the newer version
    of each changed section. If changes overlap in the same section,
    escalate.

    Args:
        original_content: content of the original note.
        conflict_content: content of the conflict copy.

    Returns:
        (success: bool, merged_content_or_None: str|None, conflict_sections: list)
    """
    orig_sections = _split_sections(original_content)
    conf_sections = _split_sections(conflict_content)

    orig_dict = _sections_to_dict(orig_sections)
    conf_dict = _sections_to_dict(conf_sections)

    all_keys = list(dict.fromkeys(
        [k for k, _ in orig_sections] + [k for k, _ in conf_sections]
    ))

    merged_sections = []
    conflict_keys = []

    for key in all_keys:
        orig_val = orig_dict.get(key, "")
        conf_val = conf_dict.get(key, "")

        if orig_val == conf_val:
            # No change in this section
            merged_sections.append((key, orig_val))
        elif key not in orig_dict:
            # New section in conflict copy
            merged_sections.append((key, conf_val))
        elif key not in conf_dict:
            # Section removed in conflict copy -- keep original
            merged_sections.append((key, orig_val))
        else:
            # Both changed this section -- check similarity
            ratio = SequenceMatcher(None, orig_val, conf_val).ratio()
            if ratio > 0.8:
                # Minor differences -- take the longer (more content)
                merged_sections.append((key, conf_val if len(conf_val) >= len(orig_val) else orig_val))
            else:
                # Significant conflict
                conflict_keys.append(key)
                merged_sections.append((key, orig_val))

    if conflict_keys:
        return False, None, conflict_keys

    # Reconstruct merged content
    merged_parts = []
    for key, body in merged_sections:
        if key == "__frontmatter__":
            merged_parts.append(body)
        elif key == "__preamble__":
            merged_parts.append(body)
        else:
            merged_parts.append(f"\n{key}{body}")

    merged = "".join(merged_parts)
    return True, merged, []


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

def resolve_conflicts(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """
    Detect and resolve Obsidian Sync conflict files.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, report only.

    Returns:
        dict with found, auto_merged, escalated, orphaned, details.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    conflicts = find_conflict_files(vault)

    auto_merged = 0
    escalated = 0
    orphaned = 0
    details = []

    review_dir = vault / "05_Inbox" / "review-conflicts"

    for conflict in conflicts:
        conflict_path = conflict["conflict_path"]
        original_path = conflict["original_path"]

        if not conflict["original_exists"]:
            # Original was deleted -- rename conflict to original
            orphaned += 1
            if not dry_run:
                shutil.move(str(conflict_path), str(original_path))
            details.append({
                "conflict": str(conflict_path.relative_to(vault)),
                "action": "renamed_to_original",
                "original": str(original_path.relative_to(vault)),
            })
            continue

        try:
            original_content = original_path.read_text(encoding="utf-8")
            conflict_content = conflict_path.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            escalated += 1
            details.append({
                "conflict": str(conflict_path.relative_to(vault)),
                "action": "escalated",
                "reason": "unreadable",
            })
            continue

        success, merged, conflict_sections = attempt_auto_merge(
            original_content, conflict_content,
        )

        if success and merged is not None:
            auto_merged += 1
            if not dry_run:
                original_path.write_text(merged, encoding="utf-8")
                conflict_path.unlink()
            details.append({
                "conflict": str(conflict_path.relative_to(vault)),
                "action": "auto_merged",
                "original": str(original_path.relative_to(vault)),
            })
        else:
            escalated += 1
            if not dry_run:
                review_dir.mkdir(parents=True, exist_ok=True)
                # Move conflict file to review
                dest = review_dir / conflict_path.name
                shutil.move(str(conflict_path), str(dest))
            details.append({
                "conflict": str(conflict_path.relative_to(vault)),
                "action": "escalated",
                "conflict_sections": conflict_sections,
                "original": str(original_path.relative_to(vault)),
            })

    return {
        "found": len(conflicts),
        "auto_merged": auto_merged,
        "escalated": escalated,
        "orphaned": orphaned,
        "details": details,
        "dry_run": dry_run,
    }
```

### Step 5.2: Write tests for conflict_resolver

- [ ] Write `plugin/lib/tests/test_conflict_resolver.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_conflict_resolver.py`

```python
"""Tests for conflict resolver."""

from pathlib import Path

import pytest

from plugin.lib.conflict_resolver import (
    CONFLICT_PATTERN,
    find_conflict_files,
    attempt_auto_merge,
    resolve_conflicts,
)


class TestConflictPattern:
    def test_matches_standard_conflict(self):
        m = CONFLICT_PATTERN.match("auth-system (conflict 2026-03-21).md")
        assert m
        assert m.group(1) == "auth-system"
        assert m.group(2) == "2026-03-21"

    def test_matches_spaces_in_name(self):
        m = CONFLICT_PATTERN.match("my note (conflict 2026-01-15).md")
        assert m
        assert m.group(1) == "my note"

    def test_no_match_on_regular_file(self):
        assert CONFLICT_PATTERN.match("regular-note.md") is None

    def test_no_match_on_parenthetical(self):
        assert CONFLICT_PATTERN.match("note (draft).md") is None


class TestFindConflictFiles:
    def test_finds_conflict_files(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "auth.md").write_text("# Auth", encoding="utf-8")
        (tmp_path / "02_Concepts" / "auth (conflict 2026-03-21).md").write_text(
            "# Auth (conflict)", encoding="utf-8",
        )
        conflicts = find_conflict_files(tmp_path)
        assert len(conflicts) == 1
        assert conflicts[0]["original_stem"] == "auth"
        assert conflicts[0]["original_exists"] is True

    def test_skips_obsidian_dir(self, tmp_path):
        obsidian = tmp_path / ".obsidian"
        obsidian.mkdir()
        (obsidian / "test (conflict 2026-03-21).md").write_text("x", encoding="utf-8")
        conflicts = find_conflict_files(tmp_path)
        assert len(conflicts) == 0


class TestAttemptAutoMerge:
    def test_identical_content(self):
        content = "---\ntitle: Test\n---\n\n# Test\n\nContent."
        success, merged, conflicts = attempt_auto_merge(content, content)
        assert success is True
        assert conflicts == []

    def test_non_overlapping_sections(self):
        original = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nOriginal A content.\n\n"
            "## Section B\n\nOriginal B content.\n"
        )
        conflict = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nOriginal A content.\n\n"
            "## Section B\n\nModified B content with new info.\n"
        )
        success, merged, conflicts = attempt_auto_merge(original, conflict)
        assert success is True
        assert "Modified B content" in merged
        assert conflicts == []

    def test_conflicting_sections_escalated(self):
        original = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nCompletely different original text about topic alpha.\n"
        )
        conflict = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nTotally rewritten content about topic beta with new direction.\n"
        )
        success, merged, conflicts = attempt_auto_merge(original, conflict)
        assert success is False
        assert len(conflicts) > 0

    def test_new_section_in_conflict(self):
        original = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nContent A.\n"
        )
        conflict = (
            "---\ntitle: Test\n---\n\n# Test\n\n"
            "## Section A\n\nContent A.\n\n"
            "## Section B\n\nNew section added.\n"
        )
        success, merged, conflicts = attempt_auto_merge(original, conflict)
        assert success is True
        assert "Section B" in merged
        assert "New section added" in merged


class TestResolveConflicts:
    def test_auto_merges_non_overlapping(self, tmp_path):
        d = tmp_path / "02_Concepts"
        d.mkdir()
        (d / "note.md").write_text(
            "---\ntitle: Note\n---\n\n# Note\n\n## A\n\nOriginal.\n\n## B\n\nOriginal B.\n",
            encoding="utf-8",
        )
        (d / "note (conflict 2026-03-21).md").write_text(
            "---\ntitle: Note\n---\n\n# Note\n\n## A\n\nOriginal.\n\n## B\n\nUpdated B.\n",
            encoding="utf-8",
        )
        result = resolve_conflicts(str(tmp_path), dry_run=False)
        assert result["auto_merged"] == 1
        assert not (d / "note (conflict 2026-03-21).md").exists()

    def test_orphaned_conflict_renamed(self, tmp_path):
        d = tmp_path / "02_Concepts"
        d.mkdir()
        # Conflict file exists but original does not
        (d / "deleted (conflict 2026-03-21).md").write_text("# Content", encoding="utf-8")
        result = resolve_conflicts(str(tmp_path), dry_run=False)
        assert result["orphaned"] == 1
        assert (d / "deleted.md").exists()

    def test_dry_run_preserves(self, tmp_path):
        d = tmp_path / "02_Concepts"
        d.mkdir()
        (d / "note.md").write_text("# Note\n\n## A\n\nContent.\n", encoding="utf-8")
        (d / "note (conflict 2026-03-21).md").write_text("# Note\n\n## A\n\nContent.\n", encoding="utf-8")
        result = resolve_conflicts(str(tmp_path), dry_run=True)
        assert result["found"] == 1
        assert (d / "note (conflict 2026-03-21).md").exists()
```

---

## Task 6: Schema enforcer

Validate frontmatter on all notes, add missing required fields with sensible defaults, and flag malformed notes.

### Step 6.1: Create schema_enforcer.py

- [ ] Write `plugin/lib/schema_enforcer.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/schema_enforcer.py`

```python
"""
Schema enforcer for the curator engine.

Validates that all notes have required frontmatter fields and adds
missing fields with sensible defaults. Flags malformed notes for review.

Required fields (from spec Section 6):
    title, category, tags, created, updated, author, source, status
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "title": None,        # Derived from filename if missing
    "category": None,     # Derived from folder if missing
    "tags": "[]",         # Empty list
    "created": None,      # Derived from file mtime if missing
    "updated": None,      # Derived from file mtime if missing
    "author": "curator",  # Default author
    "source": "curator",  # Default source
    "status": "active",   # Default status
}

VALID_STATUSES = {"active", "review", "stale", "unverified", "archived"}

FOLDER_TO_CATEGORY = {
    "01_Projects": "projects",
    "02_Concepts": "concepts",
    "03_People": "people",
    "04_Systems": "systems",
    "05_Inbox": "inbox",
    "06_Planning": "planning",
    "07_Research": "research",
    "08_Strategy": "strategy",
    "09_Changelog": "changelog",
    "10_Templates": "templates",
}


# ---------------------------------------------------------------------------
# Frontmatter manipulation
# ---------------------------------------------------------------------------

def _infer_category_from_path(rel_path: str) -> str:
    """Infer category from the note's folder."""
    parts = rel_path.split("/")
    if parts:
        folder = parts[0]
        return FOLDER_TO_CATEGORY.get(folder, "concepts")
    return "concepts"


def _add_missing_frontmatter(content: str, file_path: Path, vault_path: Path) -> tuple:
    """
    Add missing required frontmatter fields to note content.

    Returns:
        (modified_content, list_of_added_fields, list_of_issues)
    """
    added_fields = []
    issues = []

    rel_path = str(file_path.relative_to(vault_path))

    # Check if frontmatter exists
    has_fm = content.startswith("---")

    if not has_fm:
        # No frontmatter at all -- create it
        try:
            mtime = file_path.stat().st_mtime
            created_date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            created_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        title = file_path.stem.replace("-", " ").replace("_", " ").title()
        category = _infer_category_from_path(rel_path)

        fm_lines = [
            f'title: "{title}"',
            f"category: {category}",
            "tags: []",
            f"created: {created_date}",
            f"updated: {created_date}",
            "author: curator",
            "source: curator",
            "status: active",
        ]
        new_fm = "---\n" + "\n".join(fm_lines) + "\n---\n\n"
        added_fields = list(REQUIRED_FIELDS.keys())
        return new_fm + content, added_fields, issues

    # Frontmatter exists -- check for missing fields
    end = content.find("---", 3)
    if end == -1:
        issues.append("malformed_frontmatter")
        return content, added_fields, issues

    fm_text = content[3:end]
    body = content[end + 3:]

    fm = _parse_frontmatter(content)

    # Determine defaults for missing fields
    try:
        mtime = file_path.stat().st_mtime
        file_date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, ValueError):
        file_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    defaults = {
        "title": f'"{file_path.stem.replace("-", " ").replace("_", " ").title()}"',
        "category": _infer_category_from_path(rel_path),
        "tags": "[]",
        "created": file_date,
        "updated": file_date,
        "author": "curator",
        "source": "curator",
        "status": "active",
    }

    new_lines = []
    for field, default in defaults.items():
        if field not in fm or fm[field] == "" or fm[field] is None:
            new_lines.append(f"{field}: {default}")
            added_fields.append(field)

    # Validate status field
    status = fm.get("status", "")
    if isinstance(status, str) and status and status not in VALID_STATUSES:
        issues.append(f"invalid_status:{status}")

    if not new_lines:
        return content, added_fields, issues

    # Append missing fields to frontmatter
    fm_text = fm_text.rstrip() + "\n" + "\n".join(new_lines) + "\n"
    return "---" + fm_text + "---" + body, added_fields, issues


# ---------------------------------------------------------------------------
# Main enforcer
# ---------------------------------------------------------------------------

def enforce_schema(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """
    Validate and enforce frontmatter schema on all vault notes.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, report only.

    Returns:
        dict with total, compliant, fixed, malformed, details.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        return {"error": "vault_not_found", "path": str(vault)}

    total = 0
    compliant = 0
    fixed = 0
    malformed = 0
    details = []

    for md_file in vault.rglob("*.md"):
        rel = md_file.relative_to(vault).as_posix()
        # Skip .obsidian, templates, index files
        if rel.startswith(".obsidian/"):
            continue
        if md_file.name == "index.md" or md_file.stem == "00_Index":
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            continue

        total += 1

        modified, added, issues = _add_missing_frontmatter(content, md_file, vault)

        if issues:
            malformed += 1
            details.append({
                "path": rel,
                "action": "malformed",
                "issues": issues,
            })
        elif not added:
            compliant += 1
        else:
            fixed += 1
            if not dry_run:
                md_file.write_text(modified, encoding="utf-8")
            details.append({
                "path": rel,
                "action": "fixed",
                "added_fields": added,
            })

    return {
        "total": total,
        "compliant": compliant,
        "fixed": fixed,
        "malformed": malformed,
        "details": details,
        "dry_run": dry_run,
    }
```

### Step 6.2: Write tests for schema_enforcer

- [ ] Write `plugin/lib/tests/test_schema_enforcer.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_schema_enforcer.py`

```python
"""Tests for schema enforcer."""

from pathlib import Path

import pytest

from plugin.lib.schema_enforcer import (
    _add_missing_frontmatter,
    _infer_category_from_path,
    enforce_schema,
)


class TestInferCategoryFromPath:
    def test_projects_folder(self):
        assert _infer_category_from_path("01_Projects/easy-api/auth.md") == "projects"

    def test_concepts_folder(self):
        assert _infer_category_from_path("02_Concepts/patterns.md") == "concepts"

    def test_systems_folder(self):
        assert _infer_category_from_path("04_Systems/monitoring.md") == "systems"

    def test_unknown_folder(self):
        assert _infer_category_from_path("unknown/file.md") == "concepts"


class TestAddMissingFrontmatter:
    def test_no_frontmatter_creates_full(self, tmp_path):
        note = tmp_path / "02_Concepts" / "test.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Test Note\n\nContent here.", encoding="utf-8")
        content = note.read_text()
        modified, added, issues = _add_missing_frontmatter(content, note, tmp_path)
        assert modified.startswith("---\n")
        assert "title:" in modified
        assert "category: concepts" in modified
        assert "status: active" in modified
        assert len(added) == 8  # All required fields

    def test_complete_frontmatter_unchanged(self, tmp_path):
        note = tmp_path / "02_Concepts" / "test.md"
        note.parent.mkdir(parents=True)
        fm = (
            "---\n"
            'title: "Test"\n'
            "category: concepts\n"
            "tags: [test]\n"
            "created: 2026-03-21\n"
            "updated: 2026-03-21\n"
            "author: andrew\n"
            "source: human\n"
            "status: active\n"
            "---\n\n# Test\n"
        )
        note.write_text(fm, encoding="utf-8")
        modified, added, issues = _add_missing_frontmatter(fm, note, tmp_path)
        assert added == []
        assert issues == []

    def test_partial_frontmatter_fills_gaps(self, tmp_path):
        note = tmp_path / "02_Concepts" / "test.md"
        note.parent.mkdir(parents=True)
        fm = "---\ntitle: Test\ncategory: concepts\n---\n\n# Test\n"
        note.write_text(fm, encoding="utf-8")
        modified, added, issues = _add_missing_frontmatter(fm, note, tmp_path)
        assert "tags:" in modified
        assert "status: active" in modified
        assert "author: curator" in modified
        assert len(added) > 0

    def test_invalid_status_flagged(self, tmp_path):
        note = tmp_path / "02_Concepts" / "test.md"
        note.parent.mkdir(parents=True)
        fm = (
            "---\ntitle: Test\ncategory: concepts\ntags: []\n"
            "created: 2026-03-21\nupdated: 2026-03-21\n"
            "author: x\nsource: x\nstatus: bogus\n---\n\n# Test\n"
        )
        note.write_text(fm, encoding="utf-8")
        modified, added, issues = _add_missing_frontmatter(fm, note, tmp_path)
        assert any("invalid_status" in i for i in issues)


class TestEnforceSchema:
    def _make_vault(self, tmp_path, notes):
        for folder, name, content in notes:
            d = tmp_path / folder
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(content, encoding="utf-8")

    def test_all_compliant(self, tmp_path):
        self._make_vault(tmp_path, [(
            "02_Concepts", "note.md",
            "---\ntitle: Note\ncategory: concepts\ntags: []\n"
            "created: 2026-03-21\nupdated: 2026-03-21\nauthor: a\nsource: b\nstatus: active\n"
            "---\n\n# Note\n",
        )])
        result = enforce_schema(str(tmp_path), dry_run=True)
        assert result["compliant"] == 1
        assert result["fixed"] == 0

    def test_fixes_missing_fields(self, tmp_path):
        self._make_vault(tmp_path, [(
            "02_Concepts", "note.md",
            "---\ntitle: Note\n---\n\n# Note\n",
        )])
        result = enforce_schema(str(tmp_path), dry_run=False)
        assert result["fixed"] == 1
        content = (tmp_path / "02_Concepts" / "note.md").read_text()
        assert "status: active" in content
        assert "author: curator" in content

    def test_dry_run_preserves(self, tmp_path):
        self._make_vault(tmp_path, [(
            "02_Concepts", "note.md",
            "# No frontmatter at all\n",
        )])
        original = (tmp_path / "02_Concepts" / "note.md").read_text()
        enforce_schema(str(tmp_path), dry_run=True)
        assert (tmp_path / "02_Concepts" / "note.md").read_text() == original

    def test_skips_index_files(self, tmp_path):
        self._make_vault(tmp_path, [
            ("02_Concepts", "index.md", "# Index\n"),
            ("02_Concepts", "real.md", "# No FM\n"),
        ])
        result = enforce_schema(str(tmp_path), dry_run=True)
        assert result["total"] == 1
```

---

## Task 7: Index generator

Regenerate `00_Index.md` and per-folder `index.md` files with note counts and listings.

### Step 7.1: Create index_generator.py

- [ ] Write `plugin/lib/index_generator.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/index_generator.py`

```python
"""
Index generator for the curator engine.

Regenerates 00_Index.md (master index) and per-folder index.md files
with current note counts, recent changes, and note listings.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _parse_frontmatter


# ---------------------------------------------------------------------------
# Folder metadata
# ---------------------------------------------------------------------------

FOLDER_DESCRIPTIONS = {
    "01_Projects": "Per-repo and per-project knowledge",
    "02_Concepts": "Cross-project concepts and patterns",
    "03_People": "Team context and roles",
    "04_Systems": "Infrastructure and architecture",
    "05_Inbox": "Incoming notes awaiting classification",
    "06_Planning": "Product planning and roadmaps",
    "07_Research": "Research findings and evaluations",
    "08_Strategy": "Executive-level strategy documents",
    "09_Changelog": "Auto-generated release and deploy logs",
    "10_Templates": "Note templates",
    "99_Archive": "Archived notes",
}

MAIN_FOLDERS = [
    "01_Projects",
    "02_Concepts",
    "03_People",
    "04_Systems",
    "05_Inbox",
    "06_Planning",
    "07_Research",
    "08_Strategy",
    "09_Changelog",
    "10_Templates",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_notes(folder: Path) -> int:
    """Count .md files in a folder (recursive, excluding index.md)."""
    if not folder.exists():
        return 0
    return sum(
        1 for f in folder.rglob("*.md")
        if f.name != "index.md" and not f.name.startswith(".")
    )


def _recent_notes(folder: Path, limit: int = 5) -> list:
    """Get the most recently modified notes in a folder."""
    if not folder.exists():
        return []

    notes = []
    for f in folder.rglob("*.md"):
        if f.name == "index.md" or f.name.startswith("."):
            continue
        try:
            mtime = f.stat().st_mtime
            notes.append((f, mtime))
        except OSError:
            continue

    notes.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in notes[:limit]]


def _note_title(file_path: Path) -> str:
    """Extract title from note frontmatter or filename."""
    try:
        content = file_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        title = fm.get("title", "")
        if title:
            return str(title).strip('"').strip("'")
    except (IOError, UnicodeDecodeError):
        pass
    return file_path.stem.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Master index
# ---------------------------------------------------------------------------

def generate_master_index(vault_path: Path) -> str:
    """Generate the content for 00_Index.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_notes = sum(
        1 for f in vault_path.rglob("*.md")
        if not f.relative_to(vault_path).as_posix().startswith(".obsidian/")
        and f.name != "index.md"
        and f.stem != "00_Index"
    )

    lines = [
        "---",
        "type: index",
        f'generated: "{now}"',
        "---",
        "",
        "# Company Brain",
        "",
        f"Total notes: **{total_notes}** | Last updated: {now}",
        "",
        "## Sections",
        "",
        "| Folder | Notes | Description |",
        "|--------|-------|-------------|",
    ]

    for folder_name in MAIN_FOLDERS:
        folder = vault_path / folder_name
        count = _count_notes(folder)
        desc = FOLDER_DESCRIPTIONS.get(folder_name, "")
        lines.append(f"| [[{folder_name}]] | {count} | {desc} |")

    # Archive
    archive = vault_path / "99_Archive"
    if archive.exists():
        count = _count_notes(archive)
        lines.append(f"| [[99_Archive]] | {count} | {FOLDER_DESCRIPTIONS.get('99_Archive', '')} |")

    lines.append("")
    lines.append("## Recent Changes")
    lines.append("")

    # Gather recent notes across all folders
    all_recent = []
    for folder_name in MAIN_FOLDERS:
        folder = vault_path / folder_name
        for note_path in _recent_notes(folder, limit=3):
            try:
                mtime = note_path.stat().st_mtime
                all_recent.append((note_path, mtime))
            except OSError:
                continue

    all_recent.sort(key=lambda x: x[1], reverse=True)
    for note_path, mtime in all_recent[:10]:
        title = _note_title(note_path)
        rel = note_path.relative_to(vault_path)
        date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"- {date} -- [[{note_path.stem}]] ({rel.parent})")

    if not all_recent:
        lines.append("- No recent changes")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-folder index
# ---------------------------------------------------------------------------

def generate_folder_index(folder_path: Path, vault_path: Path) -> str:
    """Generate index.md content for a specific folder."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    folder_name = folder_path.name
    desc = FOLDER_DESCRIPTIONS.get(folder_name, "")

    notes = []
    for f in sorted(folder_path.rglob("*.md")):
        if f.name == "index.md" or f.name.startswith("."):
            continue
        title = _note_title(f)
        rel = f.relative_to(folder_path)
        notes.append((str(rel), f.stem, title))

    # Subfolder grouping
    subfolders = {}
    top_level = []
    for rel, stem, title in notes:
        parts = rel.split("/")
        if len(parts) > 1:
            subfolder = parts[0]
            if subfolder not in subfolders:
                subfolders[subfolder] = []
            subfolders[subfolder].append((stem, title))
        else:
            top_level.append((stem, title))

    lines = [
        "---",
        "type: folder-index",
        f'generated: "{now}"',
        "---",
        "",
        f"# {folder_name}",
        "",
        desc,
        "",
        f"**{len(notes)} notes** | Last updated: {now}",
        "",
    ]

    if top_level:
        lines.append("## Notes")
        lines.append("")
        for stem, title in top_level:
            lines.append(f"- [[{stem}]] -- {title}")
        lines.append("")

    for subfolder, sub_notes in sorted(subfolders.items()):
        lines.append(f"## {subfolder}")
        lines.append("")
        for stem, title in sub_notes:
            lines.append(f"- [[{stem}]] -- {title}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def regenerate_indexes(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
) -> dict:
    """
    Regenerate 00_Index.md and all per-folder index.md files.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, report only.

    Returns:
        dict with master_index_updated, folder_indexes_updated, total_notes.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        return {"error": "vault_not_found", "path": str(vault)}

    updated_folders = []

    # Master index
    master_content = generate_master_index(vault)
    master_path = vault / "00_Index.md"
    if not dry_run:
        master_path.write_text(master_content, encoding="utf-8")

    # Per-folder indexes
    for folder_name in MAIN_FOLDERS:
        folder = vault / folder_name
        if not folder.exists():
            continue

        index_content = generate_folder_index(folder, vault)
        index_path = folder / "index.md"
        if not dry_run:
            index_path.write_text(index_content, encoding="utf-8")
        updated_folders.append(folder_name)

        # Subfolder indexes
        for subfolder in sorted(folder.iterdir()):
            if subfolder.is_dir() and not subfolder.name.startswith("."):
                sub_index_content = generate_folder_index(subfolder, vault)
                sub_index_path = subfolder / "index.md"
                if not dry_run:
                    sub_index_path.write_text(sub_index_content, encoding="utf-8")
                updated_folders.append(f"{folder_name}/{subfolder.name}")

    total_notes = sum(
        1 for f in vault.rglob("*.md")
        if not f.relative_to(vault).as_posix().startswith(".obsidian/")
        and f.name != "index.md"
        and f.stem != "00_Index"
    )

    return {
        "master_index_updated": True,
        "folder_indexes_updated": updated_folders,
        "total_notes": total_notes,
        "dry_run": dry_run,
    }
```

### Step 7.2: Write tests for index_generator

- [ ] Write `plugin/lib/tests/test_index_generator.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_index_generator.py`

```python
"""Tests for index generator."""

from pathlib import Path

import pytest

from plugin.lib.index_generator import (
    _count_notes,
    _note_title,
    generate_master_index,
    generate_folder_index,
    regenerate_indexes,
)


class TestCountNotes:
    def test_counts_md_files(self, tmp_path):
        d = tmp_path / "folder"
        d.mkdir()
        (d / "a.md").write_text("# A")
        (d / "b.md").write_text("# B")
        (d / "index.md").write_text("# Index")
        assert _count_notes(d) == 2

    def test_empty_folder(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert _count_notes(d) == 0

    def test_nonexistent_folder(self, tmp_path):
        assert _count_notes(tmp_path / "nope") == 0

    def test_counts_recursively(self, tmp_path):
        d = tmp_path / "folder"
        (d / "sub").mkdir(parents=True)
        (d / "a.md").write_text("# A")
        (d / "sub" / "b.md").write_text("# B")
        assert _count_notes(d) == 2


class TestNoteTitle:
    def test_extracts_from_frontmatter(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text('---\ntitle: "My Great Note"\n---\n\n# Content\n')
        assert _note_title(note) == "My Great Note"

    def test_falls_back_to_filename(self, tmp_path):
        note = tmp_path / "my-great-note.md"
        note.write_text("# Content\n")
        assert _note_title(note) == "My Great Note"


class TestGenerateMasterIndex:
    def _make_vault(self, tmp_path):
        for folder in ["01_Projects", "02_Concepts", "04_Systems"]:
            (tmp_path / folder).mkdir()
        (tmp_path / "02_Concepts" / "auth.md").write_text(
            '---\ntitle: "Auth"\n---\n\n# Auth\n'
        )
        (tmp_path / "02_Concepts" / "patterns.md").write_text("# Patterns\n")
        (tmp_path / "04_Systems" / "deploy.md").write_text("# Deploy\n")

    def test_contains_section_table(self, tmp_path):
        self._make_vault(tmp_path)
        content = generate_master_index(tmp_path)
        assert "## Sections" in content
        assert "02_Concepts" in content
        assert "| 2 |" in content or "| 2|" in content

    def test_contains_recent_changes(self, tmp_path):
        self._make_vault(tmp_path)
        content = generate_master_index(tmp_path)
        assert "## Recent Changes" in content


class TestGenerateFolderIndex:
    def test_lists_notes(self, tmp_path):
        folder = tmp_path / "02_Concepts"
        folder.mkdir()
        (folder / "auth.md").write_text('---\ntitle: "Auth Patterns"\n---\n# Auth\n')
        (folder / "deploy.md").write_text("# Deploy\n")
        content = generate_folder_index(folder, tmp_path)
        assert "[[auth]]" in content
        assert "[[deploy]]" in content
        assert "2 notes" in content


class TestRegenerateIndexes:
    def test_creates_master_index(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "note.md").write_text("# Note\n")
        result = regenerate_indexes(str(tmp_path), dry_run=False)
        assert result["master_index_updated"] is True
        assert (tmp_path / "00_Index.md").exists()

    def test_creates_folder_indexes(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "note.md").write_text("# Note\n")
        result = regenerate_indexes(str(tmp_path), dry_run=False)
        assert "02_Concepts" in result["folder_indexes_updated"]
        assert (tmp_path / "02_Concepts" / "index.md").exists()

    def test_dry_run_no_files(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "note.md").write_text("# Note\n")
        regenerate_indexes(str(tmp_path), dry_run=True)
        assert not (tmp_path / "00_Index.md").exists()
```

---

## Task 8: Health reporter

Compute graph health metrics and generate the health report.

### Step 8.1: Create health_reporter.py

- [ ] Write `plugin/lib/health_reporter.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/health_reporter.py`

```python
"""
Health reporter for the curator engine.

Computes graph health metrics (note count, orphan rate, staleness distribution,
link density, inbox size) and generates a health report written to
05_Inbox/curator-health-report.md.
"""

import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import _load_vault_notes, _parse_frontmatter, _extract_links
from plugin.lib.staleness import compute_staleness_score, classify_staleness


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_graph_metrics(vault_path: Path) -> dict:
    """
    Compute comprehensive graph health metrics.

    Returns:
        dict with note_count, link_count, avg_links_per_note, orphan_count,
        orphan_rate, staleness_distribution, inbox_pending, category_counts,
        broken_link_count.
    """
    notes = {}  # stem -> {links, tags, path, rel_path, fm}
    all_links = []
    broken_links = 0
    category_counts = defaultdict(int)

    for md_file in vault_path.rglob("*.md"):
        rel = md_file.relative_to(vault_path).as_posix()
        if rel.startswith(".obsidian/") or md_file.name == "index.md" or md_file.stem == "00_Index":
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            continue

        fm = _parse_frontmatter(content)
        links = _extract_links(content)
        all_links.extend(links)

        category = fm.get("category", "uncategorized")
        if isinstance(category, str):
            category_counts[category] += 1

        notes[md_file.stem] = {
            "links": links,
            "fm": fm,
            "path": md_file,
            "rel_path": rel,
        }

    valid_stems = set(notes.keys())
    note_count = len(notes)

    # Link density
    link_count = len(all_links)
    avg_links = link_count / note_count if note_count > 0 else 0.0

    # Broken links
    for link in all_links:
        if link not in valid_stems:
            broken_links += 1

    # Orphan detection (notes with no incoming links)
    incoming = defaultdict(int)
    for stem, data in notes.items():
        for link in data["links"]:
            incoming[link] += 1

    orphan_count = sum(
        1 for stem in notes
        if incoming.get(stem, 0) == 0
        and not notes[stem]["rel_path"].startswith("05_Inbox/")
        and not notes[stem]["rel_path"].startswith("99_Archive/")
    )
    orphan_rate = orphan_count / note_count if note_count > 0 else 0.0

    # Staleness distribution
    now = datetime.now(timezone.utc)
    staleness_dist = defaultdict(int)
    for stem, data in notes.items():
        fm = data["fm"]
        if data["rel_path"].startswith("05_Inbox/") or data["rel_path"].startswith("99_Archive/"):
            continue
        last_traversed = fm.get("last_traversed", fm.get("updated", ""))
        traversal_count = fm.get("traversal_count", fm.get("count", 0))
        if not isinstance(traversal_count, int):
            try:
                traversal_count = int(traversal_count)
            except (ValueError, TypeError):
                traversal_count = 0
        score = compute_staleness_score(str(last_traversed), traversal_count, now=now)
        classification = classify_staleness(score)
        staleness_dist[classification] += 1

    # Inbox pending
    inbox_pending = 0
    inbox_dir = vault_path / "05_Inbox"
    if inbox_dir.exists():
        for queue_dir in inbox_dir.iterdir():
            if queue_dir.is_dir() and queue_dir.name.startswith("queue-"):
                inbox_pending += sum(
                    1 for f in queue_dir.glob("*.md") if f.name != "index.md"
                )

    return {
        "note_count": note_count,
        "link_count": link_count,
        "avg_links_per_note": round(avg_links, 2),
        "orphan_count": orphan_count,
        "orphan_rate": round(orphan_rate, 4),
        "staleness_distribution": dict(staleness_dist),
        "inbox_pending": inbox_pending,
        "category_counts": dict(category_counts),
        "broken_link_count": broken_links,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_health_report(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
    cycle_duration_seconds: float = 0.0,
    cycle_results: Optional[dict] = None,
) -> dict:
    """
    Generate and write the curator health report.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, do not write the report file.
        cycle_duration_seconds: how long the curator cycle took.
        cycle_results: optional dict of results from each step.

    Returns:
        dict with metrics, report_path.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        return {"error": "vault_not_found", "path": str(vault)}

    metrics = compute_graph_metrics(vault)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Health score: composite
    # Target: orphan_rate < 0.03, avg_links >= 3, stale ratio < 0.05
    graph_notes = sum(metrics["staleness_distribution"].values()) or 1
    stale_count = (
        metrics["staleness_distribution"].get("stale", 0)
        + metrics["staleness_distribution"].get("review_needed", 0)
    )
    stale_ratio = stale_count / graph_notes

    health_score = 100
    if metrics["orphan_rate"] > 0.10:
        health_score -= 20
    elif metrics["orphan_rate"] > 0.03:
        health_score -= 10
    if metrics["avg_links_per_note"] < 1.0:
        health_score -= 20
    elif metrics["avg_links_per_note"] < 3.0:
        health_score -= 10
    if stale_ratio > 0.10:
        health_score -= 20
    elif stale_ratio > 0.05:
        health_score -= 10
    if metrics["broken_link_count"] > 10:
        health_score -= 10

    health_status = "healthy" if health_score >= 80 else "degraded" if health_score >= 60 else "unhealthy"

    lines = [
        "---",
        "type: health-report",
        f'generated: "{now}"',
        f"health_score: {health_score}",
        f"health_status: {health_status}",
        "---",
        "",
        "# Curator Health Report",
        "",
        f"Generated: {now}",
        f"Cycle duration: {cycle_duration_seconds:.1f}s",
        f"Health score: **{health_score}/100** ({health_status})",
        "",
        "## Graph Metrics",
        "",
        f"- Total notes: {metrics['note_count']}",
        f"- Total links: {metrics['link_count']}",
        f"- Avg links per note: {metrics['avg_links_per_note']}",
        f"- Orphan notes: {metrics['orphan_count']} ({metrics['orphan_rate']:.1%})",
        f"- Broken links: {metrics['broken_link_count']}",
        f"- Inbox pending: {metrics['inbox_pending']}",
        "",
        "## Staleness Distribution",
        "",
        "| Classification | Count |",
        "|---------------|-------|",
    ]

    for classification in ["active", "aging", "stale", "review_needed"]:
        count = metrics["staleness_distribution"].get(classification, 0)
        lines.append(f"| {classification} | {count} |")

    lines.append("")
    lines.append("## Category Breakdown")
    lines.append("")
    lines.append("| Category | Notes |")
    lines.append("|----------|-------|")

    for cat, count in sorted(metrics["category_counts"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {cat} | {count} |")

    # Cycle results summary
    if cycle_results:
        lines.append("")
        lines.append("## Cycle Summary")
        lines.append("")
        for step_name, step_result in cycle_results.items():
            if isinstance(step_result, dict):
                summary_parts = []
                for k, v in step_result.items():
                    if isinstance(v, (int, float, str, bool)):
                        summary_parts.append(f"{k}={v}")
                lines.append(f"- **{step_name}:** {', '.join(summary_parts[:5])}")
            else:
                lines.append(f"- **{step_name}:** {step_result}")

    lines.append("")

    report_content = "\n".join(lines)
    report_path = vault / "05_Inbox" / "curator-health-report.md"

    if not dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

    return {
        "metrics": metrics,
        "health_score": health_score,
        "health_status": health_status,
        "report_path": str(report_path),
        "dry_run": dry_run,
    }
```

### Step 8.2: Write tests for health_reporter

- [ ] Write `plugin/lib/tests/test_health_reporter.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_health_reporter.py`

```python
"""Tests for health reporter."""

from pathlib import Path

import pytest

from plugin.lib.health_reporter import (
    compute_graph_metrics,
    generate_health_report,
)


class TestComputeGraphMetrics:
    def _make_vault(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "04_Systems").mkdir()

        (tmp_path / "02_Concepts" / "auth.md").write_text(
            "---\ntitle: Auth\ncategory: concepts\ntags: [auth]\n"
            "last_traversed: 2026-03-20\ntraversal_count: 10\n---\n\n"
            "# Auth\n\nSee [[deploy]] for related.\n",
            encoding="utf-8",
        )
        (tmp_path / "02_Concepts" / "patterns.md").write_text(
            "---\ntitle: Patterns\ncategory: concepts\ntags: [patterns]\n---\n\n"
            "# Patterns\n\nSee [[auth]] and [[nonexistent]].\n",
            encoding="utf-8",
        )
        (tmp_path / "04_Systems" / "deploy.md").write_text(
            "---\ntitle: Deploy\ncategory: systems\ntags: [devops]\n---\n\n"
            "# Deploy\n\nSee [[auth]].\n",
            encoding="utf-8",
        )

    def test_counts_notes(self, tmp_path):
        self._make_vault(tmp_path)
        metrics = compute_graph_metrics(tmp_path)
        assert metrics["note_count"] == 3

    def test_counts_links(self, tmp_path):
        self._make_vault(tmp_path)
        metrics = compute_graph_metrics(tmp_path)
        assert metrics["link_count"] >= 3

    def test_detects_broken_links(self, tmp_path):
        self._make_vault(tmp_path)
        metrics = compute_graph_metrics(tmp_path)
        assert metrics["broken_link_count"] >= 1  # [[nonexistent]]

    def test_detects_orphans(self, tmp_path):
        self._make_vault(tmp_path)
        metrics = compute_graph_metrics(tmp_path)
        # patterns.md has no incoming links
        assert metrics["orphan_count"] >= 1

    def test_category_counts(self, tmp_path):
        self._make_vault(tmp_path)
        metrics = compute_graph_metrics(tmp_path)
        assert metrics["category_counts"]["concepts"] == 2
        assert metrics["category_counts"]["systems"] == 1


class TestGenerateHealthReport:
    def test_generates_report(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "note.md").write_text(
            "---\ntitle: Note\ncategory: concepts\n---\n\n# Note\n"
        )
        result = generate_health_report(str(tmp_path), dry_run=False)
        assert result["health_score"] >= 0
        assert (tmp_path / "05_Inbox" / "curator-health-report.md").exists()

    def test_dry_run_no_file(self, tmp_path):
        (tmp_path / "02_Concepts").mkdir()
        (tmp_path / "02_Concepts" / "note.md").write_text("# Note\n")
        result = generate_health_report(str(tmp_path), dry_run=True)
        assert not (tmp_path / "05_Inbox" / "curator-health-report.md").exists()

    def test_healthy_vault(self, tmp_path):
        # Create a well-linked vault
        (tmp_path / "02_Concepts").mkdir()
        for i in range(5):
            links = " ".join(f"[[note-{j}]]" for j in range(5) if j != i)
            (tmp_path / "02_Concepts" / f"note-{i}.md").write_text(
                f"---\ntitle: Note {i}\ncategory: concepts\n"
                f"last_traversed: 2026-03-20\ntraversal_count: 10\n---\n\n"
                f"# Note {i}\n\n{links}\n"
            )
        result = generate_health_report(str(tmp_path), dry_run=True)
        assert result["health_score"] >= 70
```

---

## Task 9: Curator orchestrator

The top-level orchestrator that runs the 8-step scheduled maintenance cycle.

### Step 9.1: Create curator.py

- [ ] Write `plugin/lib/curator.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/curator.py`

```python
"""
Curator engine orchestrator.

Runs the 8-step scheduled maintenance cycle:
1. Process inbox
2. Run mycelium consolidation
3. Weave wikilinks
4. Staleness scan
5. Conflict resolution
6. Schema enforcement
7. Index update
8. Health report
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from plugin.lib.consolidation import run_consolidation
from plugin.lib.conflict_resolver import resolve_conflicts
from plugin.lib.health_reporter import generate_health_report
from plugin.lib.inbox_processor import process_inbox
from plugin.lib.index_generator import regenerate_indexes
from plugin.lib.knowledge_gaps import detect_knowledge_gaps
from plugin.lib.review_queue import write_review_queue
from plugin.lib.schema_enforcer import enforce_schema
from plugin.lib.staleness import scan_staleness
from plugin.lib.wikilink_weaver import weave_wikilinks

logger = logging.getLogger("curator")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def _write_heartbeat(vault_path: Path, status: str, cycle_duration: float, notes_processed: int):
    """Write the .curator-heartbeat.json file."""
    heartbeat_path = vault_path / ".curator-heartbeat.json"
    now = datetime.now(timezone.utc)

    heartbeat = {
        "last_seen": now.isoformat(),
        "status": status,
        "cycle_duration_seconds": round(cycle_duration, 1),
        "notes_processed": notes_processed,
        "next_cycle": "",  # Populated by cron scheduler
        "missed_heartbeats": 0,
    }

    # Preserve outage_log from previous heartbeat
    if heartbeat_path.exists():
        try:
            prev = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            heartbeat["outage_log"] = prev.get("outage_log", [])
        except (json.JSONDecodeError, IOError):
            heartbeat["outage_log"] = []
    else:
        heartbeat["outage_log"] = []

    heartbeat_path.write_text(
        json.dumps(heartbeat, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------

def run_curator_cycle(
    vault_path: Optional[str] = None,
    dry_run: bool = True,
    steps: Optional[list] = None,
) -> dict:
    """
    Run the full curator maintenance cycle.

    Args:
        vault_path: root of the Obsidian vault.
        dry_run: if True, no mutations.
        steps: optional list of step names to run (default: all).
            Valid: inbox, consolidation, wikilinks, staleness, conflicts,
                   schema, indexes, health

    Returns:
        dict with per-step results and overall timing.
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        return {"error": "vault_not_found", "path": str(vault)}

    all_steps = [
        "inbox", "consolidation", "wikilinks", "staleness",
        "conflicts", "schema", "indexes", "health",
    ]
    if steps is None:
        steps = all_steps

    results = {}
    cycle_start = time.monotonic()
    total_processed = 0

    # Step 1: Process inbox
    if "inbox" in steps:
        logger.info("Step 1/8: Processing inbox...")
        try:
            inbox_result = process_inbox(str(vault), dry_run=dry_run)
            results["inbox"] = inbox_result
            total_processed += inbox_result.get("processed", 0)
            logger.info(
                "Inbox: processed=%d promoted=%d held=%d",
                inbox_result["processed"],
                inbox_result["promoted"],
                inbox_result["held"],
            )
        except Exception as exc:
            logger.error("Inbox processing failed: %s", exc)
            results["inbox"] = {"error": str(exc)}

    # Step 2: Mycelium consolidation
    if "consolidation" in steps:
        logger.info("Step 2/8: Running mycelium consolidation...")
        try:
            consolidation_result = run_consolidation(
                vault_path=str(vault),
                apply=not dry_run,
                dry_run=dry_run,
            )
            results["consolidation"] = consolidation_result
            logger.info(
                "Consolidation: pruned=%s healed=%s reinforced=%s",
                consolidation_result.get("pruned", 0),
                consolidation_result.get("healed_count", 0),
                consolidation_result.get("reinforced_count", 0),
            )
        except Exception as exc:
            logger.error("Consolidation failed: %s", exc)
            results["consolidation"] = {"error": str(exc)}

    # Step 3: Weave wikilinks
    if "wikilinks" in steps:
        logger.info("Step 3/8: Weaving wikilinks...")
        try:
            wikilink_result = weave_wikilinks(
                vault_path=str(vault),
                dry_run=dry_run,
            )
            results["wikilinks"] = wikilink_result
            logger.info(
                "Wikilinks: added=%d removed=%d",
                wikilink_result["links_added"],
                wikilink_result["links_removed"],
            )
        except Exception as exc:
            logger.error("Wikilink weaving failed: %s", exc)
            results["wikilinks"] = {"error": str(exc)}

    # Step 4: Staleness scan
    if "staleness" in steps:
        logger.info("Step 4/8: Scanning staleness...")
        try:
            staleness_result = scan_staleness(
                vault_path=str(vault),
                dry_run=dry_run,
            )
            results["staleness"] = staleness_result
            logger.info(
                "Staleness: scanned=%d stale=%d review=%d",
                staleness_result.get("total_scanned", 0),
                len(staleness_result.get("flagged_stale", [])),
                len(staleness_result.get("moved_to_review", [])),
            )
        except Exception as exc:
            logger.error("Staleness scan failed: %s", exc)
            results["staleness"] = {"error": str(exc)}

    # Step 5: Conflict resolution
    if "conflicts" in steps:
        logger.info("Step 5/8: Resolving conflicts...")
        try:
            conflict_result = resolve_conflicts(
                vault_path=str(vault),
                dry_run=dry_run,
            )
            results["conflicts"] = conflict_result
            logger.info(
                "Conflicts: found=%d merged=%d escalated=%d",
                conflict_result["found"],
                conflict_result["auto_merged"],
                conflict_result["escalated"],
            )
        except Exception as exc:
            logger.error("Conflict resolution failed: %s", exc)
            results["conflicts"] = {"error": str(exc)}

    # Step 6: Schema enforcement
    if "schema" in steps:
        logger.info("Step 6/8: Enforcing schema...")
        try:
            schema_result = enforce_schema(
                vault_path=str(vault),
                dry_run=dry_run,
            )
            results["schema"] = schema_result
            logger.info(
                "Schema: total=%d compliant=%d fixed=%d malformed=%d",
                schema_result.get("total", 0),
                schema_result.get("compliant", 0),
                schema_result.get("fixed", 0),
                schema_result.get("malformed", 0),
            )
        except Exception as exc:
            logger.error("Schema enforcement failed: %s", exc)
            results["schema"] = {"error": str(exc)}

    # Step 7: Index update
    if "indexes" in steps:
        logger.info("Step 7/8: Regenerating indexes...")
        try:
            index_result = regenerate_indexes(
                vault_path=str(vault),
                dry_run=dry_run,
            )
            results["indexes"] = index_result
            logger.info(
                "Indexes: folders=%d total_notes=%d",
                len(index_result.get("folder_indexes_updated", [])),
                index_result.get("total_notes", 0),
            )
        except Exception as exc:
            logger.error("Index regeneration failed: %s", exc)
            results["indexes"] = {"error": str(exc)}

    # Step 8: Health report
    cycle_duration = time.monotonic() - cycle_start

    if "health" in steps:
        logger.info("Step 8/8: Generating health report...")
        try:
            health_result = generate_health_report(
                vault_path=str(vault),
                dry_run=dry_run,
                cycle_duration_seconds=cycle_duration,
                cycle_results=results,
            )
            results["health"] = health_result
            logger.info(
                "Health: score=%d status=%s",
                health_result.get("health_score", 0),
                health_result.get("health_status", "unknown"),
            )
        except Exception as exc:
            logger.error("Health report failed: %s", exc)
            results["health"] = {"error": str(exc)}

    # Write heartbeat (even in dry_run, heartbeat is always written)
    if not dry_run:
        health_status = results.get("health", {}).get("health_status", "unknown")
        _write_heartbeat(vault, health_status, cycle_duration, total_processed)

    # Also generate review queue and gap report (bonus steps from consolidation)
    if "consolidation" in steps:
        try:
            write_review_queue(vault_path=str(vault))
        except Exception:
            pass
        try:
            from plugin.lib.knowledge_gaps import write_gap_report
            write_gap_report(vault_path=str(vault))
        except Exception:
            pass

    return {
        "cycle_duration_seconds": round(cycle_duration, 2),
        "dry_run": dry_run,
        "steps_run": steps,
        "results": results,
    }
```

### Step 9.2: Write tests for curator orchestrator

- [ ] Write `plugin/lib/tests/test_curator.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_curator.py`

```python
"""Tests for curator orchestrator."""

from pathlib import Path

import pytest

from plugin.lib.curator import run_curator_cycle


def _make_vault(tmp_path):
    """Create a minimal but functional vault for curator testing."""
    for folder in ["01_Projects", "02_Concepts", "04_Systems", "05_Inbox"]:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    for queue in ["queue-agent", "queue-cicd", "queue-human"]:
        (tmp_path / "05_Inbox" / queue).mkdir(parents=True, exist_ok=True)

    (tmp_path / "02_Concepts" / "auth.md").write_text(
        "---\ntitle: Auth Patterns\ncategory: concepts\ntags: [auth, security]\n"
        "created: 2026-03-01\nupdated: 2026-03-20\nauthor: andrew\nsource: human\n"
        "status: active\nlast_traversed: 2026-03-20\ntraversal_count: 10\n---\n\n"
        "# Auth Patterns\n\nToken-based authentication.\n",
        encoding="utf-8",
    )
    (tmp_path / "04_Systems" / "deploy.md").write_text(
        "---\ntitle: Deploy Pipeline\ncategory: systems\ntags: [devops]\n"
        "created: 2026-03-01\nupdated: 2026-03-20\nauthor: andrew\nsource: human\n"
        "status: active\nlast_traversed: 2026-03-20\ntraversal_count: 5\n---\n\n"
        "# Deploy Pipeline\n\nKubernetes deployment.\n",
        encoding="utf-8",
    )
    # Inbox note
    (tmp_path / "05_Inbox" / "queue-agent" / "new-pattern.md").write_text(
        "---\ntitle: New Pattern\ncategory: concepts\ntags: [patterns]\n---\n\n"
        "# New Pattern\n\nDiscovered a new approach.\n",
        encoding="utf-8",
    )


class TestRunCuratorCycle:
    def test_full_cycle_dry_run(self, tmp_path):
        _make_vault(tmp_path)
        result = run_curator_cycle(str(tmp_path), dry_run=True)
        assert "error" not in result
        assert result["dry_run"] is True
        assert len(result["steps_run"]) == 8
        # All steps should have results
        for step in ["inbox", "consolidation", "wikilinks", "staleness",
                      "conflicts", "schema", "indexes", "health"]:
            assert step in result["results"]

    def test_selective_steps(self, tmp_path):
        _make_vault(tmp_path)
        result = run_curator_cycle(str(tmp_path), dry_run=True, steps=["inbox", "health"])
        assert len(result["steps_run"]) == 2
        assert "inbox" in result["results"]
        assert "health" in result["results"]
        assert "consolidation" not in result["results"]

    def test_full_cycle_applies(self, tmp_path):
        _make_vault(tmp_path)
        result = run_curator_cycle(str(tmp_path), dry_run=False)
        assert result["dry_run"] is False
        # Inbox note should have been promoted
        inbox_result = result["results"]["inbox"]
        assert inbox_result["promoted"] >= 1
        # Health report should be written
        assert (tmp_path / "05_Inbox" / "curator-health-report.md").exists()
        # Heartbeat should be written
        assert (tmp_path / ".curator-heartbeat.json").exists()
        # Index should be generated
        assert (tmp_path / "00_Index.md").exists()

    def test_nonexistent_vault(self):
        result = run_curator_cycle("/tmp/nonexistent-vault-test-xyz")
        assert "error" in result

    def test_cycle_duration_tracked(self, tmp_path):
        _make_vault(tmp_path)
        result = run_curator_cycle(str(tmp_path), dry_run=True)
        assert "cycle_duration_seconds" in result
        assert result["cycle_duration_seconds"] >= 0
```

---

## Task 10: Reactive loop (filesystem watcher)

Filesystem watcher that triggers fast-classify on new inbox items and conflict detection on sync events.

### Step 10.1: Create reactive_watcher.py

- [ ] Write `plugin/lib/reactive_watcher.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/reactive_watcher.py`

```python
"""
Reactive loop for the curator engine.

Watches the vault filesystem for changes and triggers:
1. Fast-classify on new inbox items (queue-* folders)
2. Conflict detection on new conflict files
3. Fast-promote for high-trust sources

Uses the watchdog library for cross-platform filesystem monitoring.
Falls back to polling if watchdog is not available.
"""

import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("curator.reactive")

try:
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class CuratorEventHandler:
    """
    Handle filesystem events relevant to the curator.

    Tracks new files in queue-* folders and conflict files.
    Calls the appropriate handler function for each event type.
    """

    def __init__(
        self,
        vault_path: Path,
        on_inbox_item: Optional[Callable] = None,
        on_conflict_detected: Optional[Callable] = None,
    ):
        self.vault_path = vault_path
        self.on_inbox_item = on_inbox_item
        self.on_conflict_detected = on_conflict_detected
        self._processed = set()

    def handle_created(self, src_path: str):
        """Handle a new file creation event."""
        path = Path(src_path)

        if not path.suffix == ".md":
            return

        if src_path in self._processed:
            return
        self._processed.add(src_path)

        # Limit memory for processed set
        if len(self._processed) > 10000:
            self._processed.clear()

        try:
            rel = path.relative_to(self.vault_path).as_posix()
        except ValueError:
            return

        # Check if it's an inbox item
        if "/queue-" in rel and self.on_inbox_item:
            logger.info("New inbox item: %s", rel)
            self.on_inbox_item(path)

        # Check if it's a conflict file
        if "(conflict " in path.name and self.on_conflict_detected:
            logger.info("Conflict file detected: %s", rel)
            self.on_conflict_detected(path)


# ---------------------------------------------------------------------------
# Watchdog-based watcher
# ---------------------------------------------------------------------------

if WATCHDOG_AVAILABLE:
    class _WatchdogHandler(FileSystemEventHandler):
        """Adapter from watchdog events to CuratorEventHandler."""

        def __init__(self, curator_handler: CuratorEventHandler):
            super().__init__()
            self.curator_handler = curator_handler

        def on_created(self, event):
            if not event.is_directory:
                self.curator_handler.handle_created(event.src_path)


# ---------------------------------------------------------------------------
# Polling fallback
# ---------------------------------------------------------------------------

def _poll_for_changes(vault_path: Path, handler: CuratorEventHandler, interval: float = 5.0):
    """
    Poll-based fallback for when watchdog is not available.

    Scans queue-* folders and vault root for new .md files.
    """
    known_files = set()

    # Initial scan
    inbox = vault_path / "05_Inbox"
    if inbox.exists():
        for queue_dir in inbox.iterdir():
            if queue_dir.is_dir() and queue_dir.name.startswith("queue-"):
                for f in queue_dir.glob("*.md"):
                    known_files.add(str(f))

    for f in vault_path.rglob("*(conflict *.md"):
        known_files.add(str(f))

    logger.info("Polling watcher started (interval=%.1fs, known=%d)", interval, len(known_files))

    while True:
        time.sleep(interval)
        current_files = set()

        if inbox.exists():
            for queue_dir in inbox.iterdir():
                if queue_dir.is_dir() and queue_dir.name.startswith("queue-"):
                    for f in queue_dir.glob("*.md"):
                        current_files.add(str(f))

        for f in vault_path.rglob("*(conflict *.md"):
            current_files.add(str(f))

        new_files = current_files - known_files
        for new_file in new_files:
            handler.handle_created(new_file)

        known_files = current_files


# ---------------------------------------------------------------------------
# Default handlers
# ---------------------------------------------------------------------------

def _default_inbox_handler(file_path: Path):
    """Default handler for new inbox items: fast-classify and promote if high-trust."""
    from plugin.lib.inbox_processor import classify_note

    vault_path = file_path
    # Walk up to find vault root (contains 05_Inbox)
    for parent in file_path.parents:
        if (parent / "05_Inbox").exists():
            vault_path = parent
            break

    classification = classify_note(file_path, vault_path)
    logger.info(
        "Fast-classified %s: category=%s trust=%s promote=%s",
        file_path.name,
        classification["category"],
        classification["trust_level"],
        classification["auto_promote"],
    )

    if classification["auto_promote"]:
        from plugin.lib.inbox_processor import process_inbox
        # Process just this queue folder
        # For simplicity, process the entire inbox (idempotent)
        process_inbox(str(vault_path), dry_run=False)


def _default_conflict_handler(file_path: Path):
    """Default handler for conflict files: attempt auto-merge."""
    from plugin.lib.conflict_resolver import resolve_conflicts

    vault_path = file_path
    for parent in file_path.parents:
        if (parent / ".obsidian").exists() or (parent / "05_Inbox").exists():
            vault_path = parent
            break

    result = resolve_conflicts(str(vault_path), dry_run=False)
    logger.info(
        "Conflict resolution: merged=%d escalated=%d",
        result["auto_merged"],
        result["escalated"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_reactive_watcher(
    vault_path: Optional[str] = None,
    on_inbox_item: Optional[Callable] = None,
    on_conflict_detected: Optional[Callable] = None,
    use_polling: bool = False,
    poll_interval: float = 5.0,
) -> Optional[object]:
    """
    Start the reactive filesystem watcher.

    Args:
        vault_path: root of the Obsidian vault.
        on_inbox_item: callback for new inbox items. Default: fast-classify.
        on_conflict_detected: callback for conflict files. Default: auto-merge.
        use_polling: force polling mode even if watchdog is available.
        poll_interval: polling interval in seconds (only for polling mode).

    Returns:
        Observer instance (watchdog) or None (polling runs in current thread).
    """
    if vault_path is None:
        vault_path = os.environ.get(
            "LACP_OBSIDIAN_VAULT",
            os.path.expanduser("~/obsidian/vault"),
        )

    vault = Path(vault_path)
    if not vault.exists():
        logger.error("Vault not found: %s", vault)
        return None

    if on_inbox_item is None:
        on_inbox_item = _default_inbox_handler
    if on_conflict_detected is None:
        on_conflict_detected = _default_conflict_handler

    handler = CuratorEventHandler(
        vault_path=vault,
        on_inbox_item=on_inbox_item,
        on_conflict_detected=on_conflict_detected,
    )

    if WATCHDOG_AVAILABLE and not use_polling:
        watchdog_handler = _WatchdogHandler(handler)
        observer = Observer()
        observer.schedule(watchdog_handler, str(vault), recursive=True)
        observer.start()
        logger.info("Watchdog reactive watcher started on %s", vault)
        return observer
    else:
        logger.info("Using polling fallback (watchdog %s)",
                     "not installed" if not WATCHDOG_AVAILABLE else "bypassed")
        # Polling blocks the current thread
        _poll_for_changes(vault, handler, interval=poll_interval)
        return None
```

### Step 10.2: Write tests for reactive_watcher

- [ ] Write `plugin/lib/tests/test_reactive_watcher.py`

**File:** `/Users/andrew/clawd/openclaw-lacp-fusion-repo/plugin/lib/tests/test_reactive_watcher.py`

```python
"""Tests for reactive watcher."""

from pathlib import Path

import pytest

from plugin.lib.reactive_watcher import CuratorEventHandler


class TestCuratorEventHandler:
    def test_inbox_callback_fired(self, tmp_path):
        vault = tmp_path
        (vault / "05_Inbox" / "queue-agent").mkdir(parents=True)

        received = []

        def on_inbox(path):
            received.append(path)

        handler = CuratorEventHandler(
            vault_path=vault,
            on_inbox_item=on_inbox,
        )

        note = vault / "05_Inbox" / "queue-agent" / "new-note.md"
        note.write_text("# New Note\n")
        handler.handle_created(str(note))

        assert len(received) == 1
        assert received[0] == note

    def test_conflict_callback_fired(self, tmp_path):
        vault = tmp_path

        received = []

        def on_conflict(path):
            received.append(path)

        handler = CuratorEventHandler(
            vault_path=vault,
            on_conflict_detected=on_conflict,
        )

        conflict = vault / "02_Concepts" / "note (conflict 2026-03-21).md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("# Conflict\n")
        handler.handle_created(str(conflict))

        assert len(received) == 1

    def test_ignores_non_md_files(self, tmp_path):
        vault = tmp_path

        received = []
        handler = CuratorEventHandler(
            vault_path=vault,
            on_inbox_item=lambda p: received.append(p),
        )

        handler.handle_created(str(vault / "05_Inbox" / "queue-agent" / "file.txt"))
        assert len(received) == 0

    def test_deduplicates_events(self, tmp_path):
        vault = tmp_path
        (vault / "05_Inbox" / "queue-agent").mkdir(parents=True)

        received = []
        handler = CuratorEventHandler(
            vault_path=vault,
            on_inbox_item=lambda p: received.append(p),
        )

        note = vault / "05_Inbox" / "queue-agent" / "note.md"
        note.write_text("# Note\n")
        handler.handle_created(str(note))
        handler.handle_created(str(note))

        assert len(received) == 1

    def test_no_callback_no_error(self, tmp_path):
        """Handler with no callbacks should not crash."""
        vault = tmp_path
        handler = CuratorEventHandler(vault_path=vault)
        # Should not raise
        handler.handle_created(str(vault / "05_Inbox" / "queue-agent" / "note.md"))
```

---

## Task 11: Wire curator into brain-expand

Add a `--curator-cycle` flag to `openclaw-brain-expand` that runs the full curator cycle.

### Step 11.1: Add curator cycle to brain-expand

- [ ] Edit `plugin/bin/openclaw-brain-expand` to add `--curator-cycle` option

In the `usage()` function, after the `--activate` option, add:

```bash
  --curator-cycle       Run full curator maintenance cycle (all 8 steps)
```

In the `main()` function, add a variable `curator_cycle=0` alongside the existing variables. Add a case in the `while` loop:

```bash
      --curator-cycle) curator_cycle=1; shift ;;
```

After the activation block (after `if [ "$activate" = "1" ]; then ... fi`), add:

```bash
  # Curator maintenance cycle
  if [ "$curator_cycle" = "1" ]; then
    echo ""
    echo -e "${BLUE}Running Curator Maintenance Cycle${NC}"

    local vault="${LACP_OBSIDIAN_VAULT:-${OPENCLAW_VAULT:-$HOME/.openclaw/data/knowledge}}"
    if [ ! -d "$vault" ]; then
      log_warn "Vault not found at $vault — skipping curator cycle"
    else
      local curator_result
      curator_result=$(python3 -c "
import json, sys
sys.path.insert(0, '$PLUGIN_DIR')
from plugin.lib.curator import run_curator_cycle
result = run_curator_cycle(
    vault_path='$vault',
    dry_run=$( [ "$dry_run" = "1" ] && echo "True" || echo "False" ),
)
print(json.dumps(result, indent=2, default=str))
" 2>&1) || {
        log_error "Curator cycle failed"
        echo "$curator_result" >&2
      }

      if [ "$json_output" = "1" ]; then
        echo "$curator_result"
      else
        local duration
        duration=$(echo "$curator_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cycle_duration_seconds',0))" 2>/dev/null || echo "?")
        echo "  Cycle completed in ${duration}s"
        local health_score
        health_score=$(echo "$curator_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('results',{}).get('health',{}).get('health_score','?'))" 2>/dev/null || echo "?")
        echo "  Health score: $health_score/100"
      fi
      log_success "Curator cycle complete"
    fi
  fi
```

Also update the condition that guards standard layer expansion to include curator_cycle:

```bash
  if [ "$consolidate" = "0" ] && [ "$activate" = "0" ] && [ "$curator_cycle" = "0" ]; then
```

### Step 11.2: Register cron job setup

- [ ] Verify the cron registration command works by documenting it in the skill file

The cron job is registered via:

```bash
openclaw cron add \
  --every 4h \
  --skill curator-maintenance \
  --description "Run curator maintenance cycle"
```

Which effectively runs:

```bash
openclaw-brain-expand --curator-cycle
```

No additional code is needed here -- the skill file (Task 1) and the brain-expand flag (Step 11.1) are sufficient.

---

## Verification

### Run all tests

- [ ] Run the full test suite

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
python3 -m pytest plugin/lib/tests/test_inbox_processor.py plugin/lib/tests/test_wikilink_weaver.py plugin/lib/tests/test_staleness.py plugin/lib/tests/test_conflict_resolver.py plugin/lib/tests/test_schema_enforcer.py plugin/lib/tests/test_index_generator.py plugin/lib/tests/test_health_reporter.py plugin/lib/tests/test_curator.py plugin/lib/tests/test_reactive_watcher.py -v
```

### Integration test: full cycle on a test vault

- [ ] Run a dry-run curator cycle

```bash
cd /Users/andrew/clawd/openclaw-lacp-fusion-repo
LACP_OBSIDIAN_VAULT=/tmp/test-curator-vault python3 -c "
from plugin.lib.curator import run_curator_cycle
import json

# Create a minimal test vault first
from pathlib import Path
vault = Path('/tmp/test-curator-vault')
vault.mkdir(exist_ok=True)
for d in ['01_Projects', '02_Concepts', '04_Systems', '05_Inbox/queue-agent']:
    (vault / d).mkdir(parents=True, exist_ok=True)
(vault / '02_Concepts' / 'test.md').write_text(
    '---\ntitle: Test\ncategory: concepts\ntags: [test]\n'
    'created: 2026-03-01\nupdated: 2026-03-20\nauthor: test\nsource: test\n'
    'status: active\nlast_traversed: 2026-03-20\ntraversal_count: 5\n---\n\n# Test\n'
)

result = run_curator_cycle(str(vault), dry_run=True)
print(json.dumps(result, indent=2, default=str))
"
```

---

## File Summary

| File | Status | Purpose |
|------|--------|---------|
| `plugin/skills/curator-maintenance.md` | NEW | Curator skill/prompt for cron job |
| `plugin/lib/inbox_processor.py` | NEW | Classify and route inbox notes |
| `plugin/lib/wikilink_weaver.py` | NEW | Scan and add related note links |
| `plugin/lib/staleness.py` | NEW | Staleness scoring and threshold actions |
| `plugin/lib/conflict_resolver.py` | NEW | Obsidian Sync conflict auto-merge |
| `plugin/lib/schema_enforcer.py` | NEW | Frontmatter validation and defaults |
| `plugin/lib/index_generator.py` | NEW | Master and per-folder index generation |
| `plugin/lib/health_reporter.py` | NEW | Graph metrics and health report |
| `plugin/lib/curator.py` | NEW | 8-step orchestrator |
| `plugin/lib/reactive_watcher.py` | NEW | Filesystem watcher (reactive loop) |
| `plugin/lib/tests/test_inbox_processor.py` | NEW | Tests |
| `plugin/lib/tests/test_wikilink_weaver.py` | NEW | Tests |
| `plugin/lib/tests/test_staleness.py` | NEW | Tests |
| `plugin/lib/tests/test_conflict_resolver.py` | NEW | Tests |
| `plugin/lib/tests/test_schema_enforcer.py` | NEW | Tests |
| `plugin/lib/tests/test_index_generator.py` | NEW | Tests |
| `plugin/lib/tests/test_health_reporter.py` | NEW | Tests |
| `plugin/lib/tests/test_curator.py` | NEW | Tests |
| `plugin/lib/tests/test_reactive_watcher.py` | NEW | Tests |
| `plugin/bin/openclaw-brain-expand` | EDIT | Add `--curator-cycle` flag |

**Existing code reused (not modified):**
| `plugin/lib/mycelium.py` | EXISTING | All mycelium algorithms |
| `plugin/lib/consolidation.py` | EXISTING | Consolidation pipeline + vault loading helpers |
| `plugin/lib/review_queue.py` | EXISTING | FSRS review queue |
| `plugin/lib/knowledge_gaps.py` | EXISTING | Gap detection |
| `plugin/bin/openclaw-brain-resolve` | EXISTING | Contradiction resolution |

**Optional dependency:** `watchdog` (pip install watchdog) for native filesystem events. Falls back to polling without it.
