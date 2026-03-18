"""Integration tests for Phase C & D — End-to-end promotion → dedup → injection."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BIN_DIR = REPO_ROOT / "plugin" / "bin"
V2_LCM_DIR = REPO_ROOT / "plugin" / "v2-lcm"

sys.path.insert(0, str(V2_LCM_DIR))

from promotion_scorer import PromotionScorer, score_summary
from semantic_dedup import SemanticDedup
from confidence_calibration import CalibrationTracker
from sharing_policy import SharingPolicy


class TestPromotionToDedup:
    """Test promotion → dedup pipeline."""

    def test_score_then_dedup_check(self):
        """Score a summary, then check if the promoted fact is a duplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()

            # Write an existing fact
            (vault_dir / "existing.md").write_text(
                "# Existing Facts\n\n"
                "PostgreSQL is the primary database for all services.\n"
            )

            # Score a new summary
            result = score_summary({
                "content": "PostgreSQL is the primary database for all services.",
                "source": "code",
            })

            # Check dedup
            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            is_dup = sd.is_duplicate("PostgreSQL is the primary database for all services")
            assert is_dup is True

    def test_novel_fact_passes_dedup(self):
        """A genuinely new fact should not be flagged as duplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()
            (vault_dir / "existing.md").write_text(
                "# Existing Facts\n\nRedis handles caching.\n"
            )

            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            is_dup = sd.is_duplicate("Settlement processing uses Brale for all stablecoin operations")
            assert is_dup is False


class TestPromotionToCalibration:
    """Test promotion → calibration pipeline."""

    def test_promote_and_track(self):
        """Promote a fact, record it in calibration, then mark as used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = str(Path(tmpdir) / "cal.json")

            # Score
            result = score_summary({
                "content": "Architecture: we decided to use microservices",
                "source": "code",
                "citations": ["ref1"],
            })

            # Record in calibration
            ct = CalibrationTracker(config_path=config)
            ct.record_promotion("sum_1", "fact_1", result["score"])

            # Mark as used
            ct.mark_used("sum_1", "fact_1")

            # Verify
            metrics = ct.compute_metrics(result["score"] - 10)
            assert metrics["tp"] >= 1

    def test_calibration_threshold_adjusts(self):
        """After enough data, optimal threshold should differ from default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))

            # Add diverse data
            for i in range(20):
                score = 50 + i * 2.5
                ct.record_promotion(f"s{i}", f"f{i}", score)
                # High scores are used, low scores aren't
                if score >= 75:
                    ct.mark_used(f"s{i}", f"f{i}")
                else:
                    ct.mark_unused(f"s{i}", f"f{i}")

            optimal = ct.compute_optimal_threshold()
            assert 40 <= optimal <= 95


class TestPromotionWithPolicy:
    """Test promotion with sharing policy checks."""

    def test_writer_can_promote(self):
        """A writer agent should be able to promote facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")

            assert sp.can_promote("wren", "easy-api") is True

            # Score summary
            result = score_summary({
                "content": "FastAPI handles the API layer",
                "source": "code",
            })
            assert result["score"] > 0

            # Record promotion
            sp.record_promotion("wren", "easy-api", "fact_001")
            sp.save()

    def test_reader_cannot_promote(self):
        """A reader agent should not be able to promote facts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("zoe", "easy-api", "reader")

            assert sp.can_promote("zoe", "easy-api") is False


class TestEndToEndPipeline:
    """Test full promotion → dedup → calibration → policy pipeline."""

    def test_full_pipeline(self):
        """Run the complete pipeline: score → dedup → promote → calibrate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()

            # 1. Score
            result = score_summary({
                "content": "We decided to use Brale for settlement. The treasury module handles multi-sig wallets.",
                "source": "documentation",
                "citations": ["treasury-spec.md", "settlement-flow.md"],
            })
            assert result["score"] > 0

            # 2. Dedup check
            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            is_dup = sd.is_duplicate(result["facts"][0] if result["facts"] else "Brale handles settlement")
            assert is_dup is False  # First time, not a duplicate

            # 3. Policy check
            sp = SharingPolicy(config_path=str(Path(tmpdir) / "sharing.json"))
            sp.grant_access("wren", "easy-api", "writer")
            assert sp.can_promote("wren", "easy-api") is True

            # 4. Calibrate
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", result["score"], result["category"])
            ct.mark_used("sum_1", "fact_1")

            summary = ct.summary()
            assert summary["total_records"] == 1
            assert summary["labeled_records"] == 1

    def test_pipeline_rejects_duplicate(self):
        """Pipeline should skip promotion if fact is a duplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_dir = Path(tmpdir) / "vault"
            vault_dir.mkdir()

            existing_fact = "PostgreSQL is the primary database for all services in the platform"
            (vault_dir / "known-facts.md").write_text(f"# Facts\n\n{existing_fact}\n")

            # Score a summary with the same fact
            result = score_summary({
                "content": existing_fact,
                "source": "lcm",
            })

            # Dedup should catch it
            sd = SemanticDedup(vault_path=str(vault_dir), threshold=0.85)
            is_dup = sd.is_duplicate(existing_fact)
            assert is_dup is True


class TestCLIIntegration:
    """Test CLI scripts work together."""

    def test_promote_and_status_scripts_exist(self):
        """All Phase C/D CLI scripts should exist."""
        scripts = [
            "openclaw-lacp-promote",
            "openclaw-lacp-context",
            "openclaw-memory-status",
            "openclaw-lacp-calibrate",
            "openclaw-lacp-policies",
        ]
        for script in scripts:
            path = BIN_DIR / script
            assert path.exists(), f"Missing script: {script}"
            assert os.access(path, os.X_OK), f"Not executable: {script}"

    def test_all_scripts_have_help(self):
        """All Phase C/D scripts should respond to --help."""
        scripts = [
            "openclaw-lacp-promote",
            "openclaw-lacp-context",
            "openclaw-memory-status",
            "openclaw-lacp-calibrate",
            "openclaw-lacp-policies",
        ]
        for script in scripts:
            result = subprocess.run(
                [str(BIN_DIR / script), "--help"],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, f"--help failed for {script}: {result.stderr}"
            assert "2.0.0" in result.stdout or script in result.stdout

    def test_memory_status_runs(self):
        """openclaw-memory-status should run without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")

            result = subprocess.run(
                [str(BIN_DIR / "openclaw-memory-status")],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0

    def test_memory_status_json_output(self):
        """openclaw-memory-status --json should produce valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")

            result = subprocess.run(
                [str(BIN_DIR / "openclaw-memory-status"), "--json"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert "graph" in data
            assert "version" in data
