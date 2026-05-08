from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from smart_dca.config import load_config
from smart_dca.core.strategy import StrategyEngine
from smart_dca.data_sources.manual_csv_source import ManualCsvSource
from smart_dca.reports.daily_report import build_rich_table, write_daily_report
from smart_dca.reports.static_site import build_static_site
from smart_dca.storage.db import SQLiteDataSource, SmartDcaDB

app = typer.Typer(help="Smart DCA planner for index ETFs.")
console = Console()


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{option_name} must use YYYY-MM-DD format") from exc


def _build_engine(config_dir: Path) -> tuple[StrategyEngine, SmartDcaDB, SQLiteDataSource]:
    config = load_config(config_dir)
    db = SmartDcaDB(config.strategy.db_path)
    data_source = SQLiteDataSource(db)
    engine = StrategyEngine(indices=config.indices, etfs=config.etfs, strategy=config.strategy)
    return engine, db, data_source


@app.command("init-db")
def init_db(config_dir: Path = typer.Option(Path("config"), help="Config directory.")) -> None:
    config = load_config(config_dir)
    db = SmartDcaDB(config.strategy.db_path)
    db.init_db()
    console.print(f"Initialized database: {db.path}")


@app.command("import-sample-data")
def import_sample_data(config_dir: Path = typer.Option(Path("config"), help="Config directory.")) -> None:
    config = load_config(config_dir)
    source = ManualCsvSource(config.strategy.data_dir)
    db = SmartDcaDB(config.strategy.db_path)
    db.import_csv_source(source)
    console.print(f"Imported sample CSV data from {config.strategy.data_dir} into {db.path}")


@app.command("web")
def web(
    host: str = typer.Option("localhost", help="Host for the Streamlit server."),
    port: int = typer.Option(8501, help="Port for the Streamlit server."),
) -> None:
    if importlib.util.find_spec("streamlit") is None:
        console.print("Streamlit is not installed. Run `python -m pip install -e .` first.")
        raise typer.Exit(code=1)

    script_path = Path(__file__).with_name("web_app.py")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script_path),
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]
    raise typer.Exit(code=subprocess.call(command))


@app.command("export-site")
def export_site(
    report_date: str | None = typer.Option(None, "--date", help="Static site report date, YYYY-MM-DD."),
    output_dir: Path = typer.Option(Path("docs"), help="Output directory for GitHub Pages static files."),
    config_dir: Path = typer.Option(Path("config"), help="Config directory."),
    import_sample: bool = typer.Option(
        True,
        "--import-sample/--no-import-sample",
        help="Import sample CSV data if the SQLite database is empty.",
    ),
) -> None:
    config = load_config(config_dir)
    parsed_date = None if report_date is None else _parse_date(report_date, "--date")
    result = build_static_site(
        config=config,
        output_dir=output_dir,
        report_date=parsed_date,
        import_sample_if_empty=import_sample,
    )
    console.print(f"Exported static site for {result.report_date.isoformat()}")
    console.print(f"Wrote {result.index_path}")
    console.print(f"Wrote {result.csv_path}")


@app.command("report")
def report(
    report_date: str = typer.Option(..., "--date", help="Report date, YYYY-MM-DD."),
    config_dir: Path = typer.Option(Path("config"), help="Config directory."),
) -> None:
    parsed_date = _parse_date(report_date, "--date")
    config = load_config(config_dir)
    engine, db, data_source = _build_engine(config_dir)
    if not db.has_market_data():
        raise typer.BadParameter("No market data found. Run `smart-dca import-sample-data` first.")

    etf_ids = [etf.id for etf in config.etfs]
    deferred = db.get_deferred_cash_map(etf_ids, parsed_date)
    remaining_budget = max(0.0, config.strategy.total_budget - db.get_spent_before(parsed_date))
    rows = engine.generate_daily_plan(
        target_date=parsed_date,
        data_source=data_source,
        deferred_cash=deferred,
        remaining_budget=remaining_budget,
    )
    db.save_plan_rows(rows)
    markdown_path, csv_path = write_daily_report(rows, output_dir=config.strategy.report_dir, report_date=parsed_date)

    console.print(build_rich_table(rows))
    console.print(f"Wrote {markdown_path}")
    console.print(f"Wrote {csv_path}")


@app.command("backtest")
def backtest(
    start: str = typer.Option(..., "--start", help="Start date, YYYY-MM-DD."),
    end: str = typer.Option(..., "--end", help="End date, YYYY-MM-DD."),
    config_dir: Path = typer.Option(Path("config"), help="Config directory."),
) -> None:
    parsed_start = _parse_date(start, "--start")
    parsed_end = _parse_date(end, "--end")
    if parsed_end < parsed_start:
        raise typer.BadParameter("end must be greater than or equal to start")

    config = load_config(config_dir)
    engine, db, data_source = _build_engine(config_dir)
    if not db.has_market_data():
        raise typer.BadParameter("No market data found. Run `smart-dca import-sample-data` first.")

    dates = data_source.available_dates(parsed_start, parsed_end)
    if not dates:
        console.print("No available ETF price dates in the requested range.")
        raise typer.Exit(code=0)

    db.clear_plan_results(parsed_start, parsed_end)
    deferred = db.get_deferred_cash_map([etf.id for etf in config.etfs], parsed_start)
    spent = db.get_spent_before(parsed_start)
    summary_rows: list[tuple[date, float, float, float]] = []

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
        actual = sum(row.actual_amount for row in rows)
        target = sum(row.target_amount for row in rows)
        deferred_total = sum(row.deferred_cash for row in rows)
        spent += actual
        deferred = {row.etf_id: row.deferred_cash for row in rows}
        summary_rows.append((current_date, target, actual, deferred_total))

    table = Table(title="Smart DCA Backtest")
    table.add_column("Date")
    table.add_column("Target", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Deferred", justify="right")
    for current_date, target, actual, deferred_total in summary_rows:
        table.add_row(current_date.isoformat(), f"{target:.2f}", f"{actual:.2f}", f"{deferred_total:.2f}")
    console.print(table)
    console.print(f"Backtest complete. Spent {spent:.2f} / {config.strategy.total_budget:.2f} CNY.")


if __name__ == "__main__":
    app()
