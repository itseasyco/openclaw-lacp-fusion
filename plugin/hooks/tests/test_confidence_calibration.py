"""Tests for confidence_calibration.py — Dynamic threshold adjustment."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
V2_LCM_DIR = REPO_ROOT / "plugin" / "v2-lcm"
sys.path.insert(0, str(V2_LCM_DIR))

from confidence_calibration import CalibrationTracker


class TestCalibrationInit:
    """Test CalibrationTracker initialization."""

    def test_init_creates_default_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "calibration.json"
            ct = CalibrationTracker(config_path=str(config))
            assert ct.get_current_threshold() == 70

    def test_init_loads_existing_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "calibration.json"
            config.write_text(json.dumps({
                "version": "2.0.0",
                "records": [],
                "current_threshold": 85,
                "history": [],
            }))
            ct = CalibrationTracker(config_path=str(config))
            assert ct.get_current_threshold() == 85

    def test_save_persists_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "calibration.json"
            ct = CalibrationTracker(config_path=str(config))
            ct.record_promotion("sum_1", "fact_1", 80.0, "architectural-decision")
            ct.save()

            ct2 = CalibrationTracker(config_path=str(config))
            records = ct2.get_records()
            assert len(records) == 1
            assert records[0]["summary_id"] == "sum_1"


class TestRecordPromotion:
    """Test promotion recording."""

    def test_record_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", 80.0, "architectural-decision")
            records = ct.get_records()
            assert len(records) == 1
            assert records[0]["score"] == 80.0
            assert records[0]["used"] is None

    def test_record_multiple_promotions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", 80.0)
            ct.record_promotion("sum_2", "fact_2", 60.0)
            ct.record_promotion("sum_3", "fact_3", 90.0)
            assert len(ct.get_records()) == 3


class TestMarkUsage:
    """Test marking facts as used/unused."""

    def test_mark_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", 80.0)
            result = ct.mark_used("sum_1", "fact_1")
            assert result is True
            records = ct.get_records(labeled_only=True)
            assert len(records) == 1
            assert records[0]["used"] is True

    def test_mark_unused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", 80.0)
            ct.mark_unused("sum_1", "fact_1")
            records = ct.get_records(labeled_only=True)
            assert len(records) == 1
            assert records[0]["used"] is False

    def test_mark_nonexistent_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            assert ct.mark_used("nonexistent", "nope") is False

    def test_labeled_only_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("sum_1", "fact_1", 80.0)
            ct.record_promotion("sum_2", "fact_2", 60.0)
            ct.mark_used("sum_1", "fact_1")
            all_records = ct.get_records()
            labeled = ct.get_records(labeled_only=True)
            assert len(all_records) == 2
            assert len(labeled) == 1


class TestComputeMetrics:
    """Test precision/recall/F1 computation."""

    def test_metrics_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            metrics = ct.compute_metrics(70)
            assert metrics["support"] == 0

    def test_metrics_perfect_precision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            # All high-scored facts were used
            ct.record_promotion("s1", "f1", 80.0)
            ct.mark_used("s1", "f1")
            ct.record_promotion("s2", "f2", 85.0)
            ct.mark_used("s2", "f2")
            # Low-scored facts not used
            ct.record_promotion("s3", "f3", 40.0)
            ct.mark_unused("s3", "f3")

            metrics = ct.compute_metrics(70)
            assert metrics["precision"] == 1.0  # All promoted were used
            assert metrics["recall"] == 1.0  # All used were above threshold

    def test_metrics_with_false_positives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("s1", "f1", 80.0)
            ct.mark_used("s1", "f1")
            ct.record_promotion("s2", "f2", 85.0)
            ct.mark_unused("s2", "f2")  # High score but not used (FP)

            metrics = ct.compute_metrics(70)
            assert metrics["precision"] == 0.5  # 1 TP / (1 TP + 1 FP)

    def test_f1_score_calculation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("s1", "f1", 80.0)
            ct.mark_used("s1", "f1")

            metrics = ct.compute_metrics(70)
            # With 1 TP, 0 FP, 0 FN: precision=1, recall=1, f1=1
            assert metrics["f1"] == 1.0


class TestOptimalThreshold:
    """Test optimal threshold computation."""

    def test_optimal_with_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            threshold = ct.compute_optimal_threshold()
            assert threshold == 70  # Default

    def test_optimal_finds_best_f1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            # Create data where threshold of 60 is optimal
            for i in range(10):
                ct.record_promotion(f"s{i}", f"f{i}", 65.0 + i)
                ct.mark_used(f"s{i}", f"f{i}")
            for i in range(10, 15):
                ct.record_promotion(f"s{i}", f"f{i}", 30.0 + i)
                ct.mark_unused(f"s{i}", f"f{i}")

            threshold = ct.compute_optimal_threshold()
            assert 40 <= threshold <= 95


class TestCalibrationCurve:
    """Test calibration curve generation."""

    def test_curve_empty_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            curve = ct.compute_calibration_curve()
            assert curve == []

    def test_curve_has_buckets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.record_promotion("s1", "f1", 75.0)
            ct.mark_used("s1", "f1")
            ct.record_promotion("s2", "f2", 25.0)
            ct.mark_unused("s2", "f2")

            curve = ct.compute_calibration_curve(buckets=10)
            assert len(curve) == 10
            assert all("bucket_min" in b and "usage_rate" in b for b in curve)


class TestThresholdUpdate:
    """Test threshold update and history."""

    def test_update_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.update_threshold(80, reason="calibrated")
            assert ct.get_current_threshold() == 80

    def test_update_records_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            ct.update_threshold(80, reason="first update")
            ct.update_threshold(75, reason="second update")
            summary = ct.summary()
            assert summary["history_count"] == 2


class TestCalibrationSummary:
    """Test summary output."""

    def test_summary_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ct = CalibrationTracker(config_path=str(Path(tmpdir) / "cal.json"))
            summary = ct.summary()
            assert "current_threshold" in summary
            assert "total_records" in summary
            assert "labeled_records" in summary
            assert "optimal_threshold" in summary
            assert "metrics_at_current" in summary
