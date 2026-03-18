#!/usr/bin/env python3
"""Tests for confidence calibration module (CalibrationTracker API)."""

import json
import os
import tempfile
import shutil

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from confidence_calibration import CalibrationTracker, DEFAULT_CONFIG_PATH


class TestCalibrationTracker:
    """Test the CalibrationTracker class."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "calibration.json")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_default_threshold(self):
        ct = CalibrationTracker(config_path=self.config_path)
        assert ct.get_current_threshold() == 70

    def test_load_nonexistent_config(self):
        ct = CalibrationTracker(config_path="/nonexistent/config.json")
        assert ct.get_current_threshold() == 70

    def test_save_and_load(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0, "architectural-decision")
        ct.save()

        ct2 = CalibrationTracker(config_path=self.config_path)
        records = ct2.get_records()
        assert len(records) == 1
        assert records[0]["summary_id"] == "sum_1"

    def test_record_promotion(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0, "architectural-decision")
        records = ct.get_records()
        assert len(records) == 1
        assert records[0]["score"] == 80.0
        assert records[0]["used"] is None

    def test_record_multiple_promotions(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0)
        ct.record_promotion("sum_2", "fact_2", 60.0)
        ct.record_promotion("sum_3", "fact_3", 90.0)
        assert len(ct.get_records()) == 3

    def test_mark_used(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0)
        result = ct.mark_used("sum_1", "fact_1")
        assert result is True
        labeled = ct.get_records(labeled_only=True)
        assert len(labeled) == 1
        assert labeled[0]["used"] is True

    def test_mark_unused(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0)
        ct.mark_unused("sum_1", "fact_1")
        labeled = ct.get_records(labeled_only=True)
        assert len(labeled) == 1
        assert labeled[0]["used"] is False

    def test_mark_nonexistent_returns_false(self):
        ct = CalibrationTracker(config_path=self.config_path)
        assert ct.mark_used("nonexistent", "nope") is False

    def test_labeled_only_filter(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("sum_1", "fact_1", 80.0)
        ct.record_promotion("sum_2", "fact_2", 60.0)
        ct.mark_used("sum_1", "fact_1")
        assert len(ct.get_records()) == 2
        assert len(ct.get_records(labeled_only=True)) == 1

    def test_compute_metrics_empty(self):
        ct = CalibrationTracker(config_path=self.config_path)
        metrics = ct.compute_metrics(70)
        assert metrics["support"] == 0

    def test_compute_metrics_perfect(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("s1", "f1", 80.0)
        ct.mark_used("s1", "f1")
        ct.record_promotion("s2", "f2", 85.0)
        ct.mark_used("s2", "f2")
        ct.record_promotion("s3", "f3", 40.0)
        ct.mark_unused("s3", "f3")

        metrics = ct.compute_metrics(70)
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0

    def test_compute_metrics_with_false_positives(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("s1", "f1", 80.0)
        ct.mark_used("s1", "f1")
        ct.record_promotion("s2", "f2", 85.0)
        ct.mark_unused("s2", "f2")

        metrics = ct.compute_metrics(70)
        assert metrics["precision"] == 0.5

    def test_f1_score(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("s1", "f1", 80.0)
        ct.mark_used("s1", "f1")
        metrics = ct.compute_metrics(70)
        assert metrics["f1"] == 1.0

    def test_optimal_threshold_no_data(self):
        ct = CalibrationTracker(config_path=self.config_path)
        assert ct.compute_optimal_threshold() == 70

    def test_optimal_threshold_finds_best_f1(self):
        ct = CalibrationTracker(config_path=self.config_path)
        for i in range(10):
            ct.record_promotion(f"s{i}", f"f{i}", 65.0 + i)
            ct.mark_used(f"s{i}", f"f{i}")
        for i in range(10, 15):
            ct.record_promotion(f"s{i}", f"f{i}", 30.0 + i)
            ct.mark_unused(f"s{i}", f"f{i}")
        threshold = ct.compute_optimal_threshold()
        assert 40 <= threshold <= 95

    def test_calibration_curve_empty(self):
        ct = CalibrationTracker(config_path=self.config_path)
        assert ct.compute_calibration_curve() == []

    def test_calibration_curve_buckets(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.record_promotion("s1", "f1", 75.0)
        ct.mark_used("s1", "f1")
        ct.record_promotion("s2", "f2", 25.0)
        ct.mark_unused("s2", "f2")
        curve = ct.compute_calibration_curve(buckets=10)
        assert len(curve) == 10
        assert all("bucket_min" in b and "usage_rate" in b for b in curve)

    def test_update_threshold(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.update_threshold(80, reason="calibrated")
        assert ct.get_current_threshold() == 80

    def test_update_records_history(self):
        ct = CalibrationTracker(config_path=self.config_path)
        ct.update_threshold(80, reason="first")
        ct.update_threshold(75, reason="second")
        summary = ct.summary()
        assert summary["history_count"] == 2

    def test_summary_structure(self):
        ct = CalibrationTracker(config_path=self.config_path)
        summary = ct.summary()
        assert "current_threshold" in summary
        assert "total_records" in summary
        assert "labeled_records" in summary
        assert "optimal_threshold" in summary
        assert "metrics_at_current" in summary
