from __future__ import annotations

import pandas as pd

from smart_dca.core.strategy import PlanRow


def format_currency(value: float) -> str:
    return f"{value:,.2f} CNY"


def format_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2%}"


def classify_plan_row(
    row: PlanRow,
    *,
    premium_block_threshold: float,
    premium_half_threshold: float,
) -> str:
    if row.actual_amount > 0:
        return "可买入"
    if row.premium > premium_block_threshold:
        return "溢价过高"
    if row.premium >= premium_half_threshold:
        return "溢价偏高"
    if row.available_amount < row.etf_close * 100:
        return "不足一手"
    return "顺延"


def explain_plan_row(
    row: PlanRow,
    *,
    premium_block_threshold: float,
    premium_half_threshold: float,
) -> str:
    parts: list[str] = []

    if row.valuation_missing:
        parts.append("估值数据缺失，本次使用中性估值基准")
    else:
        parts.append(f"估值分位为 {format_percent(row.valuation_percentile)}")

    parts.append(f"指数回撤 {format_percent(row.drawdown)}")
    parts.append(f"价格相对 MA120 为 {format_percent(row.price_ma_ratio)}")

    if row.premium > premium_block_threshold:
        parts.append(
            f"ETF 溢价 {format_percent(row.premium)} 超过 {format_percent(premium_block_threshold)}，今日暂停买入"
        )
    elif row.premium >= premium_half_threshold:
        parts.append(
            f"ETF 溢价 {format_percent(row.premium)} 偏高，可执行金额按 50% 处理"
        )
    else:
        parts.append(f"ETF 溢价 {format_percent(row.premium)} 在可接受范围内")

    if row.actual_amount > 0:
        parts.append(
            f"按每手 100 份向下取整后，计划买入 {row.actual_shares} 份，金额 {format_currency(row.actual_amount)}"
        )
    elif row.available_amount < row.etf_close * 100:
        parts.append("可用金额不足买入 1 手，本次资金顺延")
    elif row.premium <= premium_block_threshold:
        parts.append("过滤和取整后未形成有效买入，资金顺延")

    return "；".join(parts) + "。"


def plan_rows_to_display_frame(
    rows: list[PlanRow],
    *,
    premium_block_threshold: float,
    premium_half_threshold: float,
) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "状态": classify_plan_row(
                    row,
                    premium_block_threshold=premium_block_threshold,
                    premium_half_threshold=premium_half_threshold,
                ),
                "ETF": f"{row.etf_id} {row.etf_name}",
                "指数": row.index_name,
                "倍率": round(row.final_multiplier, 2),
                "目标金额": round(row.target_amount, 2),
                "可用金额": round(row.available_amount, 2),
                "可执行金额": round(row.executable_amount, 2),
                "实际金额": round(row.actual_amount, 2),
                "份额": row.actual_shares,
                "顺延现金": round(row.deferred_cash, 2),
                "溢价": format_percent(row.premium),
                "估值分位": format_percent(row.valuation_percentile),
                "回撤": format_percent(row.drawdown),
                "价格/MA120": format_percent(row.price_ma_ratio),
                "原因": row.reason,
            }
        )
    return pd.DataFrame.from_records(records)


def style_plan_frame(frame: pd.DataFrame) -> pd.io.formats.style.Styler:
    colors = {
        "可买入": "background-color: #dcfce7; color: #14532d",
        "溢价过高": "background-color: #fee2e2; color: #7f1d1d",
        "溢价偏高": "background-color: #fef3c7; color: #78350f",
        "不足一手": "background-color: #f3f4f6; color: #111827",
        "顺延": "background-color: #f3f4f6; color: #111827",
    }

    def style_row(row: pd.Series) -> list[str]:
        return [colors.get(str(row.get("状态")), "") for _ in row]

    return (
        frame.style.apply(style_row, axis=1)
        .set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#111827"),
                        ("color", "#f9fafb"),
                        ("font-weight", "700"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [
                        ("font-weight", "600"),
                    ],
                },
            ]
        )
    )
