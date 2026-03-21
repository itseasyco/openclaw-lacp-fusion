"""
Memory consolidation pipeline.

Implements the nightly consolidation process that:
1. Computes storage and retrieval strength for each note
2. Runs spreading activation from recently-traversed notes
3. Identifies pruning candidates (low S + low R)
4. Protects tendril nodes (frontier nodes in active categories)
5. Prunes low-value notes to archive
6. Heals broken paths after pruning
7. Reinforces recently-accessed paths
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from plugin.lib.mycelium import (
    compute_flow_score,
    compute_importance_score,
    compute_retrieval_strength,
    compute_storage_strength,
    heal_broken_paths,
    reinforce_access_paths,
    spreading_activation,
)


def _parse_frontmatter(content):
    """Extract YAML frontmatter from markdown content as a dict."""
    if not content.startswith('---'):
        return {}

    end = content.find('---', 3)
    if end == -1:
        return {}

    fm_text = content[3:end].strip()
    result = {}
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()
            # Strip quotes
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            # Try to parse as number
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except (ValueError, TypeError):
                pass
            # Parse lists (simple comma-separated in brackets)
            if isinstance(value, str) and value.startswith('[') and value.endswith(']'):
                value = [v.strip().strip('"').strip("'") for v in value[1:-1].split(',') if v.strip()]
            result[key] = value

    return result


def _extract_links(content):
    """Extract [[wikilinks]] from markdown content."""
    return re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)


def _load_vault_notes(vault_path):
    """
    Load all markdown notes from the vault.

    Returns:
        {note_id: {edges, count, last_seen, categories, embedding, storage_strength, ...}}
    """
    vault = Path(vault_path)
    items = {}

    if not vault.exists():
        return items

    for md_file in vault.rglob('*.md'):
        try:
            content = md_file.read_text(encoding='utf-8')
        except (IOError, UnicodeDecodeError):
            continue

        fm = _parse_frontmatter(content)
        note_id = md_file.stem
        links = _extract_links(content)

        # Build edges from wikilinks
        edges = [{'id': link, 'similarity': 0.5} for link in links]

        # Get metadata
        count = fm.get('count', fm.get('access_count', 1))
        if not isinstance(count, int):
            try:
                count = int(count)
            except (ValueError, TypeError):
                count = 1

        last_seen = fm.get('last_seen', fm.get('last_accessed', ''))
        if not last_seen:
            # Use file modification time
            mtime = md_file.stat().st_mtime
            last_seen = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        categories = fm.get('categories', fm.get('tags', []))
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(',')]

        storage_strength = fm.get('storage_strength', 0.0)
        if not isinstance(storage_strength, (int, float)):
            try:
                storage_strength = float(storage_strength)
            except (ValueError, TypeError):
                storage_strength = 0.0

        items[note_id] = {
            'edges': edges,
            'count': count,
            'last_seen': str(last_seen),
            'categories': categories if isinstance(categories, list) else [],
            'storage_strength': storage_strength,
            'path': str(md_file),
            'relative_path': str(md_file.relative_to(vault)),
        }

    return items


def _identify_hubs(items, min_edges=3):
    """Identify hub nodes (nodes with many connections)."""
    hubs = set()
    for node_id, data in items.items():
        if len(data.get('edges', [])) >= min_edges:
            hubs.add(node_id)
        if 'hub' in data.get('categories', []):
            hubs.add(node_id)
    return hubs


def _identify_tendrils(items, active_categories=None):
    """
    Identify tendril nodes — frontier nodes in active categories.

    Tendrils are recently-added nodes with few connections in categories
    that are actively being researched. They should be protected from pruning.
    """
    tendrils = set()
    if not active_categories:
        # Determine active categories from recent notes
        now = datetime.now(timezone.utc)
        cat_activity = {}
        for node_id, data in items.items():
            r = compute_retrieval_strength(data, edge_count=len(data.get('edges', [])))
            for cat in data.get('categories', []):
                if cat not in cat_activity:
                    cat_activity[cat] = 0.0
                cat_activity[cat] = max(cat_activity[cat], r)
        active_categories = {cat for cat, activity in cat_activity.items() if activity > 0.3}

    for node_id, data in items.items():
        cats = set(data.get('categories', []))
        if not cats.intersection(active_categories):
            continue
        # Tendril = few edges (frontier) + active category
        edge_count = len(data.get('edges', []))
        if edge_count <= 2:
            tendrils.add(node_id)

    return tendrils


def run_consolidation(vault_path=None, apply=False, dry_run=True, config=None):
    """
    Run the full memory consolidation pipeline.

    Args:
        vault_path: path to the Obsidian vault (or None for env default).
        apply: if True, actually move files to archive.
        dry_run: if True, only report what would be done.
        config: optional dict of thresholds.

    Returns:
        dict with consolidation results.
    """
    if config is None:
        config = {}

    # Defaults
    prune_r_threshold = config.get('prune_r_threshold', 0.1)
    prune_s_threshold = config.get('prune_s_threshold', 0.3)
    prune_edge_threshold = config.get('prune_edge_threshold', 0.5)
    max_prune_per_run = config.get('max_prune_per_run', 50)

    # Resolve vault path
    if vault_path is None:
        vault_path = os.environ.get('LACP_OBSIDIAN_VAULT', os.path.expanduser('~/obsidian/vault'))

    # Step 1: Load notes
    items = _load_vault_notes(vault_path)

    # Step 2: Compute strengths
    for node_id, data in items.items():
        edge_count = len(data.get('edges', []))
        data['storage_strength'] = compute_storage_strength(data)
        data['retrieval_strength'] = compute_retrieval_strength(data, edge_count=edge_count)
        data['importance_score'] = compute_importance_score(data, edge_count=edge_count)

    # Step 3: Spreading activation from recently accessed notes
    recent_seeds = {}
    for node_id, data in items.items():
        r = data.get('retrieval_strength', 0)
        if r > 0.7:
            recent_seeds[node_id] = r

    if recent_seeds:
        activations = spreading_activation(recent_seeds, items, alpha=0.7, max_hops=3)
        for node_id, act_val in activations.items():
            if node_id in items:
                items[node_id]['activation'] = act_val

    # Step 4: Identify prune candidates
    prune_candidates = []
    for node_id, data in items.items():
        s = data.get('storage_strength', 0)
        r = data.get('retrieval_strength', 0)
        if s < prune_s_threshold and r < prune_r_threshold:
            prune_candidates.append(node_id)

    # Step 5: Protect tendrils
    protected_tendrils = _identify_tendrils(items)
    prune_candidates = [n for n in prune_candidates if n not in protected_tendrils]

    # Limit pruning
    prune_candidates = prune_candidates[:max_prune_per_run]

    # Step 6: Prune (archive)
    pruned = set()
    if apply and not dry_run:
        archive_dir = Path(vault_path) / '99_Archive'
        archive_dir.mkdir(parents=True, exist_ok=True)
        for node_id in prune_candidates:
            src = Path(items[node_id].get('path', ''))
            if src.exists():
                dst = archive_dir / src.name
                src.rename(dst)
                pruned.add(node_id)
    else:
        pruned = set(prune_candidates)

    # Step 7: Heal broken paths
    hubs = _identify_hubs(items)
    heal_result = {'healed_count': 0}
    if pruned:
        heal_result = heal_broken_paths(pruned, items, hubs)

    # Step 8: Reinforce recently accessed paths
    reinforce_results = []
    for node_id in recent_seeds:
        if node_id not in pruned:
            result = reinforce_access_paths(node_id, items)
            reinforce_results.append(result)

    total_reinforced = sum(r.get('reinforced_count', 0) for r in reinforce_results)

    return {
        'total_notes': len(items),
        'prune_candidates': len(prune_candidates),
        'pruned': len(pruned),
        'protected_tendrils': list(protected_tendrils),
        'healed_count': heal_result.get('healed_count', 0),
        'reinforced_count': total_reinforced,
        'hubs': list(hubs),
        'dry_run': dry_run,
        'applied': apply and not dry_run,
    }
