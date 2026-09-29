"""Configuration loading and validation."""

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class PathsConfig(BaseModel):
    """File system paths configuration."""

    data_raw: Path = Field(description="Path to raw data cache")
    data_sample: Path = Field(description="Path to sample data")
    exports: Path = Field(description="Path to export outputs")
    db: Path = Field(description="Path to SQLite database")


class QuantityRange(BaseModel):
    """Seeded quantity range for an asset class."""

    min: float = Field(description="Minimum position quantity")
    max: float = Field(description="Maximum position quantity")

    @model_validator(mode="after")
    def validate_range(self) -> "QuantityRange":
        """Validate min <= max and both positive."""
        if self.min <= 0 or self.max <= 0:
            raise ValueError("Quantity range bounds must be positive")
        if self.min > self.max:
            raise ValueError(f"Quantity min ({self.min}) must be <= max ({self.max})")
        return self


class PortfolioConfig(BaseModel):
    """Synthetic portfolio generation configuration."""

    books: list[str] = Field(description="Book labels for positions")
    quantity_ranges: dict[str, QuantityRange] = Field(
        description="Quantity range per asset class"
    )

    @model_validator(mode="after")
    def validate_portfolio(self) -> "PortfolioConfig":
        """Validate books list is not empty."""
        if not self.books:
            raise ValueError("Books list cannot be empty")
        return self


class MarkNoiseConfig(BaseModel):
    """Noise sigmas for synthetic internal marks."""

    equity: float = Field(gt=0)
    bond_etf: float = Field(gt=0)
    fx: float = Field(gt=0)
    bond_l2: float = Field(gt=0)
    l3_daily_walk: float = Field(gt=0)


class YieldCurveConfig(BaseModel):
    """Yield curve tenors for Level 2 bond pricing."""

    tenors_years: list[float] = Field(description="Tenor points in years")
    fred_series: list[str] = Field(description="FRED series per tenor")

    @model_validator(mode="after")
    def validate_curve(self) -> "YieldCurveConfig":
        """Validate tenors and series align and are sorted."""
        if len(self.tenors_years) != len(self.fred_series):
            raise ValueError("tenors_years and fred_series must have same length")
        if self.tenors_years != sorted(self.tenors_years):
            raise ValueError("tenors_years must be sorted ascending")
        if len(self.tenors_years) < 2:
            raise ValueError("At least two tenors are required")
        return self


class SettingsConfig(BaseModel):
    """Runtime settings configuration."""

    seed: int = Field(gt=0, description="Random seed for reproducibility")
    base_currency: str = Field(description="Base currency for reporting")
    lookback_business_days: int = Field(
        gt=0, description="Number of business days to look back"
    )
    paths: PathsConfig
    portfolio: PortfolioConfig
    mark_noise: MarkNoiseConfig
    yield_curve: YieldCurveConfig

    @field_validator("base_currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency code format."""
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()


class InstrumentConfig(BaseModel):
    """Single instrument configuration."""

    ticker: str = Field(description="Instrument ticker symbol")
    name: str = Field(description="Instrument name")
    asset_class: str = Field(description="Asset class category")
    currency: str = Field(description="Instrument currency")
    fv_level: int = Field(ge=1, le=3, description="Fair value hierarchy level")
    ref_source: str = Field(description="Reference data source")
    stooq_symbol: str | None = Field(default=None, description="Stooq symbol mapping")
    coupon: float | None = Field(default=None, description="Bond coupon rate")
    maturity_years: int | None = Field(
        default=None, description="Bond maturity in years"
    )
    maturity_date: date | None = Field(default=None, description="Bond maturity date")
    model_band_pct: float | None = Field(
        default=None, description="L3 model band percentage"
    )
    model_value: float | None = Field(default=None, description="L3 fixed model value")

    @field_validator("coupon")
    @classmethod
    def validate_coupon(cls, v: float | None) -> float | None:
        """Validate coupon rate is positive and below 1."""
        if v is not None and not (0 < v < 1):
            raise ValueError(f"Coupon rate must be in (0, 1), got {v}")
        return v

    @field_validator("model_value")
    @classmethod
    def validate_model_value(cls, v: float | None) -> float | None:
        """Validate model value is positive."""
        if v is not None and v <= 0:
            raise ValueError(f"Model value must be positive, got {v}")
        return v

    @field_validator("asset_class")
    @classmethod
    def validate_asset_class(cls, v: str) -> str:
        """Validate asset class is known."""
        valid_classes = {"equity", "bond_etf", "fx", "bond_l2", "l3"}
        if v not in valid_classes:
            raise ValueError(
                f"Unknown asset class: {v}. Must be one of {valid_classes}"
            )
        return v

    @field_validator("fv_level")
    @classmethod
    def validate_fv_level(cls, v: int) -> int:
        """Validate fair value level."""
        if v not in {1, 2, 3}:
            raise ValueError(f"Invalid fair value level: {v}. Must be 1, 2, or 3")
        return v

    @field_validator("ref_source")
    @classmethod
    def validate_ref_source(cls, v: str) -> str:
        """Validate reference source."""
        valid_sources = {"yahoo", "fred", "fx", "stooq", "none"}
        if v not in valid_sources:
            raise ValueError(
                f"Unknown reference source: {v}. Must be one of {valid_sources}"
            )
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency code format."""
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"Invalid currency code: {v}")
        return v.upper()


class UniverseConfig(BaseModel):
    """Universe of instruments configuration."""

    instruments: list[InstrumentConfig] = Field(description="List of instruments")

    @model_validator(mode="after")
    def validate_instruments(self) -> "UniverseConfig":
        """Validate instrument list is not empty."""
        if len(self.instruments) == 0:
            raise ValueError("Instruments list cannot be empty")
        return self


class ToleranceThreshold(BaseModel):
    """Tolerance threshold for an asset class."""

    warn_bps: float | None = Field(default=None, description="Warning threshold in bps")
    breach_bps: float | None = Field(
        default=None, description="Breach threshold in bps"
    )
    band_pct: float | None = Field(default=None, description="Model band percentage")
    daily_move_pct: float | None = Field(
        default=None, description="Daily move percentage"
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ToleranceThreshold":
        """Validate threshold relationships."""
        if self.warn_bps is not None and self.breach_bps is not None:
            if self.warn_bps <= 0:
                raise ValueError("warn_bps must be positive")
            if self.breach_bps <= 0:
                raise ValueError("breach_bps must be positive")
            if self.warn_bps >= self.breach_bps:
                raise ValueError(
                    f"warn_bps ({self.warn_bps}) must be less than "
                    f"breach_bps ({self.breach_bps})"
                )
        if self.band_pct is not None and self.band_pct <= 0:
            raise ValueError("band_pct must be positive")
        if self.daily_move_pct is not None and self.daily_move_pct <= 0:
            raise ValueError("daily_move_pct must be positive")
        return self


class SeverityConfig(BaseModel):
    """Severity configuration."""

    critical_multiple: float = Field(gt=0, description="Critical severity multiplier")


class StaleConfig(BaseModel):
    """Stale mark detection configuration."""

    min_days: int = Field(gt=0, description="Minimum consecutive stale days")
    ref_move_bps: float = Field(gt=0, description="Reference move threshold in bps")


class DriftConfig(BaseModel):
    """Drift detection configuration."""

    consecutive_days: int = Field(gt=0, description="Minimum consecutive drift days")


class ReturnOutlierConfig(BaseModel):
    """Return outlier detection configuration."""

    mad_multiple: float = Field(gt=0, description="MAD multiple for outlier flag")
    window_days: int = Field(gt=1, description="Rolling window in days")
    min_mad_bps: float = Field(
        ge=0, description="Floor on MAD in bps to avoid quiet-panel flags"
    )


class CrossSourceConfig(BaseModel):
    """Cross-source reference disagreement configuration."""

    max_diff_bps: float = Field(gt=0, description="Max allowed source disagreement")


class MaterialityConfig(BaseModel):
    """Materiality configuration."""

    mv_threshold_usd: float = Field(gt=0, description="MV impact threshold in USD")


class TolerancesConfig(BaseModel):
    """Tolerances configuration."""

    equity_l1: ToleranceThreshold
    bond_etf_l1: ToleranceThreshold
    fx_l1: ToleranceThreshold
    bond_l2: ToleranceThreshold
    l3: ToleranceThreshold
    severity: SeverityConfig
    stale: StaleConfig
    drift: DriftConfig
    return_outlier: ReturnOutlierConfig
    cross_source: CrossSourceConfig
    materiality: MaterialityConfig


class FaultParameters(BaseModel):
    """Parameters for a specific fault type."""

    min_consecutive_days: int | None = None
    max_consecutive_days: int | None = None
    multipliers: list[float] | None = None
    transposition_probability: float | None = None
    probability: float | None = None
    min_days: int | None = None
    max_days: int | None = None
    bps_per_day_min: float | None = None
    bps_per_day_max: float | None = None
    target_levels: list[int] | None = None
    target_currencies: list[str] | None = None


class FaultInjectionConfig(BaseModel):
    """Fault injection configuration."""

    injection_rate: float = Field(
        ge=0, le=1, description="Overall fault injection rate"
    )
    subtle_fraction: float = Field(ge=0, le=1, description="Fraction of subtle faults")
    fault_type_weights: dict[str, float] = Field(
        description="Weights for each fault type"
    )
    fault_parameters: dict[str, FaultParameters] = Field(
        description="Parameters per fault type"
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "FaultInjectionConfig":
        """Validate fault type weights sum to 1."""
        total = sum(self.fault_type_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Fault type weights must sum to 1.0, got {total}")
        return self

    @model_validator(mode="after")
    def validate_fault_types_match(self) -> "FaultInjectionConfig":
        """Validate fault types in weights match parameters."""
        weight_types = set(self.fault_type_weights.keys())
        param_types = set(self.fault_parameters.keys())
        if weight_types != param_types:
            raise ValueError(
                f"Fault types in weights {weight_types} must match "
                f"parameters {param_types}"
            )
        return self


class Config:
    """Main configuration container."""

    def __init__(
        self,
        settings: SettingsConfig,
        universe: UniverseConfig,
        tolerances: TolerancesConfig,
        fault_injection: FaultInjectionConfig,
    ) -> None:
        """Initialize configuration container."""
        self.settings = settings
        self.universe = universe
        self.tolerances = tolerances
        self.fault_injection = fault_injection

    @classmethod
    def load(cls, config_dir: Path) -> "Config":
        """Load all configuration files from directory."""
        settings_path = config_dir / "settings.yaml"
        universe_path = config_dir / "universe.yaml"
        tolerances_path = config_dir / "tolerances.yaml"
        fault_injection_path = config_dir / "fault_injection.yaml"

        settings = SettingsConfig(**_load_yaml(settings_path))
        universe = UniverseConfig(**_load_yaml(universe_path))
        tolerances = TolerancesConfig(**_load_yaml(tolerances_path))
        fault_injection = FaultInjectionConfig(**_load_yaml(fault_injection_path))

        return cls(
            settings=settings,
            universe=universe,
            tolerances=tolerances,
            fault_injection=fault_injection,
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file and return as dictionary."""
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    return data


def compute_config_hash(config_dir: Path) -> str:
    """Compute SHA256 hash of normalized configuration files.

    Hashes all YAML files in the config directory in sorted order.
    """
    hasher = hashlib.sha256()
    yaml_files = sorted(config_dir.glob("*.yaml"))

    for yaml_file in yaml_files:
        with open(yaml_file, encoding="utf-8") as f:
            content = f.read()
        hasher.update(yaml_file.name.encode("utf-8"))
        hasher.update(content.encode("utf-8"))

    return hasher.hexdigest()
