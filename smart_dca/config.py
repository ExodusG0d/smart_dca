from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class IndexConfig(BaseModel):
    id: str
    name: str
    currency: str = "CNY"
    ma_window: int = 120


class ETFConfig(BaseModel):
    id: str
    name: str
    index_id: str
    allocation_weight: float = 1.0
    currency: str = "CNY"
    lot_size: int = 100


class StrategyConfig(BaseModel):
    total_budget: float = 50_000.0
    base_trading_days: int = 200
    data_dir: Path = Path("data/sample")
    db_path: Path = Path("data/smart_dca.db")
    report_dir: Path = Path("reports/daily")
    premium_block_threshold: float = 0.005
    premium_half_threshold: float = 0.002
    final_multiplier_min: float = 0.0
    final_multiplier_max: float = 2.5
    missing_valuation_multiplier_min: float = 0.3
    missing_valuation_multiplier_max: float = 2.0

    @property
    def base_daily_amount(self) -> float:
        return self.total_budget / self.base_trading_days


class AppConfig(BaseModel):
    indices: list[IndexConfig] = Field(default_factory=list)
    etfs: list[ETFConfig] = Field(default_factory=list)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def load_config(config_dir: str | Path = "config") -> AppConfig:
    root = Path(config_dir)
    indices_data = _load_yaml(root / "indices.yaml")
    etfs_data = _load_yaml(root / "etfs.yaml")
    strategy_data = _load_yaml(root / "strategy.yaml")

    return AppConfig(
        indices=[IndexConfig(**item) for item in indices_data.get("indices", [])],
        etfs=[ETFConfig(**item) for item in etfs_data.get("etfs", [])],
        strategy=StrategyConfig(**strategy_data),
    )
