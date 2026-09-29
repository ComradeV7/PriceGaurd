"""Tests for configuration loading and validation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from priceguard.config import (
    Config,
    compute_config_hash,
)


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory with valid files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        settings = {
            "seed": 42,
            "base_currency": "USD",
            "lookback_business_days": 90,
            "paths": {
                "data_raw": "data/raw",
                "data_sample": "data/sample",
                "exports": "exports",
                "db": "data/test.db",
            },
            "portfolio": {
                "books": ["Trading-A", "Treasury"],
                "quantity_ranges": {
                    "equity": {"min": 100, "max": 1000},
                    "bond_etf": {"min": 100, "max": 1000},
                    "fx": {"min": 1000, "max": 10000},
                    "bond_l2": {"min": 10, "max": 100},
                    "l3": {"min": 1, "max": 10},
                },
            },
            "mark_noise": {
                "equity": 0.0005,
                "bond_etf": 0.0005,
                "fx": 0.0002,
                "bond_l2": 0.0008,
                "l3_daily_walk": 0.001,
            },
            "yield_curve": {
                "tenors_years": [2, 5, 10, 30],
                "fred_series": ["DGS2", "DGS5", "DGS10", "DGS30"],
            },
        }

        universe = {
            "instruments": [
                {
                    "ticker": "AAPL",
                    "name": "Apple Inc",
                    "asset_class": "equity",
                    "currency": "USD",
                    "fv_level": 1,
                    "ref_source": "yahoo",
                }
            ]
        }

        tolerances = {
            "equity_l1": {"warn_bps": 50, "breach_bps": 100},
            "bond_etf_l1": {"warn_bps": 75, "breach_bps": 150},
            "fx_l1": {"warn_bps": 25, "breach_bps": 50},
            "bond_l2": {"warn_bps": 30, "breach_bps": 75},
            "l3": {"band_pct": 5.0, "daily_move_pct": 2.0},
            "severity": {"critical_multiple": 5},
            "stale": {"min_days": 2, "ref_move_bps": 20},
            "drift": {"consecutive_days": 3},
            "return_outlier": {
                "mad_multiple": 5.0,
                "window_days": 10,
                "min_mad_bps": 10.0,
            },
            "cross_source": {"max_diff_bps": 50},
            "materiality": {"mv_threshold_usd": 10000},
        }

        fault_injection = {
            "injection_rate": 0.04,
            "subtle_fraction": 0.10,
            "fault_type_weights": {
                "STALE": 0.25,
                "FAT_FINGER": 0.25,
                "MISSING": 0.20,
                "DRIFT": 0.20,
                "CURRENCY_MISMATCH": 0.10,
            },
            "fault_parameters": {
                "STALE": {
                    "min_consecutive_days": 2,
                    "max_consecutive_days": 5,
                },
                "FAT_FINGER": {
                    "multipliers": [10, 0.1],
                    "transposition_probability": 0.3,
                },
                "MISSING": {"probability": 1.0},
                "DRIFT": {
                    "min_days": 10,
                    "max_days": 20,
                    "bps_per_day_min": 5,
                    "bps_per_day_max": 15,
                    "target_levels": [2, 3],
                },
                "CURRENCY_MISMATCH": {"target_currencies": ["INR", "USD"]},
            },
        }

        (config_dir / "settings.yaml").write_text(yaml.dump(settings))
        (config_dir / "universe.yaml").write_text(yaml.dump(universe))
        (config_dir / "tolerances.yaml").write_text(yaml.dump(tolerances))
        (config_dir / "fault_injection.yaml").write_text(yaml.dump(fault_injection))

        yield config_dir


def test_valid_config_loads(temp_config_dir):
    """Valid configuration loads successfully."""
    config = Config.load(temp_config_dir)

    assert config.settings.seed == 42
    assert config.settings.base_currency == "USD"
    assert config.settings.lookback_business_days == 90
    assert len(config.universe.instruments) == 1
    assert config.universe.instruments[0].ticker == "AAPL"
    assert config.tolerances.equity_l1.warn_bps == 50
    assert config.tolerances.equity_l1.breach_bps == 100
    assert config.fault_injection.injection_rate == 0.04


def test_invalid_seed_raises_error(temp_config_dir):
    """Invalid seed raises validation error."""
    settings_path = temp_config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text())
    settings["seed"] = -1
    settings_path.write_text(yaml.dump(settings))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_invalid_currency_raises_error(temp_config_dir):
    """Invalid currency raises validation error."""
    settings_path = temp_config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text())
    settings["base_currency"] = "INVALID"
    settings_path.write_text(yaml.dump(settings))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_invalid_asset_class_raises_error(temp_config_dir):
    """Invalid asset class raises validation error."""
    universe_path = temp_config_dir / "universe.yaml"
    universe = yaml.safe_load(universe_path.read_text())
    universe["instruments"][0]["asset_class"] = "invalid_class"
    universe_path.write_text(yaml.dump(universe))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_invalid_fv_level_raises_error(temp_config_dir):
    """Invalid fair value level raises validation error."""
    universe_path = temp_config_dir / "universe.yaml"
    universe = yaml.safe_load(universe_path.read_text())
    universe["instruments"][0]["fv_level"] = 5
    universe_path.write_text(yaml.dump(universe))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_warn_greater_than_breach_raises_error(temp_config_dir):
    """Warning threshold greater than breach raises error."""
    tolerances_path = temp_config_dir / "tolerances.yaml"
    tolerances = yaml.safe_load(tolerances_path.read_text())
    tolerances["equity_l1"]["warn_bps"] = 150
    tolerances["equity_l1"]["breach_bps"] = 100
    tolerances_path.write_text(yaml.dump(tolerances))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_negative_threshold_raises_error(temp_config_dir):
    """Negative threshold raises validation error."""
    tolerances_path = temp_config_dir / "tolerances.yaml"
    tolerances = yaml.safe_load(tolerances_path.read_text())
    tolerances["equity_l1"]["warn_bps"] = -10
    tolerances_path.write_text(yaml.dump(tolerances))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_fault_weights_not_summing_to_one_raises_error(temp_config_dir):
    """Fault weights not summing to 1 raises error."""
    fault_path = temp_config_dir / "fault_injection.yaml"
    fault = yaml.safe_load(fault_path.read_text())
    fault["fault_type_weights"]["STALE"] = 0.50
    fault_path.write_text(yaml.dump(fault))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_config_hash_changes_with_threshold(temp_config_dir):
    """Config hash changes when threshold changes."""
    hash1 = compute_config_hash(temp_config_dir)

    tolerances_path = temp_config_dir / "tolerances.yaml"
    tolerances = yaml.safe_load(tolerances_path.read_text())
    tolerances["equity_l1"]["warn_bps"] = 60
    tolerances_path.write_text(yaml.dump(tolerances))

    hash2 = compute_config_hash(temp_config_dir)

    assert hash1 != hash2


def test_config_hash_is_deterministic(temp_config_dir):
    """Config hash is deterministic."""
    hash1 = compute_config_hash(temp_config_dir)
    hash2 = compute_config_hash(temp_config_dir)

    assert hash1 == hash2


def test_empty_instruments_raises_error(temp_config_dir):
    """Empty instruments list raises error."""
    universe_path = temp_config_dir / "universe.yaml"
    universe = yaml.safe_load(universe_path.read_text())
    universe["instruments"] = []
    universe_path.write_text(yaml.dump(universe))

    with pytest.raises(Exception):
        Config.load(temp_config_dir)


def test_real_config_loads():
    """Real configuration files load successfully."""
    config_dir = Path("config")
    if not config_dir.exists():
        pytest.skip("Config directory not found")

    config = Config.load(config_dir)

    assert config.settings.seed > 0
    assert config.settings.base_currency == "USD"
    assert len(config.universe.instruments) > 0
    assert config.tolerances.equity_l1.warn_bps > 0
    assert config.fault_injection.injection_rate > 0
