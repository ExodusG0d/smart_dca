from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from rich.table import Table

from smart_dca.core.strategy import PlanRow


def rows_to_dataframe(rows: list[PlanRow]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "date": row.date.isoformat(),
                "etf_id": row.etf_id,
                "etf_name": row.etf_name,
                "index_id": row.index_id,
                "index_name": row.index_name,
                "target_amount": round(row.target_amount, 2),
                "deferred_cash_before": round(row.deferred_cash_before, 2),
                "available_amount": round(row.available_amount, 2),
                "executable_amount": round(row.executable_amount, 2),
                "actual_shares": row.actual_shares,
                "actual_amount": round(row.actual_amount, 2),
                "deferred_cash": round(row.deferred_cash, 2),
                "etf_close": round(row.etf_close, 4),
                "premium": round(row.premium, 6),
                "index_close": round(row.index_close, 4),
                "ma_value": None if row.ma_value is None else round(row.ma_value, 4),
                "drawdown": round(row.drawdown, 6),
                "price_ma_ratio": round(row.price_ma_ratio, 6),
                "valuation_percentile": None
                if row.valuation_percentile is None
                else round(row.valuation_percentile, 6),
                "valuation_missing": row.valuation_missing,
                "valuation_multiplier": None
                if row.valuation_multiplier is None
                else round(row.valuation_multiplier, 4),
                "drawdown_multiplier": round(row.drawdown_multiplier, 4),
                "trend_multiplier": round(row.trend_multiplier, 4),
                "final_multiplier": round(row.final_multiplier, 4),
                "reason": row.reason,
            }
        )
    return pd.DataFrame.from_records(records)


def build_rich_table(rows: list[PlanRow]) -> Table:
    table = Table(title="Smart DCA Daily Plan")
    table.add_column("ETF")
    table.add_column("Index")
    table.add_column("Multiplier", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Deferred", justify="right")
    table.add_column("Reason")

    for row in rows:
        table.add_row(
            f"{row.etf_id} {row.etf_name}",
            row.index_name,
            f"{row.final_multiplier:.2f}",
            f"{row.target_amount:.2f}",
            f"{row.actual_amount:.2f}",
            str(row.actual_shares),
            f"{row.deferred_cash:.2f}",
            row.reason,
        )
    return table


def write_daily_report(rows: list[PlanRow], *, output_dir: str | Path, report_date: date | None = None) -> tuple[Path, Path]:
    if not rows and report_date is None:
        raise ValueError("report_date is required when rows is empty")

    date_value = report_date or rows[0].date
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    markdown_path = output_path / f"{date_value.isoformat()}_report.md"
    csv_path = output_path / f"{date_value.isoformat()}_plan.csv"

    frame = rows_to_dataframe(rows)
    frame.to_csv(csv_path, index=False)

    total_target = sum(row.target_amount for row in rows)
    total_actual = sum(row.actual_amount for row in rows)
    total_deferred = sum(row.deferred_cash for row in rows)

    lines = [
        f"# Smart DCA Daily Report - {date_value.isoformat()}",
        "",
        f"- Total target amount: {total_target:.2f} CNY",
        f"- Total actual amount: {total_actual:.2f} CNY",
        f"- Total deferred cash: {total_deferred:.2f} CNY",
        "",
        "| ETF | Index | Multiplier | Target | Actual | Shares | Deferred | Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.etf_id} {row.etf_name} | "
            f"{row.index_name} | "
            f"{row.final_multiplier:.2f} | "
            f"{row.target_amount:.2f} | "
            f"{row.actual_amount:.2f} | "
            f"{row.actual_shares} | "
            f"{row.deferred_cash:.2f} | "
            f"{row.reason} |"
        )
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    return markdown_path, csv_path
