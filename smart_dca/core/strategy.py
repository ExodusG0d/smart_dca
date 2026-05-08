from __future__ import annotations

from datetime import date
from typing import Mapping

from pydantic import BaseModel

from smart_dca.config import ETFConfig, IndexConfig, StrategyConfig
from smart_dca.core.execution import ExecutionEngine
from smart_dca.core.indicators import calculate_drawdown, calculate_ma, final_multiplier, price_vs_ma_ratio
from smart_dca.data_sources.base import DataSource


class PlanRow(BaseModel):
    date: date
    etf_id: str
    etf_name: str
    index_id: str
    index_name: str
    target_amount: float
    deferred_cash_before: float
    available_amount: float
    executable_amount: float
    actual_shares: int
    actual_amount: float
    deferred_cash: float
    etf_close: float
    premium: float
    index_close: float
    ma_value: float | None
    drawdown: float
    price_ma_ratio: float
    valuation_percentile: float | None
    valuation_missing: bool
    valuation_multiplier: float | None
    drawdown_multiplier: float
    trend_multiplier: float
    final_multiplier: float
    reason: str


class StrategyEngine:
    def __init__(
        self,
        *,
        indices: list[IndexConfig],
        etfs: list[ETFConfig],
        strategy: StrategyConfig,
        execution_engine: ExecutionEngine | None = None,
    ) -> None:
        self.indices = {item.id: item for item in indices}
        self.etfs = etfs
        self.strategy = strategy
        self.execution_engine = execution_engine or ExecutionEngine(
            premium_block_threshold=strategy.premium_block_threshold,
            premium_half_threshold=strategy.premium_half_threshold,
        )

    def _normalized_weights(self) -> dict[str, float]:
        total = sum(max(0.0, etf.allocation_weight) for etf in self.etfs)
        if total <= 0:
            raise ValueError("At least one ETF allocation_weight must be positive")
        return {etf.id: max(0.0, etf.allocation_weight) / total for etf in self.etfs}

    def generate_daily_plan(
        self,
        *,
        target_date: date,
        data_source: DataSource,
        deferred_cash: Mapping[str, float] | None = None,
        remaining_budget: float | None = None,
    ) -> list[PlanRow]:
        weights = self._normalized_weights()
        deferred_cash = deferred_cash or {}
        remaining = remaining_budget
        rows: list[PlanRow] = []

        for etf in self.etfs:
            index = self.indices.get(etf.index_id)
            if index is None:
                raise ValueError(f"ETF {etf.id} references unknown index_id: {etf.index_id}")

            history = data_source.get_index_prices(index.id, target_date)
            if history.empty:
                raise ValueError(f"No index price data for {index.id} on or before {target_date}")
            current_index_close = float(history.iloc[-1]["close"])
            ma_value = calculate_ma(history["close"], index.ma_window)
            drawdown_value = calculate_drawdown(history["close"])
            ma_ratio = price_vs_ma_ratio(current_index_close, ma_value)

            valuation = data_source.get_valuation(index.id, target_date)
            valuation_percentile = None if valuation is None else valuation.valuation_percentile
            multiplier, valuation_missing, valuation_part, drawdown_part, trend_part = final_multiplier(
                valuation_percentile,
                drawdown_value,
                ma_ratio,
                with_valuation_min=self.strategy.final_multiplier_min,
                with_valuation_max=self.strategy.final_multiplier_max,
                missing_valuation_min=self.strategy.missing_valuation_multiplier_min,
                missing_valuation_max=self.strategy.missing_valuation_multiplier_max,
            )

            etf_price = data_source.get_etf_price(etf.id, target_date)
            if etf_price is None:
                raise ValueError(f"No ETF price data for {etf.id} on or before {target_date}")

            target_amount = self.strategy.base_daily_amount * weights[etf.id] * multiplier
            before_deferred = float(deferred_cash.get(etf.id, 0.0))
            execution = self.execution_engine.plan_buy(
                target_amount=target_amount,
                deferred_cash=before_deferred,
                etf_price=etf_price.close,
                premium=etf_price.premium,
                lot_size=etf.lot_size,
                remaining_budget=remaining,
            )
            if remaining is not None:
                remaining = max(0.0, remaining - execution.actual_amount)

            reasons = [
                f"valuation={'missing' if valuation_missing else f'{valuation_percentile:.1%}'}",
                f"drawdown={drawdown_value:.1%}",
                f"price_vs_ma={ma_ratio:.1%}",
                f"premium={etf_price.premium:.2%}",
            ]
            reasons.extend(execution.reasons)

            rows.append(
                PlanRow(
                    date=target_date,
                    etf_id=etf.id,
                    etf_name=etf.name,
                    index_id=index.id,
                    index_name=index.name,
                    target_amount=target_amount,
                    deferred_cash_before=before_deferred,
                    available_amount=execution.available_amount,
                    executable_amount=execution.executable_amount,
                    actual_shares=execution.actual_shares,
                    actual_amount=execution.actual_amount,
                    deferred_cash=execution.deferred_cash,
                    etf_close=etf_price.close,
                    premium=etf_price.premium,
                    index_close=current_index_close,
                    ma_value=ma_value,
                    drawdown=drawdown_value,
                    price_ma_ratio=ma_ratio,
                    valuation_percentile=valuation_percentile,
                    valuation_missing=valuation_missing,
                    valuation_multiplier=valuation_part,
                    drawdown_multiplier=drawdown_part,
                    trend_multiplier=trend_part,
                    final_multiplier=multiplier,
                    reason="; ".join(reasons),
                )
            )

        return rows
