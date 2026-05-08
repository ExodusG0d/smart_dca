from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def valuation_multiplier(valuation_percentile: float) -> float:
    if valuation_percentile > 0.80:
        return 0.3
    if valuation_percentile >= 0.60:
        return 0.6
    if valuation_percentile >= 0.40:
        return 1.0
    if valuation_percentile >= 0.20:
        return 1.3
    return 1.6


def drawdown_multiplier(drawdown: float) -> float:
    if drawdown <= 0.05:
        return 0.0
    if drawdown <= 0.10:
        return 0.2
    if drawdown <= 0.20:
        return 0.5
    if drawdown <= 0.30:
        return 0.8
    return 1.0


def trend_multiplier(price_vs_ma_ratio: float) -> float:
    if price_vs_ma_ratio > 0.20:
        return -0.3
    if price_vs_ma_ratio > 0.10:
        return -0.1
    if price_vs_ma_ratio >= -0.10:
        return 0.0
    if price_vs_ma_ratio >= -0.20:
        return 0.2
    return 0.4


def calculate_ma(prices: Sequence[float] | pd.Series, window: int = 120) -> float | None:
    series = pd.Series(prices, dtype="float64").dropna()
    if series.empty:
        return None
    lookback = series.tail(window)
    return float(lookback.mean())


def calculate_drawdown(prices: Sequence[float] | pd.Series) -> float:
    series = pd.Series(prices, dtype="float64").dropna()
    if series.empty:
        return 0.0
    current = float(series.iloc[-1])
    peak = float(series.max())
    if peak <= 0 or current >= peak:
        return 0.0
    return 1.0 - current / peak


def price_vs_ma_ratio(price: float, ma_value: float | None) -> float:
    if ma_value is None or ma_value <= 0 or math.isnan(ma_value):
        return 0.0
    return price / ma_value - 1.0


def final_multiplier(
    valuation_percentile: float | None,
    drawdown: float,
    price_ma_ratio: float,
    *,
    with_valuation_min: float = 0.0,
    with_valuation_max: float = 2.5,
    missing_valuation_min: float = 0.3,
    missing_valuation_max: float = 2.0,
) -> tuple[float, bool, float | None, float, float]:
    drawdown_part = drawdown_multiplier(drawdown)
    trend_part = trend_multiplier(price_ma_ratio)

    if valuation_percentile is None or pd.isna(valuation_percentile):
        value = clamp(1.0 + drawdown_part + trend_part, missing_valuation_min, missing_valuation_max)
        return value, True, None, drawdown_part, trend_part

    valuation_part = valuation_multiplier(float(valuation_percentile))
    value = clamp(valuation_part + drawdown_part + trend_part, with_valuation_min, with_valuation_max)
    return value, False, valuation_part, drawdown_part, trend_part
