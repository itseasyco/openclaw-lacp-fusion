"""
Config Loader — Load and validate openclaw-lacp plugin configuration.

Reads from openclaw.json plugins.entries.openclaw-lacp-fusion.config
and validates against the expected schema for backend selection.
"""

import json
import os
from pathlib import Path
from typing import Optional

# Default config values
DEFAULTS = {
    "contextEngine": None,
    "lcmDbPath": os.path.expanduser("~/.openclaw/lcm.db"),
    "lcmQueryBatchSize": 50,
    "promotionThreshold": 70,
    "autoDiscoveryInterval": "6h",
    "vaultPath": os.path.expanduser("~/.openclaw/vault"),
    "memoryRoot": os.path.expanduser("~/.openclaw/memory"),
}

# Validation constraints
VALID_CONTEXT_ENGINES = {"lossless-claw", None}
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 1000
MIN_THRESHOLD = 0
MAX_THRESHOLD = 100
VALID_INTERVALS = {"1h", "2h", "4h", "6h", "8h", "12h", "24h"}


class ConfigValidationError(Exception):
    """Raised when plugin configuration is invalid."""


def load_openclaw_lacp_config(
    config_path: Optional[str] = None,
    overrides: Optional[dict] = None,
) -> dict:
    """Load and validate the openclaw-lacp plugin config.

    Resolution order:
        1. Defaults (DEFAULTS dict)
        2. openclaw.json gateway config
        3. Explicit overrides

    Args:
        config_path: Path to openclaw.json. If None, uses
                     ~/.openclaw/openclaw.json.
        overrides: Dict of config overrides (e.g., from CLI flags).

    Returns:
        Validated config dict with all required keys.

    Raises:
        ConfigValidationError: If config values are invalid.
    """
    config = dict(DEFAULTS)

    # Load from gateway config
    gateway_config = _load_gateway_config(config_path)
    if gateway_config:
        config.update(gateway_config)

    # Apply overrides
    if overrides:
        config.update(overrides)

    # Validate
    _validate_config(config)

    return config


def _load_gateway_config(config_path: Optional[str] = None) -> dict:
    """Load the plugin config section from openclaw.json.

    Args:
        config_path: Path to openclaw.json.

    Returns:
        Config dict from the plugin entry, or empty dict.
    """
    if config_path is None:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")

    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Navigate to plugins.entries.openclaw-lacp-fusion.config
        plugin_entry = (
            data
            .get("plugins", {})
            .get("entries", {})
            .get("openclaw-lacp-fusion", {})
        )

        if not plugin_entry.get("enabled", False):
            return {}

        return plugin_entry.get("config", {})
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _validate_config(config: dict) -> None:
    """Validate config values. Raises ConfigValidationError on invalid values.

    Args:
        config: Config dict to validate.

    Raises:
        ConfigValidationError: If any value is invalid.
    """
    errors = []

    # contextEngine
    engine = config.get("contextEngine")
    if engine not in VALID_CONTEXT_ENGINES:
        errors.append(
            f"contextEngine must be 'lossless-claw' or null, got: {engine!r}"
        )

    # lcmQueryBatchSize
    batch_size = config.get("lcmQueryBatchSize")
    if not isinstance(batch_size, (int, float)):
        errors.append(f"lcmQueryBatchSize must be a number, got: {type(batch_size).__name__}")
    elif not (MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE):
        errors.append(
            f"lcmQueryBatchSize must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}, "
            f"got: {batch_size}"
        )

    # promotionThreshold
    threshold = config.get("promotionThreshold")
    if not isinstance(threshold, (int, float)):
        errors.append(f"promotionThreshold must be a number, got: {type(threshold).__name__}")
    elif not (MIN_THRESHOLD <= threshold <= MAX_THRESHOLD):
        errors.append(
            f"promotionThreshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}, "
            f"got: {threshold}"
        )

    # autoDiscoveryInterval
    interval = config.get("autoDiscoveryInterval")
    if isinstance(interval, str) and interval not in VALID_INTERVALS:
        errors.append(
            f"autoDiscoveryInterval must be one of {sorted(VALID_INTERVALS)}, "
            f"got: {interval!r}"
        )

    if errors:
        raise ConfigValidationError(
            "Invalid openclaw-lacp config:\n  " + "\n  ".join(errors)
        )


def get_context_engine_name(config: dict) -> str:
    """Return human-readable name for the active context engine.

    Args:
        config: Validated config dict.

    Returns:
        'lossless-claw' or 'file-based'.
    """
    engine = config.get("contextEngine")
    if engine == "lossless-claw":
        return "lossless-claw"
    return "file-based"
