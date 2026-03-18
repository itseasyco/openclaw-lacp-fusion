# Confidence Calibration — OpenClaw LACP v2.0.0

Dynamic threshold calibration for the promotion scoring pipeline based on historical usage data.

## Overview

The promotion scorer uses a fixed threshold (default: 70) to decide whether LCM session facts should be promoted to persistent LACP memory. Over time, some promoted facts turn out to be useful while others don't. Confidence calibration tracks this feedback and adjusts the threshold to improve promotion quality.

## How It Works

1. **Record Usage** — When a promoted fact is later injected into an LCM session (or manually flagged), its usefulness is recorded via `record_usage(fact_hash, was_useful)`.

2. **Compute Metrics** — Precision is calculated as the ratio of useful promotions to total promotions. This tells us whether the threshold is too low (many useless promotions) or too high (missing useful facts).

3. **Suggest Adjustment** — Based on precision:
   - **Precision < 50%**: Raise threshold by `adjustment_step` (too many bad promotions)
   - **Precision > 90%**: Lower threshold by `adjustment_step` (may be missing good facts)
   - **50%–90%**: Maintain current threshold

4. **Apply Adjustment** — Updates the config file and records the change in calibration history.

## Configuration

```json
{
  "threshold": 70,
  "min_threshold": 40,
  "max_threshold": 95,
  "adjustment_step": 5,
  "min_samples": 10,
  "calibration_history": []
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | `70` | Current promotion threshold (0–100) |
| `min_threshold` | `40` | Floor for automatic adjustment |
| `max_threshold` | `95` | Ceiling for automatic adjustment |
| `adjustment_step` | `5` | Points to adjust per calibration |
| `min_samples` | `10` | Minimum usage records before adjusting |

## Python API

```python
from confidence_calibration import ConfidenceCalibrator, get_calibrated_threshold

# Get current threshold
threshold = get_calibrated_threshold()

# Full calibration workflow
cal = ConfidenceCalibrator()

# Record usage feedback
cal.record_usage("abc123", was_useful=True, context="Used in API design")
cal.record_usage("def456", was_useful=False)

# Check metrics
metrics = cal.compute_metrics()
print(f"Precision: {metrics['precision']:.0%}")

# Get suggestion
suggestion = cal.suggest_adjustment()
print(f"Direction: {suggestion['direction']}")

# Apply if appropriate
result = cal.apply_adjustment()
if result["applied"]:
    print(f"Threshold adjusted to {cal.threshold}")

# View history
curve = cal.get_calibration_curve()
```

## CLI Usage

```bash
# Show calibration metrics
openclaw-lacp-calibrate --show-metrics

# Show calibration curve history
openclaw-lacp-calibrate --show-curve

# Auto-update threshold based on usage data
openclaw-lacp-calibrate --update

# Check metrics at a specific threshold
openclaw-lacp-calibrate --threshold 75 --json
```

## Integration with Promote Pipeline

Use `--calibrate-confidence` to auto-calibrate before promoting:

```bash
openclaw-lacp-promote pipeline \
  --file summary.json \
  --project easy-api \
  --calibrate-confidence
```

This runs `apply_adjustment()` before scoring, dynamically setting the threshold based on accumulated usage feedback.

## Bayesian Interpretation

The calibration system implements a simple frequentist approach (precision-based adjustment) with bounded step sizes. The `min_samples` guard prevents premature adjustments from small sample sizes. The bounded range (`min_threshold` to `max_threshold`) prevents runaway calibration.

For more sophisticated Bayesian updates, the calibration history provides the data needed to fit a posterior distribution over optimal thresholds.
