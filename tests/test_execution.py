from smart_dca.core.execution import ExecutionEngine


def test_etf_lot_rounding() -> None:
    result = ExecutionEngine().plan_buy(
        target_amount=550,
        deferred_cash=0,
        etf_price=1.2,
        premium=0.0,
        lot_size=100,
    )
    assert result.actual_shares == 400
    assert result.actual_amount == 480
    assert result.deferred_cash == 70


def test_premium_filter() -> None:
    engine = ExecutionEngine()
    blocked = engine.plan_buy(
        target_amount=500,
        deferred_cash=0,
        etf_price=1.0,
        premium=0.006,
        lot_size=100,
    )
    assert blocked.executable_amount == 0
    assert blocked.actual_amount == 0
    assert blocked.deferred_cash == 500

    halved = engine.plan_buy(
        target_amount=500,
        deferred_cash=0,
        etf_price=1.0,
        premium=0.003,
        lot_size=100,
    )
    assert halved.executable_amount == 250
    assert halved.actual_shares == 200
    assert halved.actual_amount == 200
    assert halved.deferred_cash == 300


def test_deferred_cash() -> None:
    result = ExecutionEngine().plan_buy(
        target_amount=80,
        deferred_cash=10,
        etf_price=1.0,
        premium=0.0,
        lot_size=100,
    )
    assert result.actual_shares == 0
    assert result.deferred_cash == 90


def test_budget_cap() -> None:
    result = ExecutionEngine().plan_buy(
        target_amount=1000,
        deferred_cash=0,
        etf_price=1.0,
        premium=0.0,
        lot_size=100,
        remaining_budget=350,
    )
    assert result.actual_shares == 300
    assert result.actual_amount == 300
    assert result.deferred_cash == 700
