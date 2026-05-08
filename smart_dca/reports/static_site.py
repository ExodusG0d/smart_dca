from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from smart_dca.config import AppConfig
from smart_dca.core.strategy import PlanRow, StrategyEngine
from smart_dca.data_sources.manual_csv_source import ManualCsvSource
from smart_dca.reports.daily_report import rows_to_dataframe
from smart_dca.storage.db import SQLiteDataSource, SmartDcaDB
from smart_dca.ui.components import classify_plan_row, explain_plan_row, format_currency, format_percent


@dataclass(frozen=True)
class StaticSiteResult:
    index_path: Path
    csv_path: Path
    report_date: date
    rows: list[PlanRow]


def _load_index_history(db: SmartDcaDB, config: AppConfig, end_date: date) -> pd.DataFrame:
    index_names = {item.id: item.name for item in config.indices}
    db.init_db()
    with db.connect() as connection:
        frame = pd.read_sql_query(
            """
            SELECT date, index_id, close
            FROM index_prices
            WHERE date <= ?
            ORDER BY date, index_id
            """,
            connection,
            params=(end_date.isoformat(),),
        )
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    frame["index_name"] = frame["index_id"].map(index_names).fillna(frame["index_id"])
    frame["drawdown"] = frame.groupby("index_id")["close"].transform(lambda values: values / values.cummax() - 1.0)
    return frame


def _latest_available_date(data_source: SQLiteDataSource) -> date:
    dates = data_source.available_dates(date.min, date.max)
    if not dates:
        raise ValueError("No ETF price data available. Import sample data first.")
    return max(dates)


def _run_plan_history(
    *,
    config: AppConfig,
    db: SmartDcaDB,
    target_date: date,
) -> tuple[list[PlanRow], pd.DataFrame]:
    data_source = SQLiteDataSource(db)
    dates = [item for item in data_source.available_dates(date.min, target_date) if item <= target_date]
    if not dates:
        raise ValueError(f"No ETF price data available on or before {target_date.isoformat()}")

    engine = StrategyEngine(indices=config.indices, etfs=config.etfs, strategy=config.strategy)
    db.clear_plan_results(min(dates), target_date)
    deferred = db.get_deferred_cash_map([etf.id for etf in config.etfs], min(dates))
    spent = db.get_spent_before(min(dates))
    final_rows: list[PlanRow] = []
    records: list[dict[str, object]] = []

    for current_date in dates:
        remaining_budget = max(0.0, config.strategy.total_budget - spent)
        rows = engine.generate_daily_plan(
            target_date=current_date,
            data_source=data_source,
            deferred_cash=deferred,
            remaining_budget=remaining_budget,
        )
        db.save_plan_rows(rows)

        target = sum(row.target_amount for row in rows)
        actual = sum(row.actual_amount for row in rows)
        deferred_total = sum(row.deferred_cash for row in rows)
        spent += actual
        deferred = {row.etf_id: row.deferred_cash for row in rows}
        final_rows = rows
        records.append(
            {
                "date": current_date,
                "target_amount": round(target, 2),
                "actual_amount": round(actual, 2),
                "deferred_cash": round(deferred_total, 2),
                "spent": round(spent, 2),
            }
        )

    return final_rows, pd.DataFrame.from_records(records)


def _figure_html(figure: go.Figure) -> str:
    figure.update_layout(
        template="plotly_white",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#111827"},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        margin=dict(l=24, r=20, t=30, b=34),
        legend_title_text="",
    )
    return pio.to_html(
        figure,
        include_plotlyjs=False,
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )


def _build_price_chart(index_history: pd.DataFrame) -> str:
    if index_history.empty:
        return '<p class="empty">暂无指数数据</p>'
    figure = px.line(
        index_history,
        x="date",
        y="close",
        color="index_name",
        labels={"date": "日期", "close": "收盘价", "index_name": "指数"},
    )
    return _figure_html(figure)


def _build_drawdown_chart(index_history: pd.DataFrame) -> str:
    if index_history.empty:
        return '<p class="empty">暂无回撤数据</p>'
    figure = px.line(
        index_history,
        x="date",
        y="drawdown",
        color="index_name",
        labels={"date": "日期", "drawdown": "回撤", "index_name": "指数"},
    )
    figure.update_yaxes(tickformat=".0%")
    return _figure_html(figure)


def _build_cash_chart(plan_history: pd.DataFrame) -> str:
    if plan_history.empty:
        return '<p class="empty">暂无计划历史</p>'
    figure = go.Figure()
    figure.add_bar(
        x=plan_history["date"],
        y=plan_history["actual_amount"],
        name="实际金额",
        marker_color="#0f766e",
    )
    figure.add_scatter(
        x=plan_history["date"],
        y=plan_history["target_amount"],
        name="目标金额",
        mode="lines+markers",
        line_color="#2563eb",
    )
    figure.add_scatter(
        x=plan_history["date"],
        y=plan_history["deferred_cash"],
        name="顺延现金",
        mode="lines+markers",
        line_color="#d97706",
    )
    figure.update_layout(xaxis_title="日期", yaxis_title="金额 CNY")
    return _figure_html(figure)


def _status_class(status: str) -> str:
    return {
        "可买入": "status-buy",
        "溢价过高": "status-blocked",
        "溢价偏高": "status-half",
        "不足一手": "status-small",
        "顺延": "status-deferred",
    }.get(status, "status-deferred")


def _build_plan_table(rows: list[PlanRow], config: AppConfig) -> str:
    headers = [
        "状态",
        "ETF",
        "指数",
        "倍率",
        "目标金额",
        "可执行金额",
        "实际金额",
        "份额",
        "顺延现金",
        "溢价",
        "估值分位",
        "回撤",
        "价格/MA120",
    ]
    body: list[str] = []
    for row in rows:
        status = classify_plan_row(
            row,
            premium_block_threshold=config.strategy.premium_block_threshold,
            premium_half_threshold=config.strategy.premium_half_threshold,
        )
        cells = [
            status,
            f"{row.etf_id} {row.etf_name}",
            row.index_name,
            f"{row.final_multiplier:.2f}",
            format_currency(row.target_amount),
            format_currency(row.executable_amount),
            format_currency(row.actual_amount),
            str(row.actual_shares),
            format_currency(row.deferred_cash),
            format_percent(row.premium),
            format_percent(row.valuation_percentile),
            format_percent(row.drawdown),
            format_percent(row.price_ma_ratio),
        ]
        body.append(
            f'<tr class="{_status_class(status)}">'
            + "".join(f"<td>{escape(cell)}</td>" for cell in cells)
            + "</tr>"
        )

    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(f"<th>{escape(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _build_explanations(rows: list[PlanRow], config: AppConfig) -> str:
    items = []
    for row in rows:
        status = "买入" if row.actual_amount > 0 else "顺延"
        text = explain_plan_row(
            row,
            premium_block_threshold=config.strategy.premium_block_threshold,
            premium_half_threshold=config.strategy.premium_half_threshold,
        )
        items.append(
            '<details class="explanation" open>'
            f"<summary>{escape(row.etf_id)} {escape(row.etf_name)}：{escape(status)}</summary>"
            f"<p>{escape(text)}</p>"
            "</details>"
        )
    return "".join(items)


def _build_config_table(config: AppConfig) -> str:
    rows = []
    for etf in config.etfs:
        rows.append(
            "<tr>"
            f"<td>{escape(etf.id)}</td>"
            f"<td>{escape(etf.name)}</td>"
            f"<td>{escape(etf.index_id)}</td>"
            f"<td>{etf.allocation_weight:.2f}</td>"
            f"<td>{etf.lot_size}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap compact"><table><thead><tr>'
        "<th>ETF</th><th>名称</th><th>指数</th><th>权重</th><th>最小份额</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _render_html(
    *,
    config: AppConfig,
    rows: list[PlanRow],
    plan_history: pd.DataFrame,
    index_history: pd.DataFrame,
    report_date: date,
) -> str:
    target_total = sum(row.target_amount for row in rows)
    actual_total = sum(row.actual_amount for row in rows)
    deferred_total = sum(row.deferred_cash for row in rows)
    spent_total = 0.0 if plan_history.empty else float(plan_history.iloc[-1]["spent"])
    generated_at = date.today().isoformat()

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smart DCA 静态展示</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #111827;
      --muted: #4b5563;
      --line: #d1d5db;
      --head: #111827;
      --accent: #0f766e;
      --buy-bg: #dcfce7;
      --buy-text: #14532d;
      --blocked-bg: #fee2e2;
      --blocked-text: #7f1d1d;
      --half-bg: #fef3c7;
      --half-text: #78350f;
      --deferred-bg: #f3f4f6;
      --deferred-text: #111827;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, "Segoe UI", Arial, "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-end;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(32px, 5vw, 56px);
      letter-spacing: 0;
    }}
    h2 {{
      margin: 32px 0 14px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    p {{
      margin: 0;
    }}
    .muted {{
      color: var(--muted);
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      min-height: 40px;
      padding: 9px 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--text);
      background: #fff;
      text-decoration: none;
      font-weight: 700;
    }}
    .button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(160px, 1fr));
      gap: 14px;
      margin: 18px 0 26px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 96px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-weight: 700;
      font-size: 14px;
      margin-bottom: 10px;
    }}
    .metric strong {{
      color: var(--text);
      font-size: 24px;
      letter-spacing: 0;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1080px;
      font-size: 14px;
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: var(--head);
      color: #f9fafb;
      font-weight: 800;
    }}
    td {{
      color: var(--text);
      font-weight: 650;
    }}
    tr.status-buy td {{
      background: var(--buy-bg);
      color: var(--buy-text);
    }}
    tr.status-blocked td {{
      background: var(--blocked-bg);
      color: var(--blocked-text);
    }}
    tr.status-half td {{
      background: var(--half-bg);
      color: var(--half-text);
    }}
    tr.status-small td, tr.status-deferred td {{
      background: var(--deferred-bg);
      color: var(--deferred-text);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .chart {{
      min-height: 360px;
    }}
    details.explanation {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      margin-bottom: 10px;
    }}
    details.explanation summary {{
      cursor: pointer;
      padding: 13px 16px;
      color: var(--text);
      font-weight: 800;
    }}
    details.explanation p {{
      border-top: 1px solid var(--line);
      padding: 14px 16px 16px;
      color: var(--text);
      font-weight: 600;
    }}
    .compact table {{
      min-width: 620px;
    }}
    footer {{
      margin-top: 30px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 900px) {{
      header {{
        display: block;
      }}
      .actions {{
        justify-content: flex-start;
        margin-top: 16px;
      }}
      .metrics {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 520px) {{
      .metrics {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>Smart DCA</h1>
        <p class="muted">静态展示页 · 计划日期 {report_date.isoformat()} · 生成日期 {generated_at}</p>
      </div>
      <nav class="actions">
        <a class="button primary" href="daily_plan.csv">下载今日计划 CSV</a>
        <a class="button" href="https://github.com/ExodusG0d/smart_dca">GitHub 仓库</a>
      </nav>
    </header>

    <section class="metrics">
      <div class="metric"><span>总预算</span><strong>{escape(format_currency(config.strategy.total_budget))}</strong></div>
      <div class="metric"><span>基础日投</span><strong>{escape(format_currency(config.strategy.base_daily_amount))}</strong></div>
      <div class="metric"><span>今日目标</span><strong>{escape(format_currency(target_total))}</strong></div>
      <div class="metric"><span>今日实际</span><strong>{escape(format_currency(actual_total))}</strong></div>
      <div class="metric"><span>顺延现金</span><strong>{escape(format_currency(deferred_total))}</strong></div>
    </section>

    <section>
      <h2>今日 ETF 计划</h2>
      {_build_plan_table(rows, config)}
    </section>

    <section>
      <h2>原因说明</h2>
      {_build_explanations(rows, config)}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>指数走势</h2>
        <div class="chart">{_build_price_chart(index_history)}</div>
      </div>
      <div class="panel">
        <h2>指数回撤</h2>
        <div class="chart">{_build_drawdown_chart(index_history)}</div>
      </div>
    </section>

    <section class="panel">
      <h2>投入与顺延</h2>
      <div class="chart">{_build_cash_chart(plan_history)}</div>
    </section>

    <section class="panel">
      <h2>当前配置</h2>
      <p class="muted">总预算 {escape(format_currency(config.strategy.total_budget))}，基础定投周期 {config.strategy.base_trading_days} 个交易日，溢价暂停阈值 {format_percent(config.strategy.premium_block_threshold)}。</p>
      <br>
      {_build_config_table(config)}
    </section>

    <footer>
      本页面由 <code>smart-dca export-site</code> 生成，只用于静态展示，不执行真实交易。
    </footer>
  </main>
</body>
</html>
"""


def build_static_site(
    *,
    config: AppConfig,
    output_dir: str | Path = "docs",
    report_date: date | None = None,
    import_sample_if_empty: bool = True,
) -> StaticSiteResult:
    db = SmartDcaDB(config.strategy.db_path)
    if import_sample_if_empty and not db.has_market_data():
        db.import_csv_source(ManualCsvSource(config.strategy.data_dir))

    data_source = SQLiteDataSource(db)
    selected_date = report_date or _latest_available_date(data_source)
    rows, plan_history = _run_plan_history(config=config, db=db, target_date=selected_date)
    index_history = _load_index_history(db, config, selected_date)

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    index_path = target_dir / "index.html"
    csv_path = target_dir / "daily_plan.csv"
    nojekyll_path = target_dir / ".nojekyll"

    rows_to_dataframe(rows).to_csv(csv_path, index=False)
    index_path.write_text(
        _render_html(
            config=config,
            rows=rows,
            plan_history=plan_history,
            index_history=index_history,
            report_date=selected_date,
        ),
        encoding="utf-8",
    )
    nojekyll_path.write_text("", encoding="utf-8")

    return StaticSiteResult(index_path=index_path, csv_path=csv_path, report_date=selected_date, rows=rows)
