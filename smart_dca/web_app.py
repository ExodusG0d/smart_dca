from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from smart_dca.config import AppConfig, load_config
from smart_dca.core.strategy import PlanRow, StrategyEngine
from smart_dca.data_sources.manual_csv_source import ManualCsvSource
from smart_dca.reports.daily_report import write_daily_report
from smart_dca.storage.db import SQLiteDataSource, SmartDcaDB
from smart_dca.ui.components import (
    explain_plan_row,
    format_currency,
    plan_rows_to_display_frame,
    style_plan_frame,
)


def _configure_page() -> None:
    st.set_page_config(page_title="Smart DCA", page_icon=None, layout="wide")

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px 14px;
            background: #ffffff;
        }
        div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {
            color: #374151 !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #111827 !important;
        }
        div[data-testid="stMetric"] label {
            color: #374151 !important;
        }
        div[data-testid="stDataFrame"] {
            color: #111827;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _load_available_dates(db: SmartDcaDB) -> list[date]:
    db.init_db()
    with db.connect() as connection:
        rows = connection.execute("SELECT DISTINCT date FROM etf_prices ORDER BY date").fetchall()
    return [date.fromisoformat(row["date"]) for row in rows]


def _load_index_history(db: SmartDcaDB, config: AppConfig) -> pd.DataFrame:
    db.init_db()
    index_names = {item.id: item.name for item in config.indices}
    with db.connect() as connection:
        frame = pd.read_sql_query(
            "SELECT date, index_id, close FROM index_prices ORDER BY date, index_id",
            connection,
        )
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    frame["index_name"] = frame["index_id"].map(index_names).fillna(frame["index_id"])
    frame["drawdown"] = frame.groupby("index_id")["close"].transform(lambda values: values / values.cummax() - 1.0)
    return frame


def _load_plan_history(db: SmartDcaDB) -> pd.DataFrame:
    db.init_db()
    with db.connect() as connection:
        frame = pd.read_sql_query(
            """
            SELECT date, etf_id, etf_name, target_amount, actual_amount, deferred_cash, final_multiplier
            FROM plan_results
            ORDER BY date, etf_id
            """,
            connection,
        )
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _build_engine(config: AppConfig) -> StrategyEngine:
    return StrategyEngine(indices=config.indices, etfs=config.etfs, strategy=config.strategy)


def _model_to_dict(model: object) -> dict[str, object]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[no-any-return]
    if hasattr(model, "dict"):
        return model.dict()  # type: ignore[no-any-return]
    raise TypeError(f"Unsupported config model: {type(model)!r}")


def _generate_daily_plan(config: AppConfig, db: SmartDcaDB, selected_date: date) -> tuple[list[PlanRow], Path, Path]:
    data_source = SQLiteDataSource(db)
    engine = _build_engine(config)
    deferred = db.get_deferred_cash_map([etf.id for etf in config.etfs], selected_date)
    remaining_budget = max(0.0, config.strategy.total_budget - db.get_spent_before(selected_date))
    rows = engine.generate_daily_plan(
        target_date=selected_date,
        data_source=data_source,
        deferred_cash=deferred,
        remaining_budget=remaining_budget,
    )
    db.save_plan_rows(rows)
    markdown_path, csv_path = write_daily_report(rows, output_dir=config.strategy.report_dir, report_date=selected_date)
    return rows, markdown_path, csv_path


def _run_backtest(config: AppConfig, db: SmartDcaDB, start: date, end: date) -> pd.DataFrame:
    data_source = SQLiteDataSource(db)
    dates = data_source.available_dates(start, end)
    if not dates:
        return pd.DataFrame()

    db.clear_plan_results(start, end)
    engine = _build_engine(config)
    deferred = db.get_deferred_cash_map([etf.id for etf in config.etfs], start)
    spent = db.get_spent_before(start)
    records = []

    for current_date in dates:
        remaining_budget = max(0.0, config.strategy.total_budget - spent)
        rows = engine.generate_daily_plan(
            target_date=current_date,
            data_source=data_source,
            deferred_cash=deferred,
            remaining_budget=remaining_budget,
        )
        db.save_plan_rows(rows)
        write_daily_report(rows, output_dir=config.strategy.report_dir, report_date=current_date)

        target = sum(row.target_amount for row in rows)
        actual = sum(row.actual_amount for row in rows)
        deferred_total = sum(row.deferred_cash for row in rows)
        spent += actual
        deferred = {row.etf_id: row.deferred_cash for row in rows}
        records.append(
            {
                "日期": current_date,
                "目标金额": round(target, 2),
                "实际金额": round(actual, 2),
                "顺延现金": round(deferred_total, 2),
                "累计投入": round(spent, 2),
            }
        )

    return pd.DataFrame.from_records(records)


def _render_summary(config: AppConfig, db: SmartDcaDB, rows: list[PlanRow], selected_date: date) -> None:
    target_total = sum(row.target_amount for row in rows)
    actual_total = sum(row.actual_amount for row in rows)
    deferred_total = sum(row.deferred_cash for row in rows)
    spent_before = db.get_spent_before(selected_date)
    spent_after = spent_before + actual_total

    columns = st.columns(6)
    columns[0].metric("总预算", format_currency(config.strategy.total_budget))
    columns[1].metric("基础日投", format_currency(config.strategy.base_daily_amount))
    columns[2].metric("今日目标", format_currency(target_total))
    columns[3].metric("今日实际", format_currency(actual_total))
    columns[4].metric("顺延现金", format_currency(deferred_total))
    columns[5].metric("累计投入", format_currency(spent_after))


def _render_plan_table(config: AppConfig, rows: list[PlanRow]) -> None:
    frame = plan_rows_to_display_frame(
        rows,
        premium_block_threshold=config.strategy.premium_block_threshold,
        premium_half_threshold=config.strategy.premium_half_threshold,
    )
    st.dataframe(style_plan_frame(frame), use_container_width=True, hide_index=True)


def _render_explanations(config: AppConfig, rows: list[PlanRow]) -> None:
    for row in rows:
        status = "买入" if row.actual_amount > 0 else "顺延"
        with st.expander(f"{row.etf_id} {row.etf_name}：{status}", expanded=row.actual_amount == 0):
            st.write(
                explain_plan_row(
                    row,
                    premium_block_threshold=config.strategy.premium_block_threshold,
                    premium_half_threshold=config.strategy.premium_half_threshold,
                )
            )


def _render_charts(config: AppConfig, db: SmartDcaDB) -> None:
    index_history = _load_index_history(db, config)
    plan_history = _load_plan_history(db)

    chart_left, chart_right = st.columns(2)

    with chart_left:
        st.subheader("指数走势")
        if index_history.empty:
            st.info("暂无指数数据")
        else:
            figure = px.line(
                index_history,
                x="date",
                y="close",
                color="index_name",
                labels={"date": "日期", "close": "收盘价", "index_name": "指数"},
            )
            figure.update_layout(legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(figure, use_container_width=True)

    with chart_right:
        st.subheader("指数回撤")
        if index_history.empty:
            st.info("暂无回撤数据")
        else:
            figure = px.line(
                index_history,
                x="date",
                y="drawdown",
                color="index_name",
                labels={"date": "日期", "drawdown": "回撤", "index_name": "指数"},
            )
            figure.update_yaxes(tickformat=".0%")
            figure.update_layout(legend_title_text="", margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(figure, use_container_width=True)

    st.subheader("投入与顺延")
    if plan_history.empty:
        st.info("暂无计划历史")
        return

    daily = (
        plan_history.groupby("date", as_index=False)
        .agg({"target_amount": "sum", "actual_amount": "sum", "deferred_cash": "sum"})
        .rename(columns={"target_amount": "目标金额", "actual_amount": "实际金额", "deferred_cash": "顺延现金"})
    )
    figure = go.Figure()
    figure.add_bar(x=daily["date"], y=daily["实际金额"], name="实际金额", marker_color="#0f766e")
    figure.add_scatter(x=daily["date"], y=daily["目标金额"], name="目标金额", mode="lines+markers", line_color="#2563eb")
    figure.add_scatter(x=daily["date"], y=daily["顺延现金"], name="顺延现金", mode="lines+markers", line_color="#d97706")
    figure.update_layout(
        xaxis_title="日期",
        yaxis_title="金额 CNY",
        legend_title_text="",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(figure, use_container_width=True)


def main() -> None:
    _configure_page()
    st.title("Smart DCA")

    with st.sidebar:
        st.header("控制台")
        config_dir_text = st.text_input("配置目录", value="config")
        config_dir = Path(config_dir_text)

    try:
        config = load_config(config_dir)
    except Exception as exc:
        st.error(f"配置加载失败：{exc}")
        st.stop()

    db = SmartDcaDB(config.strategy.db_path)

    with st.sidebar:
        if st.button("初始化数据库", use_container_width=True):
            db.init_db()
            st.success("数据库已初始化")

        if st.button("导入样例数据", use_container_width=True):
            source = ManualCsvSource(config.strategy.data_dir)
            db.import_csv_source(source)
            st.success("样例数据已导入")

    available_dates = _load_available_dates(db)
    if not available_dates:
        st.warning("暂无市场数据，请先在左侧导入样例数据。")
        st.stop()

    with st.sidebar:
        selected_date = st.date_input(
            "计划日期",
            value=max(available_dates),
            min_value=min(available_dates),
            max_value=max(available_dates),
        )
        selected_date = selected_date if isinstance(selected_date, date) else max(available_dates)

        st.divider()
        st.caption("区间回测")
        start_date = st.date_input("开始日期", value=min(available_dates), key="backtest_start")
        end_date = st.date_input("结束日期", value=max(available_dates), key="backtest_end")
        run_backtest = st.button("运行回测", use_container_width=True)

    if run_backtest:
        if end_date < start_date:
            st.error("结束日期不能早于开始日期")
        else:
            summary = _run_backtest(config, db, start_date, end_date)
            if summary.empty:
                st.warning("所选区间没有可用交易日")
            else:
                st.session_state["backtest_summary"] = summary
                st.success("回测完成")

    rows, markdown_path, csv_path = _generate_daily_plan(config, db, selected_date)

    st.caption(f"计划日期：{selected_date.isoformat()}")
    _render_summary(config, db, rows, selected_date)

    st.subheader("今日 ETF 计划")
    _render_plan_table(config, rows)

    csv_bytes = csv_path.read_bytes()
    st.download_button(
        "下载今日计划 CSV",
        data=csv_bytes,
        file_name=csv_path.name,
        mime="text/csv",
        use_container_width=False,
    )
    st.caption(f"报告文件：{markdown_path}")

    st.subheader("原因说明")
    _render_explanations(config, rows)

    if "backtest_summary" in st.session_state:
        st.subheader("回测摘要")
        st.dataframe(st.session_state["backtest_summary"], use_container_width=True, hide_index=True)

    _render_charts(config, db)

    with st.expander("当前配置", expanded=False):
        st.write(
            {
                "total_budget": config.strategy.total_budget,
                "base_trading_days": config.strategy.base_trading_days,
                "base_daily_amount": config.strategy.base_daily_amount,
                "premium_block_threshold": config.strategy.premium_block_threshold,
                "premium_half_threshold": config.strategy.premium_half_threshold,
            }
        )
        st.dataframe(
            pd.DataFrame([_model_to_dict(etf) for etf in config.etfs]),
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":
    main()
