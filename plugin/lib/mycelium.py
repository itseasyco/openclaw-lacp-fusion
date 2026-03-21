"""
Mycelium network memory algorithms.

Implements spreading activation, FSRS-inspired dual-strength memory model,
mycelium path reinforcement, self-healing, and flow score computation.

All functions operate on graph items represented as dicts keyed by node_id,
where each node has 'edges' (list of {id, similarity, ...}), 'count', 'last_seen', etc.
"""

import math
import random
from collections import deque
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Contradiction markers (used by prediction_error_gate)
# ---------------------------------------------------------------------------

CONTRADICTION_MARKERS = [
    "not", "no", "never", "neither", "nor", "isn't", "aren't", "wasn't",
    "weren't", "won't", "wouldn't", "shouldn't", "couldn't", "doesn't",
    "don't", "didn't", "can't", "cannot", "hardly", "scarcely", "barely",
    "contrary", "oppose", "reject", "refute", "disprove", "contradict",
    "however", "but", "although", "despite", "instead", "rather",
    "incorrect", "wrong", "false", "untrue", "invalid", "debunk",
]


# ---------------------------------------------------------------------------
# Spreading activation (Collins & Loftus)
# ---------------------------------------------------------------------------

def spreading_activation(seeds, items, alpha=0.7, max_hops=3):
    """
    Collins & Loftus spreading activation over graph edges.

    Args:
        seeds: {node_id: initial_activation} — starting activations.
        items: {node_id: {edges: [{id, similarity, ...}], ...}} — the graph.
        alpha: decay factor per hop (0.7 means 70% propagates).
        max_hops: maximum number of hops from any seed.

    Returns:
        {node_id: activation_score} for all reachable nodes.
        At each node, take MAX of incoming activations (not sum).
    """
    activations = {}

    # Initialize seeds
    for node_id, act_val in seeds.items():
        activations[node_id] = act_val

    # BFS with hop tracking — propagate activation
    # Queue entries: (node_id, current_activation, hops_used)
    queue = deque()
    for node_id, act_val in seeds.items():
        queue.append((node_id, act_val, 0))

    while queue:
        node_id, current_act, hops = queue.popleft()

        if hops >= max_hops:
            continue

        node = items.get(node_id)
        if node is None:
            continue

        edges = node.get('edges', [])
        for edge in edges:
            neighbor_id = edge.get('id')
            if neighbor_id is None:
                continue

            propagated = current_act * alpha
            existing = activations.get(neighbor_id, 0.0)

            if propagated > existing:
                activations[neighbor_id] = propagated
                queue.append((neighbor_id, propagated, hops + 1))

    return activations


# ---------------------------------------------------------------------------
# Dual-strength memory model (FSRS-inspired)
# ---------------------------------------------------------------------------

def compute_storage_strength(item):
    """
    FSRS-inspired storage strength from access count.

    Uses the formula: S = min(1.0, 0.1 + 0.05 * count)
    Takes the max of this floor and any existing storage_strength.

    Args:
        item: dict with 'count' (int) and optionally 'storage_strength' (float).

    Returns:
        float in [0, 1], monotonically increasing with count.
    """
    count = item.get('count', 0)
    existing = item.get('storage_strength', 0.0)

    # Floor from count: approaches 1.0 asymptotically via linear growth capped at 1.0
    floor = min(1.0, 0.1 + 0.05 * count)

    return max(floor, existing)


def compute_retrieval_strength(item, edge_count=0):
    """
    FSRS-inspired retrieval strength with temporal decay.

    More connections (edge_count) boost stability, slowing decay.
    Recent items have higher retrieval strength.

    Args:
        item: dict with 'count' (int), 'last_seen' (ISO date string).
        edge_count: number of edges (more connections = slower decay).

    Returns:
        float in [0, 1].
    """
    count = item.get('count', 0)
    last_seen_str = item.get('last_seen', '')

    # Parse last_seen
    if not last_seen_str:
        return 0.0

    try:
        # Handle various ISO formats
        last_seen_str_clean = last_seen_str.replace('Z', '+00:00')
        if '+' not in last_seen_str_clean and 'T' in last_seen_str_clean:
            last_seen_str_clean += '+00:00'
        last_seen = datetime.fromisoformat(last_seen_str_clean)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0

    now = datetime.now(timezone.utc)
    days_ago = max(0.0, (now - last_seen).total_seconds() / 86400.0)

    # Stability: base from count, boosted by edges
    # Higher stability = slower decay
    stability = max(1.0, count * (1.0 + 0.2 * edge_count))

    # Exponential decay: R = exp(-days / stability)
    retrieval = math.exp(-days_ago / stability)

    return min(1.0, max(0.0, retrieval))


def compute_importance_score(item, edge_count=0):
    """
    Combined importance from storage + retrieval + graph position.

    Weighted combination: 0.4*S + 0.4*R + 0.2*flow
    where flow defaults to 0 if not present.

    Args:
        item: dict with count, last_seen, and optionally flow_score.
        edge_count: number of edges for retrieval strength calc.

    Returns:
        float in [0, 1].
    """
    s = compute_storage_strength(item)
    r = compute_retrieval_strength(item, edge_count=edge_count)
    flow = item.get('flow_score', 0.0)

    score = 0.4 * s + 0.4 * r + 0.2 * flow
    return min(1.0, max(0.0, score))


# ---------------------------------------------------------------------------
# Prediction error gate
# ---------------------------------------------------------------------------

def prediction_error_gate(text, embedding, items):
    """
    Classify incoming information as novel, redundant, or contradicting.

    Args:
        text: the incoming text.
        embedding: embedding vector (list of floats), may be empty.
        items: {node_id: {embedding: [...], ...}} — existing knowledge.

    Returns:
        (classification, matched_id_or_None, similarity_or_0.0)
        classification is one of: 'novel', 'redundant', 'contradicting'
    """
    # Empty embedding → novel
    if not embedding:
        return ('novel', None, 0.0)

    # No items → novel
    if not items:
        return ('novel', None, 0.0)

    # Find most similar existing item
    best_sim = 0.0
    best_id = None

    for item_id, item_data in items.items():
        item_emb = item_data.get('embedding', [])
        if not item_emb or len(item_emb) != len(embedding):
            continue

        sim = _cosine_similarity(embedding, item_emb)
        if sim > best_sim:
            best_sim = sim
            best_id = item_id

    if best_id is None:
        return ('novel', None, 0.0)

    # Check for contradiction markers in text
    text_lower = text.lower()
    has_contradiction = any(marker in text_lower for marker in CONTRADICTION_MARKERS)

    if best_sim > 0.85 and has_contradiction:
        return ('contradicting', best_id, best_sim)
    elif best_sim > 0.85:
        return ('redundant', best_id, best_sim)
    else:
        return ('novel', best_id, best_sim)


def _cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Mycelium path reinforcement
# ---------------------------------------------------------------------------

def reinforce_access_paths(node_id, items):
    """
    Mycelium path reinforcement — traversing a node boosts its neighbors' confidence.

    When a node is accessed, all edges connected to it get a confidence boost.
    This simulates mycelial nutrient flow strengthening active pathways.

    Args:
        node_id: the node being traversed.
        items: {node_id: {edges: [{id, similarity, confidence?, ...}], ...}} — mutated in place.

    Returns:
        {reinforced_count: int} and potentially other stats.
    """
    node = items.get(node_id)
    if node is None:
        return {'reinforced_count': 0}

    reinforced_count = 0
    boost = 0.1  # confidence boost per reinforcement

    # Boost confidence on this node's outgoing edges
    for edge in node.get('edges', []):
        old_conf = edge.get('confidence', 0.5)
        edge['confidence'] = min(1.0, old_conf + boost)
        reinforced_count += 1

    # Also boost confidence on incoming edges from neighbors
    neighbor_ids = {e.get('id') for e in node.get('edges', []) if e.get('id')}
    for nid in neighbor_ids:
        neighbor = items.get(nid)
        if neighbor is None:
            continue
        for edge in neighbor.get('edges', []):
            if edge.get('id') == node_id:
                old_conf = edge.get('confidence', 0.5)
                edge['confidence'] = min(1.0, old_conf + boost)
                reinforced_count += 1

    return {'reinforced_count': reinforced_count}


# ---------------------------------------------------------------------------
# Mycelium self-healing
# ---------------------------------------------------------------------------

def heal_broken_paths(pruned_set, items, hubs):
    """
    After pruning nodes, reconnect orphaned neighbors via hubs.

    For each pruned node, find its former neighbors. If a neighbor would become
    disconnected (all its edges point to pruned nodes), reconnect it to the
    nearest hub.

    Args:
        pruned_set: set of node_ids being pruned.
        items: {node_id: {edges: [...], embedding: [...], ...}} — mutated in place.
        hubs: set of node_ids that are hubs (high-connectivity nodes).

    Returns:
        {healed_count: int}
    """
    healed_count = 0

    # Collect orphaned neighbors: nodes that had edges to pruned nodes
    orphan_candidates = set()
    for pruned_id in pruned_set:
        pruned_node = items.get(pruned_id)
        if pruned_node is None:
            continue
        for edge in pruned_node.get('edges', []):
            neighbor_id = edge.get('id')
            if neighbor_id and neighbor_id not in pruned_set and neighbor_id in items:
                orphan_candidates.add(neighbor_id)

    # For each orphan candidate, check if it needs reconnection
    for orphan_id in orphan_candidates:
        orphan = items.get(orphan_id)
        if orphan is None:
            continue

        # Remove edges to pruned nodes
        original_edges = orphan.get('edges', [])
        remaining_edges = [e for e in original_edges if e.get('id') not in pruned_set]
        orphan['edges'] = remaining_edges

        # If orphan has no remaining edges (or lost significant connectivity), connect to a hub
        # Find best hub by embedding similarity or just pick first available
        best_hub = None
        best_sim = -1.0
        orphan_emb = orphan.get('embedding', [])

        for hub_id in hubs:
            if hub_id == orphan_id or hub_id in pruned_set:
                continue
            hub_node = items.get(hub_id)
            if hub_node is None:
                continue

            hub_emb = hub_node.get('embedding', [])
            if orphan_emb and hub_emb and len(orphan_emb) == len(hub_emb):
                sim = _cosine_similarity(orphan_emb, hub_emb)
            else:
                sim = 0.5  # default similarity if no embeddings

            if sim > best_sim:
                best_sim = sim
                best_hub = hub_id

        if best_hub is not None:
            # Check if edge already exists
            existing_targets = {e.get('id') for e in orphan.get('edges', [])}
            if best_hub not in existing_targets:
                orphan['edges'].append({
                    'id': best_hub,
                    'similarity': best_sim,
                    'confidence': 0.5,
                    'healed': True,
                })
                # Also add reverse edge on hub
                hub_node = items.get(best_hub)
                if hub_node is not None:
                    hub_targets = {e.get('id') for e in hub_node.get('edges', [])}
                    if orphan_id not in hub_targets:
                        hub_node.setdefault('edges', []).append({
                            'id': orphan_id,
                            'similarity': best_sim,
                            'confidence': 0.5,
                            'healed': True,
                        })
                healed_count += 1

    # Remove pruned nodes' edges (cleanup)
    for pruned_id in pruned_set:
        if pruned_id in items:
            items[pruned_id]['edges'] = []

    return {'healed_count': healed_count}


# ---------------------------------------------------------------------------
# Flow score (betweenness centrality proxy)
# ---------------------------------------------------------------------------

def compute_flow_score(node_id, items, sample_size=20):
    """
    Betweenness centrality proxy — how important is this node as a connector.

    Samples random pairs of nodes and checks how many shortest paths go through
    the target node. Hub nodes that connect many components score higher.

    Args:
        node_id: the node to score.
        items: {node_id: {edges: [{id, ...}], ...}} — the graph.
        sample_size: max number of source-target pairs to sample.

    Returns:
        float in [0, 1].
    """
    all_nodes = [n for n in items.keys() if n != node_id]

    if len(all_nodes) < 2:
        return 0.0

    # Build adjacency list
    adjacency = {}
    for nid, data in items.items():
        adjacency[nid] = [e.get('id') for e in data.get('edges', []) if e.get('id') in items]

    # Sample pairs
    pairs = []
    possible_pairs = [(a, b) for i, a in enumerate(all_nodes) for b in all_nodes[i+1:]]
    if len(possible_pairs) <= sample_size:
        pairs = possible_pairs
    else:
        pairs = random.sample(possible_pairs, sample_size)

    if not pairs:
        return 0.0

    through_count = 0
    reachable_count = 0

    for source, target in pairs:
        # BFS shortest path from source to target (with node_id present)
        path_with = _bfs_shortest_path(source, target, adjacency)
        if path_with is None:
            continue

        reachable_count += 1

        # Check if node_id is on the shortest path (excluding endpoints)
        if node_id in path_with and node_id != source and node_id != target:
            # Verify it's actually needed: try without it
            adjacency_without = {}
            for nid, neighbors in adjacency.items():
                if nid == node_id:
                    adjacency_without[nid] = []
                else:
                    adjacency_without[nid] = [n for n in neighbors if n != node_id]

            path_without = _bfs_shortest_path(source, target, adjacency_without)
            if path_without is None or len(path_without) > len(path_with):
                through_count += 1

    if reachable_count == 0:
        return 0.0

    return min(1.0, through_count / reachable_count)


def _bfs_shortest_path(source, target, adjacency):
    """BFS shortest path, returns list of nodes or None if unreachable."""
    if source == target:
        return [source]

    visited = {source}
    queue = deque([(source, [source])])

    while queue:
        current, path = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor == target:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return None
