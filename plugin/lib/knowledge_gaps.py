"""
Knowledge gap detection.

Detects cross-category bridges and under-researched areas by analyzing
the knowledge graph structure.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from plugin.lib.consolidation import _load_vault_notes
from plugin.lib.mycelium import compute_storage_strength


def detect_knowledge_gaps(vault_path=None, min_category_size=3):
    """
    Detect cross-category bridges and under-researched areas.

    Finds:
    1. Categories with few notes (under-researched areas)
    2. Pairs of categories with no cross-links (missing bridges)
    3. Weak bridges (cross-links with low confidence)

    Args:
        vault_path: path to the Obsidian vault.
        min_category_size: categories below this threshold are flagged as sparse.

    Returns:
        dict with sparse_categories, missing_bridges, weak_bridges.
    """
    if vault_path is None:
        vault_path = os.environ.get('LACP_OBSIDIAN_VAULT', os.path.expanduser('~/obsidian/vault'))

    items = _load_vault_notes(vault_path)

    # Build category membership
    category_members = defaultdict(set)
    node_categories = {}
    for node_id, data in items.items():
        cats = data.get('categories', [])
        node_categories[node_id] = set(cats)
        for cat in cats:
            category_members[cat].add(node_id)

    # 1. Sparse categories
    sparse_categories = []
    for cat, members in category_members.items():
        if len(members) < min_category_size:
            sparse_categories.append({
                'category': cat,
                'count': len(members),
                'notes': sorted(members),
            })

    sparse_categories.sort(key=lambda x: x['count'])

    # 2. Missing bridges — pairs of categories with no cross-links
    all_cats = sorted(category_members.keys())
    missing_bridges = []
    weak_bridges = []

    for i, cat_a in enumerate(all_cats):
        for cat_b in all_cats[i + 1:]:
            members_a = category_members[cat_a]
            members_b = category_members[cat_b]

            # Check for cross-links
            cross_link_count = 0
            cross_link_strength = 0.0

            for node_id in members_a:
                node = items.get(node_id, {})
                for edge in node.get('edges', []):
                    target = edge.get('id')
                    if target in members_b:
                        cross_link_count += 1
                        cross_link_strength += edge.get('confidence', edge.get('similarity', 0.5))

            for node_id in members_b:
                node = items.get(node_id, {})
                for edge in node.get('edges', []):
                    target = edge.get('id')
                    if target in members_a:
                        cross_link_count += 1
                        cross_link_strength += edge.get('confidence', edge.get('similarity', 0.5))

            if cross_link_count == 0:
                missing_bridges.append({
                    'categories': [cat_a, cat_b],
                    'sizes': [len(members_a), len(members_b)],
                })
            elif cross_link_count > 0:
                avg_strength = cross_link_strength / cross_link_count
                if avg_strength < 0.5:
                    weak_bridges.append({
                        'categories': [cat_a, cat_b],
                        'cross_links': cross_link_count,
                        'avg_strength': round(avg_strength, 4),
                    })

    return {
        'sparse_categories': sparse_categories,
        'missing_bridges': missing_bridges,
        'weak_bridges': weak_bridges,
        'total_categories': len(all_cats),
        'total_notes': len(items),
    }


def write_gap_report(vault_path=None, min_category_size=3):
    """
    Generate and write a knowledge gap report to the vault.
    """
    if vault_path is None:
        vault_path = os.environ.get('LACP_OBSIDIAN_VAULT', os.path.expanduser('~/obsidian/vault'))

    gaps = detect_knowledge_gaps(vault_path, min_category_size)
    vault = Path(vault_path)
    inbox = vault / '05_Inbox'
    inbox.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    lines = [
        '---',
        'type: knowledge-gap-report',
        'generated: "' + now + '"',
        '---',
        '',
        '# Knowledge Gap Report',
        '',
        'Generated: ' + now,
        '',
        '## Summary',
        '',
        '- Total categories: {}'.format(gaps['total_categories']),
        '- Total notes: {}'.format(gaps['total_notes']),
        '- Sparse categories: {}'.format(len(gaps['sparse_categories'])),
        '- Missing bridges: {}'.format(len(gaps['missing_bridges'])),
        '- Weak bridges: {}'.format(len(gaps['weak_bridges'])),
        '',
    ]

    if gaps['sparse_categories']:
        lines.append('## Sparse Categories (under-researched)')
        lines.append('')
        lines.append('| Category | Notes | Members |')
        lines.append('|----------|-------|---------|')
        for sc in gaps['sparse_categories']:
            members = ', '.join('[[{}]]'.format(n) for n in sc['notes'][:5])
            lines.append('| {} | {} | {} |'.format(sc['category'], sc['count'], members))
        lines.append('')

    if gaps['missing_bridges']:
        lines.append('## Missing Bridges (no cross-links)')
        lines.append('')
        lines.append('| Category A | Category B | Sizes |')
        lines.append('|------------|------------|-------|')
        for mb in gaps['missing_bridges'][:20]:
            lines.append('| {} | {} | {}x{} |'.format(
                mb['categories'][0], mb['categories'][1],
                mb['sizes'][0], mb['sizes'][1],
            ))
        lines.append('')

    if gaps['weak_bridges']:
        lines.append('## Weak Bridges (low-confidence cross-links)')
        lines.append('')
        lines.append('| Category A | Category B | Links | Avg Strength |')
        lines.append('|------------|------------|-------|--------------|')
        for wb in gaps['weak_bridges'][:20]:
            lines.append('| {} | {} | {} | {:.2f} |'.format(
                wb['categories'][0], wb['categories'][1],
                wb['cross_links'], wb['avg_strength'],
            ))
        lines.append('')

    lines.append('')

    output_path = inbox / 'knowledge-gaps.md'
    output_path.write_text('\n'.join(lines), encoding='utf-8')

    return {
        'path': str(output_path),
        'gaps': gaps,
    }
