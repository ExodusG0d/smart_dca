from __future__ import annotations

import math

from pydantic import BaseModel


class ExecutionResult(BaseModel):
    available_amount: float
    executable_amount: float
    actual_shares: int
    actual_amount: float
    deferred_cash: float
    reasons: list[str]


class ExecutionEngine:
    def __init__(self, premium_block_threshold: float = 0.005, premium_half_threshold: float = 0.002) -> None:
        self.premium_block_threshold = premium_block_threshold
        self.premium_half_threshold = premium_half_threshold

    def plan_buy(
        self,
        *,
        target_amount: float,
        deferred_cash: float,
        etf_price: float,
        premium: float,
        lot_size: int = 100,
        remaining_budget: float | None = None,
    ) -> ExecutionResult:
        if etf_price <= 0:
            raise ValueError("ETF price must be positive")
        if lot_size <= 0:
            raise ValueError("lot_size must be positive")

        reasons: list[str] = []
        available_amount = max(0.0, target_amount + deferred_cash)
        lot_amount = etf_price * lot_size

        if available_amount < lot_amount:
            reasons.append("available cash below one lot")
            return ExecutionResult(
                available_amount=available_amount,
                executable_amount=0.0,
                actual_shares=0,
                actual_amount=0.0,
                deferred_cash=available_amount,
                reasons=reasons,
            )

        if premium > self.premium_block_threshold:
            reasons.append("premium above block threshold")
            return ExecutionResult(
                available_amount=available_amount,
                executable_amount=0.0,
                actual_shares=0,
                actual_amount=0.0,
                deferred_cash=available_amount,
                reasons=reasons,
            )

        executable_amount = available_amount
        if premium >= self.premium_half_threshold:
            executable_amount *= 0.5
            reasons.append("premium above half threshold")

        if remaining_budget is not None:
            budget = max(0.0, remaining_budget)
            if budget <= 0:
                reasons.append("budget exhausted")
                return ExecutionResult(
                    available_amount=available_amount,
                    executable_amount=0.0,
                    actual_shares=0,
                    actual_amount=0.0,
                    deferred_cash=available_amount,
                    reasons=reasons,
                )
            if executable_amount > budget:
                executable_amount = budget
                reasons.append("capped by remaining budget")

        lots = math.floor(executable_amount / lot_amount)
        actual_shares = lots * lot_size
        actual_amount = actual_shares * etf_price
        if actual_shares == 0:
            reasons.append("executable cash below one lot after filters")
        elif actual_amount < executable_amount:
            reasons.append("rounded down to lot size")

        deferred = max(0.0, available_amount - actual_amount)
        return ExecutionResult(
            available_amount=available_amount,
            executable_amount=executable_amount,
            actual_shares=actual_shares,
            actual_amount=actual_amount,
            deferred_cash=deferred,
            reasons=reasons,
        )
