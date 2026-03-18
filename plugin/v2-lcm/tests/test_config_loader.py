#!/usr/bin/env python3
"""Tests for config_loader — load and validate openclaw-lacp plugin config."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config_loader import (
    load_openclaw_lacp_config,
    ConfigValidationError,
    get_context_engine_name,
    _load_gateway_config,
    DEFAULTS,
)


# ---------------------------------------------------------------------------
# load_openclaw_lacp_config — defaults and merging
# ---------------------------------------------------------------------------

class TestLoadDefaults:
    """Config loading with defaults."""

    def test_returns_defaults_with_no_args(self, tmp_path):
        # Point to a nonexistent config so gateway returns {}
        config = load_openclaw_lacp_config(config_path=str(tmp_path / "missing.json"))
        assert config["contextEngine"] is None
        assert config["lcmQueryBatchSize"] == 50
        assert config["promotionThreshold"] == 70
        assert config["autoDiscoveryInterval"] == "6h"

    def test_reads_from_gateway_config_file(self, tmp_path):
        gw = tmp_path / "openclaw.json"
        gw.write_text(json.dumps({
            "plugins": {
                "entries": {
                    "openclaw-lacp-fusion": {
                        "enabled": True,
                        "config": {
                            "contextEngine": "lossless-claw",
                            "lcmQueryBatchSize": 100,
                        },
                    }
                }
            }
        }))
        config = load_openclaw_lacp_config(config_path=str(gw))
        assert config["contextEngine"] == "lossless-claw"
        assert config["lcmQueryBatchSize"] == 100

    def test_applies_overrides(self, tmp_path):
        config = load_openclaw_lacp_config(
            config_path=str(tmp_path / "missing.json"),
            overrides={"promotionThreshold": 90},
        )
        assert config["promotionThreshold"] == 90

    def test_override_precedence(self, tmp_path):
        gw = tmp_path / "openclaw.json"
        gw.write_text(json.dumps({
            "plugins": {
                "entries": {
                    "openclaw-lacp-fusion": {
                        "enabled": True,
                        "config": {"promotionThreshold": 60},
                    }
                }
            }
        }))
        config = load_openclaw_lacp_config(
            config_path=str(gw),
            overrides={"promotionThreshold": 95},
        )
        # Override wins over gateway config
        assert config["promotionThreshold"] == 95


# ---------------------------------------------------------------------------
# ConfigValidationError cases
# ---------------------------------------------------------------------------

class TestValidation:
    """Validation raises ConfigValidationError on bad values."""

    def test_invalid_context_engine(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="contextEngine"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"contextEngine": "invalid-engine"},
            )

    def test_batch_size_too_low(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="lcmQueryBatchSize"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"lcmQueryBatchSize": 0},
            )

    def test_batch_size_too_high(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="lcmQueryBatchSize"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"lcmQueryBatchSize": 9999},
            )

    def test_batch_size_wrong_type(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="lcmQueryBatchSize"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"lcmQueryBatchSize": "fifty"},
            )

    def test_threshold_too_low(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="promotionThreshold"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"promotionThreshold": -1},
            )

    def test_threshold_zero_is_valid(self, tmp_path):
        config = load_openclaw_lacp_config(
            config_path=str(tmp_path / "x.json"),
            overrides={"promotionThreshold": 0},
        )
        assert config["promotionThreshold"] == 0

    def test_threshold_too_high(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="promotionThreshold"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"promotionThreshold": 101},
            )

    def test_threshold_wrong_type(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="promotionThreshold"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"promotionThreshold": "high"},
            )

    def test_invalid_interval(self, tmp_path):
        with pytest.raises(ConfigValidationError, match="autoDiscoveryInterval"):
            load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"autoDiscoveryInterval": "3h"},
            )


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------

class TestValidConfigs:
    """Configurations that should pass validation."""

    def test_valid_lossless_claw(self, tmp_path):
        config = load_openclaw_lacp_config(
            config_path=str(tmp_path / "x.json"),
            overrides={"contextEngine": "lossless-claw"},
        )
        assert config["contextEngine"] == "lossless-claw"

    def test_valid_null_engine(self, tmp_path):
        config = load_openclaw_lacp_config(
            config_path=str(tmp_path / "x.json"),
            overrides={"contextEngine": None},
        )
        assert config["contextEngine"] is None

    def test_all_valid_intervals(self, tmp_path):
        for interval in ("1h", "2h", "4h", "6h", "8h", "12h", "24h"):
            config = load_openclaw_lacp_config(
                config_path=str(tmp_path / "x.json"),
                overrides={"autoDiscoveryInterval": interval},
            )
            assert config["autoDiscoveryInterval"] == interval


# ---------------------------------------------------------------------------
# get_context_engine_name
# ---------------------------------------------------------------------------

class TestGetContextEngineName:
    """get_context_engine_name returns human-readable names."""

    def test_lossless_claw(self):
        assert get_context_engine_name({"contextEngine": "lossless-claw"}) == "lossless-claw"

    def test_null_engine(self):
        assert get_context_engine_name({"contextEngine": None}) == "file-based"

    def test_missing_key(self):
        assert get_context_engine_name({}) == "file-based"


# ---------------------------------------------------------------------------
# _load_gateway_config
# ---------------------------------------------------------------------------

class TestLoadGatewayConfig:
    """Private _load_gateway_config helper."""

    def test_handles_missing_file(self, tmp_path):
        result = _load_gateway_config(str(tmp_path / "nope.json"))
        assert result == {}

    def test_handles_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json {{!!")
        result = _load_gateway_config(str(f))
        assert result == {}

    def test_handles_disabled_plugin(self, tmp_path):
        f = tmp_path / "disabled.json"
        f.write_text(json.dumps({
            "plugins": {
                "entries": {
                    "openclaw-lacp-fusion": {
                        "enabled": False,
                        "config": {"contextEngine": "lossless-claw"},
                    }
                }
            }
        }))
        result = _load_gateway_config(str(f))
        assert result == {}

    def test_handles_missing_plugin_entry(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text(json.dumps({"plugins": {"entries": {}}}))
        result = _load_gateway_config(str(f))
        assert result == {}

    def test_returns_config_for_enabled_plugin(self, tmp_path):
        f = tmp_path / "good.json"
        f.write_text(json.dumps({
            "plugins": {
                "entries": {
                    "openclaw-lacp-fusion": {
                        "enabled": True,
                        "config": {"lcmQueryBatchSize": 200},
                    }
                }
            }
        }))
        result = _load_gateway_config(str(f))
        assert result == {"lcmQueryBatchSize": 200}
