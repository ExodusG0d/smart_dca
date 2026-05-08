from smart_dca.core.indicators import (
    drawdown_multiplier,
    final_multiplier,
    trend_multiplier,
    valuation_multiplier,
)


def test_valuation_multiplier() -> None:
    assert valuation_multiplier(0.81) == 0.3
    assert valuation_multiplier(0.80) == 0.6
    assert valuation_multiplier(0.50) == 1.0
    assert valuation_multiplier(0.30) == 1.3
    assert valuation_multiplier(0.19) == 1.6


def test_drawdown_multiplier() -> None:
    assert drawdown_multiplier(0.05) == 0.0
    assert drawdown_multiplier(0.08) == 0.2
    assert drawdown_multiplier(0.15) == 0.5
    assert drawdown_multiplier(0.25) == 0.8
    assert drawdown_multiplier(0.31) == 1.0


def test_trend_multiplier() -> None:
    assert trend_multiplier(0.21) == -0.3
    assert trend_multiplier(0.15) == -0.1
    assert trend_multiplier(0.0) == 0.0
    assert trend_multiplier(-0.15) == 0.2
    assert trend_multiplier(-0.21) == 0.4


def test_final_multiplier_with_valuation() -> None:
    value, missing, valuation_part, drawdown_part, trend_part = final_multiplier(0.30, 0.15, -0.15)
    assert value == 2.0
    assert missing is False
    assert valuation_part == 1.3
    assert drawdown_part == 0.5
    assert trend_part == 0.2


def test_final_multiplier_without_valuation() -> None:
    value, missing, valuation_part, drawdown_part, trend_part = final_multiplier(None, 0.31, -0.21)
    assert value == 2.0
    assert missing is True
    assert valuation_part is None
    assert drawdown_part == 1.0
    assert trend_part == 0.4
