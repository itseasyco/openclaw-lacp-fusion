"""
FSRS review queue generator.

Finds notes with low retrieval_strength that haven't been reviewed recently,
and outputs a prioritized list of notes needing review.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from plugin.lib.consolidation import _load_vault_notes
from plugin.lib.mycelium import (
    compute_retrieval_strength,
    compute_storage_strength,
)


def generate_review_queue(vault_path=None, max_items=20, r_threshold=0.5):
    """
    Generate a prioritized review queue of notes needing attention.

    Notes with low retrieval strength but meaningful storage strength
    are the best candidates for review — they represent knowledge that
    was once learned but is fading.

    Args:
        vault_path: path to the Obsidian vault.
        max_items: maximum number of items in the queue.
        r_threshold: retrieval strength threshold below which review is needed.

    Returns:
        list of dicts with note_id, storage_strength, retrieval_strength, priority.
    """
    if vault_path is None:
        vault_path = os.environ.get('LACP_OBSIDIAN_VAULT', os.path.expanduser('~/obsidian/vault'))

    items = _load_vault_notes(vault_path)

    candidates = []
    for node_id, data in items.items():
        edge_count = len(data.get('edges', []))
        s = compute_storage_strength(data)
        r = compute_retrieval_strength(data, edge_count=edge_count)

        if r < r_threshold and s > 0.1:
            # Priority: high S + low R = most urgent (we knew it well, now forgetting)
            priority = s * (1.0 - r)
            candidates.append({
                'note_id': node_id,
                'storage_strength': round(s, 4),
                'retrieval_strength': round(r, 4),
                'priority': round(priority, 4),
                'path': data.get('relative_path', ''),
                'categories': data.get('categories', []),
            })

    # Sort by priority (highest first)
    candidates.sort(key=lambda x: x['priority'], reverse=True)

    return candidates[:max_items]


def write_review_queue(vault_path=None, max_items=20, r_threshold=0.5):
    """
    Generate and write the review queue to the vault's inbox.

    Writes to 05_Inbox/review-queue.md in the vault.
    """
    if vault_path is None:
        vault_path = os.environ.get('LACP_OBSIDIAN_VAULT', os.path.expanduser('~/obsidian/vault'))

    queue = generate_review_queue(vault_path, max_items, r_threshold)
    vault = Path(vault_path)
    inbox = vault / '05_Inbox'
    inbox.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    lines = [
        '---',
        'type: review-queue',
        'generated: "' + now + '"',
        'count: ' + str(len(queue)),
        '---',
        '',
        '# Review Queue',
        '',
        'Generated: ' + now,
        '',
        '| Priority | Note | S | R | Categories |',
        '|----------|------|---|---|------------|',
    ]

    for item in queue:
        cats = ', '.join(item.get('categories', []))
        lines.append(
            '| {:.2f} | [[{}]] | {:.2f} | {:.2f} | {} |'.format(
                item['priority'],
                item['note_id'],
                item['storage_strength'],
                item['retrieval_strength'],
                cats,
            )
        )

    if not queue:
        lines.append('| - | No items need review | - | - | - |')

    lines.append('')
    lines.append('> Notes with high storage strength but low retrieval strength')
    lines.append('> are the best candidates — knowledge once learned, now fading.')
    lines.append('')

    output_path = inbox / 'review-queue.md'
    output_path.write_text('\n'.join(lines), encoding='utf-8')

    return {
        'path': str(output_path),
        'count': len(queue),
        'items': queue,
    }
