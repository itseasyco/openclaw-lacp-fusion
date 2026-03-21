"""
Tests for mycelium network memory algorithms.

These tests mirror the LACP test contracts from test-brain-memory.sh.
"""

import math
import random
from datetime import datetime, timezone

import pytest

from plugin.lib.mycelium import (
    CONTRADICTION_MARKERS,
    compute_flow_score,
    compute_importance_score,
    compute_retrieval_strength,
    compute_storage_strength,
    heal_broken_paths,
    prediction_error_gate,
    reinforce_access_paths,
    spreading_activation,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Test 1: Spreading activation
# ---------------------------------------------------------------------------

class TestSpreadingActivation:
    def test_anchor_preserved(self):
        """Seed node keeps its original activation."""
        items = {
            'a': {'edges': [{'id': 'b', 'similarity': 0.8}], 'count': 1, 'last_seen': _now_iso()},
            'b': {'edges': [{'id': 'c', 'similarity': 0.7}], 'count': 1, 'last_seen': _now_iso()},
            'c': {'edges': [], 'count': 1, 'last_seen': _now_iso()},
        }
        act = spreading_activation({'a': 1.0}, items, alpha=0.7, max_hops=3)
        assert act['a'] == 1.0

    def test_hop1_decay(self):
        """One hop away decays by alpha."""
        items = {
            'a': {'edges': [{'id': 'b', 'similarity': 0.8}], 'count': 1, 'last_seen': _now_iso()},
            'b': {'edges': [{'id': 'c', 'similarity': 0.7}], 'count': 1, 'last_seen': _now_iso()},
            'c': {'edges': [], 'count': 1, 'last_seen': _now_iso()},
        }
        act = spreading_activation({'a': 1.0}, items, alpha=0.7, max_hops=3)
        assert act['b'] == 0.7

    def test_hop2_decay(self):
        """Two hops away decays by alpha^2."""
        items = {
            'a': {'edges': [{'id': 'b', 'similarity': 0.8}], 'count': 1, 'last_seen': _now_iso()},
            'b': {'edges': [{'id': 'c', 'similarity': 0.7}], 'count': 1, 'last_seen': _now_iso()},
            'c': {'edges': [], 'count': 1, 'last_seen': _now_iso()},
        }
        act = spreading_activation({'a': 1.0}, items, alpha=0.7, max_hops=3)
        assert abs(act['c'] - 0.49) < 1e-10

    def test_max_not_sum(self):
        """Multi-seed: take max of incoming activations, not sum."""
        items = {
            'a': {'edges': [{'id': 'c', 'similarity': 0.9}], 'count': 1, 'last_seen': _now_iso()},
            'b': {'edges': [{'id': 'c', 'similarity': 0.8}], 'count': 1, 'last_seen': _now_iso()},
            'c': {'edges': [], 'count': 1, 'last_seen': _now_iso()},
        }
        act = spreading_activation({'a': 1.0, 'b': 0.5}, items, alpha=0.7, max_hops=1)
        # a->c: 1.0*0.7=0.7, b->c: 0.5*0.7=0.35, max=0.7
        assert act.get('c', 0) == 0.7


# ---------------------------------------------------------------------------
# Test 2: Dual-strength model
# ---------------------------------------------------------------------------

class TestDualStrength:
    def test_storage_strength_positive(self):
        item = {'count': 10, 'last_seen': _now_iso()}
        s = compute_storage_strength(item)
        assert s > 0.0

    def test_retrieval_strength_positive(self):
        item = {'count': 10, 'last_seen': _now_iso()}
        r = compute_retrieval_strength(item, edge_count=2)
        assert r > 0.0

    def test_combined_score_positive(self):
        item = {'count': 10, 'last_seen': _now_iso()}
        score = compute_importance_score(item, edge_count=2)
        assert score > 0.0

    def test_storage_strength_floor_from_count(self):
        """count=10 -> floor = min(1.0, 0.1 + 0.05*10) = 0.6, so > 0.59."""
        s = compute_storage_strength({'count': 10})
        assert s > 0.59

    def test_retrieval_strength_decays_with_age(self):
        """Old item (2025-01-01) with count=1, edge_count=0 decays below 0.5."""
        r = compute_retrieval_strength({'count': 1, 'last_seen': '2025-01-01'}, edge_count=0)
        assert r < 0.5

    def test_storage_strength_monotonic(self):
        """Storage strength increases with count."""
        prev = 0.0
        for count in [1, 5, 10, 15, 18]:
            s = compute_storage_strength({'count': count})
            assert s >= prev
            prev = s

    def test_importance_score_in_range(self):
        """Score is a float in [0, 1]."""
        item = {'count': 5, 'last_seen': _now_iso()}
        score = compute_importance_score(item, edge_count=2)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Test 3: Synaptic tagging (S boost to neighbors)
# ---------------------------------------------------------------------------

class TestSynapticTagging:
    def test_boosts_neighbor_s(self):
        """New item's storage strength can boost a neighbor's S."""
        new_item = {'count': 1, 'storage_strength': 0.0}
        new_s = compute_storage_strength(new_item)
        boost = 0.1 * new_s
        updated_s = round(min(1.0, 0.2 + boost), 4)
        assert updated_s > 0.2


# ---------------------------------------------------------------------------
# Test 4: Prediction error gate
# ---------------------------------------------------------------------------

class TestPredictionErrorGate:
    def test_empty_embedding_novel(self):
        cls, mid, sim = prediction_error_gate('test text', [], {})
        assert cls == 'novel'

    def test_no_items_novel(self):
        cls, mid, sim = prediction_error_gate('test', [1.0, 0.0], {})
        assert cls == 'novel'

    def test_has_contradiction_markers(self):
        assert len(CONTRADICTION_MARKERS) > 0


# ---------------------------------------------------------------------------
# Test 5: Consolidation prune candidates
# ---------------------------------------------------------------------------

class TestPruneCandidates:
    def test_low_s_low_r_is_prune_candidate(self):
        """Ancient item with no access = low S, low R."""
        item = {'count': 1, 'last_seen': '2024-01-01', 'storage_strength': 0.05}
        s = compute_storage_strength(item)
        r = compute_retrieval_strength(item, edge_count=0)
        assert s < 0.3
        assert r < 0.1


# ---------------------------------------------------------------------------
# Test 6: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_single_float_return(self):
        item = {'count': 5, 'last_seen': _now_iso()}
        score = compute_importance_score(item, edge_count=2)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_review_queue_imports_work(self):
        """All three functions are importable."""
        from plugin.lib.mycelium import (
            compute_importance_score,
            compute_retrieval_strength,
            compute_storage_strength,
        )
        assert callable(compute_importance_score)
        assert callable(compute_retrieval_strength)
        assert callable(compute_storage_strength)


# ---------------------------------------------------------------------------
# Test 8: Mycelium path reinforcement
# ---------------------------------------------------------------------------

class TestReinforceAccessPaths:
    def test_reinforce_count_positive(self):
        items = {
            'a': {'edges': [{'id': 'b', 'similarity': 0.8}], 'count': 5, 'last_seen': _now_iso(), 'categories': ['hub']},
            'b': {'edges': [{'id': 'c', 'similarity': 0.7}], 'count': 2, 'last_seen': _now_iso(), 'categories': []},
            'c': {'edges': [], 'count': 1, 'last_seen': _now_iso(), 'categories': []},
        }
        result = reinforce_access_paths('b', items)
        assert result['reinforced_count'] > 0

    def test_reinforce_boosts_confidence(self):
        items = {
            'a': {'edges': [{'id': 'b', 'similarity': 0.8}], 'count': 5, 'last_seen': _now_iso(), 'categories': ['hub']},
            'b': {'edges': [{'id': 'a', 'similarity': 0.8, 'confidence': 0.5}], 'count': 2, 'last_seen': _now_iso(), 'categories': []},
        }
        reinforce_access_paths('b', items)
        conf = items['b']['edges'][0].get('confidence', 0)
        assert conf > 0.5


# ---------------------------------------------------------------------------
# Test 9: Mycelium self-healing
# ---------------------------------------------------------------------------

class TestHealBrokenPaths:
    def test_heal_reconnects_orphan(self):
        items = {
            'hub1': {'edges': [{'id': 'b', 'similarity': 0.9}], 'count': 10, 'embedding': [1.0, 0.0, 0.0], 'categories': ['hub']},
            'b':    {'edges': [{'id': 'hub1', 'similarity': 0.9}, {'id': 'c', 'similarity': 0.7}], 'count': 3, 'embedding': [0.8, 0.2, 0.0], 'categories': []},
            'c':    {'edges': [{'id': 'b', 'similarity': 0.7}], 'count': 1, 'embedding': [0.7, 0.3, 0.0], 'categories': []},
        }
        result = heal_broken_paths({'b'}, items, {'hub1'})
        assert result['healed_count'] > 0


# ---------------------------------------------------------------------------
# Test 10: Flow score computation
# ---------------------------------------------------------------------------

class TestFlowScore:
    def test_hub_positive(self):
        random.seed(42)
        items = {
            'hub': {'edges': [{'id': 'a', 'similarity': 0.9}, {'id': 'b', 'similarity': 0.9}, {'id': 'c', 'similarity': 0.9}, {'id': 'd', 'similarity': 0.9}], 'count': 10},
            'a':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
            'b':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
            'c':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
            'd':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
        }
        score = compute_flow_score('hub', items, sample_size=20)
        assert score > 0.0

    def test_leaf_low(self):
        random.seed(42)
        items = {
            'hub': {'edges': [{'id': 'a', 'similarity': 0.9}, {'id': 'b', 'similarity': 0.9}, {'id': 'c', 'similarity': 0.9}], 'count': 10},
            'a':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
            'b':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
            'c':   {'edges': [{'id': 'hub', 'similarity': 0.9}], 'count': 1},
        }
        score = compute_flow_score('a', items, sample_size=20)
        assert score < 0.5
