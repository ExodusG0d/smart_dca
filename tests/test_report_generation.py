from datetime import date

import pandas as pd

from smart_dca.core.strategy import PlanRow
from smart_dca.reports.daily_report import write_daily_report


def test_report_generation(tmp_path) -> None:
    row = PlanRow(
        date=date(2026, 5, 8),
        etf_id="510300",
        etf_name="CSI 300 ETF",
        index_id="csi300",
        index_name="CSI 300",
        target_amount=250.0,
        deferred_cash_before=0.0,
        available_amount=250.0,
        executable_amount=250.0,
        actual_shares=300,
        actual_amount=240.0,
        deferred_cash=10.0,
        etf_close=0.8,
        premium=0.001,
        index_close=3420.0,
        ma_value=3564.0,
        drawdown=0.075,
        price_ma_ratio=-0.04,
        valuation_percentile=0.21,
        valuation_missing=False,
        valuation_multiplier=1.3,
        drawdown_multiplier=0.2,
        trend_multiplier=0.0,
        final_multiplier=1.5,
        reason="sample",
    )

    markdown_path, csv_path = write_daily_report([row], output_dir=tmp_path, report_date=date(2026, 5, 8))

    assert markdown_path.exists()
    assert csv_path.exists()
    assert "Smart DCA Daily Report" in markdown_path.read_text(encoding="utf-8")

    frame = pd.read_csv(csv_path)
    assert frame.loc[0, "etf_id"] == 510300
    assert frame.loc[0, "actual_amount"] == 240.0
