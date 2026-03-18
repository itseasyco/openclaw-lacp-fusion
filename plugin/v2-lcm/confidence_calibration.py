#!/usr/bin/env python3
"""
Confidence Calibration — Dynamic threshold adjustment for promotion scoring.

Tracks which promoted facts were actually used by agents (heuristic: mentioned
in subsequent sessions) and computes calibration curves to optimize thresholds.

Stores calibration data in config/.openclaw-lacp-calibration.json.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_PATH = "~/.openclaw/config/.openclaw-lacp-calibration.json"


class CalibrationTracker:
    """Track fact usage and compute optimal promotion thresholds."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(
            config_path or os.path.expanduser(DEFAULT_CONFIG_PATH)
        )
        self._data = self._load()

    def _load(self) -> dict:
        """Load calibration data from disk."""
        try:
            if self.config_path.exists():
                return json.loads(self.config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {
            "version": "2.0.0",
            "records": [],
            "current_threshold": 70,
            "history": [],
        }

    def save(self) -> None:
        """Persist calibration data to disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(self._data, indent=2, default=str))
        except OSError:
            pass

    def record_promotion(
        self,
        summary_id: str,
        fact_id: str,
        score: float,
        category: str = "",
    ) -> None:
        """Record a fact promotion for later calibration."""
        record = {
            "summary_id": summary_id,
            "fact_id": fact_id,
            "score": score,
            "category": category,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "used": None,
            "used_at": None,
        }
        self._data["records"].append(record)

    def mark_used(self, summary_id: str, fact_id: str) -> bool:
        """Mark a promoted fact as actually used by an agent."""
        for record in self._data["records"]:
            if record["summary_id"] == summary_id and record["fact_id"] == fact_id:
                record["used"] = True
                record["used_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    def mark_unused(self, summary_id: str, fact_id: str) -> bool:
        """Mark a promoted fact as not used (explicitly)."""
        for record in self._data["records"]:
            if record["summary_id"] == summary_id and record["fact_id"] == fact_id:
                record["used"] = False
                return True
        return False

    def get_records(self, labeled_only: bool = False) -> list[dict]:
        """Get calibration records, optionally only labeled ones."""
        if labeled_only:
            return [r for r in self._data["records"] if r.get("used") is not None]
        return list(self._data["records"])

    def compute_metrics(self, threshold: float) -> dict:
        """
        Compute precision, recall, F1 at a given threshold.

        - True Positive: score >= threshold AND was used
        - False Positive: score >= threshold AND was NOT used
        - False Negative: score < threshold AND was used
        - True Negative: score < threshold AND was NOT used
        """
        labeled = self.get_records(labeled_only=True)
        if not labeled:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}

        tp = fp = fn = tn = 0
        for record in labeled:
            above = record["score"] >= threshold
            used = record["used"] is True

            if above and used:
                tp += 1
            elif above and not used:
                fp += 1
            elif not above and used:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        return {
            "threshold": threshold,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "support": len(labeled),
        }

    def compute_optimal_threshold(
        self,
        min_threshold: float = 40,
        max_threshold: float = 95,
        step: float = 5,
    ) -> float:
        """Find the threshold that maximizes F1 score."""
        labeled = self.get_records(labeled_only=True)
        if not labeled:
            return self._data.get("current_threshold", 70)

        best_threshold = self._data.get("current_threshold", 70)
        best_f1 = 0.0

        t = min_threshold
        while t <= max_threshold:
            metrics = self.compute_metrics(t)
            if metrics["f1"] > best_f1:
                best_f1 = metrics["f1"]
                best_threshold = t
            t += step

        return best_threshold

    def compute_calibration_curve(self, buckets: int = 10) -> list[dict]:
        """
        Compute calibration curve: for each score bucket, what fraction was used?

        Returns list of {bucket_min, bucket_max, total, used, usage_rate}.
        """
        labeled = self.get_records(labeled_only=True)
        if not labeled:
            return []

        bucket_size = 100.0 / buckets
        curve = []

        for i in range(buckets):
            bucket_min = i * bucket_size
            bucket_max = (i + 1) * bucket_size

            in_bucket = [
                r for r in labeled
                if bucket_min <= r["score"] < bucket_max
            ]

            total = len(in_bucket)
            used = sum(1 for r in in_bucket if r["used"] is True)

            curve.append({
                "bucket_min": bucket_min,
                "bucket_max": bucket_max,
                "total": total,
                "used": used,
                "usage_rate": round(used / total, 4) if total > 0 else 0.0,
            })

        return curve

    def update_threshold(self, new_threshold: float, reason: str = "") -> None:
        """Update the current threshold and record in history."""
        old_threshold = self._data.get("current_threshold", 70)
        self._data["current_threshold"] = new_threshold
        self._data["history"].append({
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "reason": reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def get_current_threshold(self) -> float:
        """Get the current calibrated threshold."""
        return self._data.get("current_threshold", 70)

    def summary(self) -> dict:
        """Get a summary of calibration state."""
        labeled = self.get_records(labeled_only=True)
        all_records = self.get_records()
        current = self.get_current_threshold()

        return {
            "current_threshold": current,
            "total_records": len(all_records),
            "labeled_records": len(labeled),
            "unlabeled_records": len(all_records) - len(labeled),
            "metrics_at_current": self.compute_metrics(current),
            "optimal_threshold": self.compute_optimal_threshold(),
            "history_count": len(self._data.get("history", [])),
        }
