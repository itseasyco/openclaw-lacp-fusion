"""Tests for openclaw-lacp-promote CLI and promotion pipeline."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BIN_DIR = REPO_ROOT / "plugin" / "bin"
V2_LCM_DIR = REPO_ROOT / "plugin" / "v2-lcm"
PROMOTE_SCRIPT = BIN_DIR / "openclaw-lacp-promote"

# Add v2-lcm to path for direct Python imports
sys.path.insert(0, str(V2_LCM_DIR))
from promotion_scorer import PromotionScorer, score_summary, CATEGORIES


class TestPromoteScriptExists:
    """Verify the CLI script exists and is executable."""

    def test_script_exists(self):
        assert PROMOTE_SCRIPT.exists()

    def test_script_is_executable(self):
        assert os.access(PROMOTE_SCRIPT, os.X_OK)

    def test_script_has_shebang(self):
        content = PROMOTE_SCRIPT.read_text()
        assert content.startswith("#!/usr/bin/env bash")


class TestPromoteHelp:
    """Test --help output."""

    def test_help_flag(self):
        result = subprocess.run(
            [str(PROMOTE_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "openclaw-lacp-promote" in result.stdout
        assert "COMMANDS:" in result.stdout

    def test_help_shows_commands(self):
        result = subprocess.run(
            [str(PROMOTE_SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        for cmd in ["auto", "pipeline", "manual", "list", "verify"]:
            assert cmd in result.stdout

    def test_version_flag(self):
        result = subprocess.run(
            [str(PROMOTE_SCRIPT), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "2.0.0" in result.stdout


class TestPromotionScorerDirect:
    """Test the PromotionScorer Python class directly."""

    def test_default_threshold(self):
        scorer = PromotionScorer()
        assert scorer.threshold == 70

    def test_custom_threshold(self):
        scorer = PromotionScorer(threshold=85)
        assert scorer.threshold == 85

    def test_score_returns_dict(self):
        scorer = PromotionScorer()
        result = scorer.score({"content": "Architecture decision: use PostgreSQL", "source": "code"})
        assert isinstance(result, dict)
        assert "score" in result
        assert "category" in result
        assert "facts" in result
        assert "breakdown" in result

    def test_score_range(self):
        scorer = PromotionScorer()
        result = scorer.score({"content": "Some operational knowledge about deployment", "source": "unknown"})
        assert 0 <= result["score"] <= 100

    def test_high_score_promotes(self):
        scorer = PromotionScorer(threshold=50)
        result = scorer.score({
            "content": "Architecture decision: we chose PostgreSQL for the database. Migration from MySQL was decided by the team. The deployment infrastructure uses Docker containers.",
            "source": "code",
            "citations": ["ref1", "ref2", "ref3"],
        })
        assert result["promote"] is True

    def test_low_score_rejects(self):
        scorer = PromotionScorer(threshold=95)
        result = scorer.score({"content": "maybe something unclear", "source": "unknown"})
        assert result["promote"] is False

    def test_fact_extraction_bullets(self):
        scorer = PromotionScorer()
        content = "- Brale handles all settlement operations\n- Treasury uses multi-sig wallets\n- short"
        facts = scorer.extract_facts(content)
        assert len(facts) >= 2
        assert "Brale handles all settlement operations" in facts

    def test_categorize_architectural(self):
        scorer = PromotionScorer()
        cat = scorer.categorize("We decided on a microservices architecture with schema migrations", [])
        assert cat == "architectural-decision"

    def test_categorize_debugging(self):
        scorer = PromotionScorer()
        cat = scorer.categorize("Found a bug causing timeout errors, the fix was to increase retry count", [])
        assert cat == "debugging-insight"

    def test_receipt_hash_deterministic(self):
        scorer = PromotionScorer()
        result = {"score": 75, "facts": ["fact1"]}
        hash1 = scorer.generate_receipt_hash(result)
        hash2 = scorer.generate_receipt_hash(result)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256

    def test_score_summary_convenience(self):
        result = score_summary({"content": "Test content", "source": "lcm"})
        assert "receipt_hash" in result
        assert "score" in result


class TestPromotePipeline:
    """Test the pipeline command with real files."""

    def test_pipeline_with_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a summary file
            summary_file = Path(tmpdir) / "sum_test123.md"
            summary_file.write_text(
                "# Session Summary\n\n"
                "- Architecture decision: use FastAPI for the API layer\n"
                "- Database migration from SQLite to PostgreSQL decided\n"
                "- Deployment pipeline uses GitHub Actions\n"
            )

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            result = subprocess.run(
                [str(PROMOTE_SCRIPT), "pipeline", "--file", str(summary_file), "--project", "test-project", "--threshold", "30"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert result.returncode == 0
            assert "Pipeline complete" in result.stdout or "Score:" in result.stdout

    def test_pipeline_with_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "sum_json456.json"
            summary_file.write_text(json.dumps({
                "summary_id": "sum_json456",
                "content": "Architecture: we decided to use Supabase for auth. The API uses FastAPI.",
                "source": "code",
                "citations": ["file1.py", "file2.ts"],
                "project": "test-project",
            }))

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            result = subprocess.run(
                [str(PROMOTE_SCRIPT), "pipeline", "--file", str(summary_file), "--threshold", "30"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert result.returncode == 0

    def test_pipeline_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "sum_dry.md"
            summary_file.write_text("- Test fact for dry run pipeline\n- Another architecture decision\n")

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            result = subprocess.run(
                [str(PROMOTE_SCRIPT), "pipeline", "--file", str(summary_file), "--dry-run", "--threshold", "0"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert result.returncode == 0
            assert "DRY RUN" in result.stdout

    def test_pipeline_missing_file(self):
        result = subprocess.run(
            [str(PROMOTE_SCRIPT), "pipeline", "--file", "/nonexistent/file.md"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0


class TestPromoteAuditLog:
    """Test audit trail (gated-runs.jsonl logging)."""

    def test_promotion_creates_log_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "sum_audit.md"
            summary_file.write_text("- Important architecture decision about infrastructure\n" * 3)

            gated_log = Path(tmpdir) / "logs" / "gated-runs.jsonl"

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(gated_log)
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            subprocess.run(
                [str(PROMOTE_SCRIPT), "pipeline", "--file", str(summary_file), "--threshold", "0", "--project", "audit-test"],
                capture_output=True, text=True, timeout=30, env=env,
            )

            assert gated_log.exists()
            entries = [json.loads(line) for line in gated_log.read_text().strip().split("\n") if line.strip()]
            assert len(entries) > 0
            assert "event" in entries[0] or "timestamp" in entries[0]

    def test_promotion_log_has_receipt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "sum_receipt.md"
            summary_file.write_text("- Important fact about deployment process and infrastructure\n" * 3)

            promotions_log = Path(tmpdir) / "logs" / "promotions.jsonl"

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(promotions_log)
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            subprocess.run(
                [str(PROMOTE_SCRIPT), "pipeline", "--file", str(summary_file), "--threshold", "0", "--project", "receipt-test"],
                capture_output=True, text=True, timeout=30, env=env,
            )

            if promotions_log.exists():
                entries = [json.loads(line) for line in promotions_log.read_text().strip().split("\n") if line.strip()]
                if entries:
                    assert "receipt_hash" in entries[0]


class TestPromoteManual:
    """Test manual promotion command."""

    def test_manual_promote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(Path(tmpdir) / "memory")
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            result = subprocess.run(
                [str(PROMOTE_SCRIPT), "manual",
                 "--summary", "sum_manual_001",
                 "--fact", "Brale is the settlement layer",
                 "--reasoning", "Affects treasury design",
                 "--project", "easy-api"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert result.returncode == 0
            assert "Manual promotion complete" in result.stdout

    def test_manual_writes_to_layer1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_root = Path(tmpdir) / "memory"

            env = os.environ.copy()
            env["OPENCLAW_MEMORY_ROOT"] = str(memory_root)
            env["OPENCLAW_VAULT_ROOT"] = str(Path(tmpdir) / "vault")
            env["OPENCLAW_PROMOTIONS_LOG"] = str(Path(tmpdir) / "logs" / "promotions.jsonl")
            env["OPENCLAW_GATED_RUNS_LOG"] = str(Path(tmpdir) / "logs" / "gated-runs.jsonl")
            env["OPENCLAW_PROVENANCE_DIR"] = str(Path(tmpdir) / "provenance")

            subprocess.run(
                [str(PROMOTE_SCRIPT), "manual",
                 "--summary", "sum_layer1_test",
                 "--fact", "PostgreSQL is the primary database",
                 "--category", "architectural-decision",
                 "--project", "test-proj"],
                capture_output=True, text=True, timeout=30, env=env,
            )

            memory_file = memory_root / "test-proj" / "MEMORY.md"
            assert memory_file.exists()
            content = memory_file.read_text()
            assert "PostgreSQL is the primary database" in content


class TestPromoteCategories:
    """Test all valid promotion categories."""

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_valid_category(self, category):
        assert isinstance(category, str)
        assert len(category) > 0
        assert "-" in category  # All categories use kebab-case

    def test_all_categories_present(self):
        expected = [
            "architectural-decision", "operational-knowledge", "domain-insight",
            "integration-pattern", "debugging-insight", "team-context", "process-improvement",
        ]
        for cat in expected:
            assert cat in CATEGORIES
