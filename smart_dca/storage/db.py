from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from smart_dca.core.strategy import PlanRow
from smart_dca.data_sources.base import DataSource, ETFPriceRecord, ValuationRecord
from smart_dca.data_sources.manual_csv_source import ManualCsvSource


class SmartDcaDB:
    def __init__(self, path: str | Path = "data/smart_dca.db") -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS index_prices (
                    date TEXT NOT NULL,
                    index_id TEXT NOT NULL,
                    close REAL NOT NULL,
                    PRIMARY KEY (date, index_id)
                );

                CREATE TABLE IF NOT EXISTS etf_prices (
                    date TEXT NOT NULL,
                    etf_id TEXT NOT NULL,
                    close REAL NOT NULL,
                    premium REAL NOT NULL,
                    PRIMARY KEY (date, etf_id)
                );

                CREATE TABLE IF NOT EXISTS valuations (
                    date TEXT NOT NULL,
                    index_id TEXT NOT NULL,
                    valuation_percentile REAL,
                    PRIMARY KEY (date, index_id)
                );

                CREATE TABLE IF NOT EXISTS plan_results (
                    date TEXT NOT NULL,
                    etf_id TEXT NOT NULL,
                    etf_name TEXT NOT NULL,
                    index_id TEXT NOT NULL,
                    index_name TEXT NOT NULL,
                    target_amount REAL NOT NULL,
                    deferred_cash_before REAL NOT NULL,
                    available_amount REAL NOT NULL,
                    executable_amount REAL NOT NULL,
                    actual_shares INTEGER NOT NULL,
                    actual_amount REAL NOT NULL,
                    deferred_cash REAL NOT NULL,
                    etf_close REAL NOT NULL,
                    premium REAL NOT NULL,
                    index_close REAL NOT NULL,
                    ma_value REAL,
                    drawdown REAL NOT NULL,
                    price_ma_ratio REAL NOT NULL,
                    valuation_percentile REAL,
                    valuation_missing INTEGER NOT NULL,
                    valuation_multiplier REAL,
                    drawdown_multiplier REAL NOT NULL,
                    trend_multiplier REAL NOT NULL,
                    final_multiplier REAL NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (date, etf_id)
                );
                """
            )

    def import_csv_source(self, source: ManualCsvSource) -> None:
        self.init_db()
        index_prices = source.index_prices.copy()
        etf_prices = source.etf_prices.copy()
        valuations = source.valuations.copy()
        for frame in (index_prices, etf_prices, valuations):
            frame["date"] = frame["date"].astype(str)

        with self.connect() as connection:
            index_prices.to_sql("_index_prices_import", connection, if_exists="replace", index=False)
            etf_prices.to_sql("_etf_prices_import", connection, if_exists="replace", index=False)
            valuations.to_sql("_valuations_import", connection, if_exists="replace", index=False)
            connection.executescript(
                """
                INSERT OR REPLACE INTO index_prices (date, index_id, close)
                SELECT date, index_id, close FROM _index_prices_import;

                INSERT OR REPLACE INTO etf_prices (date, etf_id, close, premium)
                SELECT date, CAST(etf_id AS TEXT), close, premium FROM _etf_prices_import;

                INSERT OR REPLACE INTO valuations (date, index_id, valuation_percentile)
                SELECT date, index_id, valuation_percentile FROM _valuations_import;

                DROP TABLE _index_prices_import;
                DROP TABLE _etf_prices_import;
                DROP TABLE _valuations_import;
                """
            )

    def has_market_data(self) -> bool:
        self.init_db()
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM etf_prices").fetchone()
        return bool(row and row["count"] > 0)

    def get_previous_deferred_cash(self, etf_id: str, before_date: date) -> float:
        self.init_db()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT deferred_cash
                FROM plan_results
                WHERE etf_id = ? AND date < ?
                ORDER BY date DESC
                LIMIT 1
                """,
                (str(etf_id), before_date.isoformat()),
            ).fetchone()
        return 0.0 if row is None else float(row["deferred_cash"])

    def get_deferred_cash_map(self, etf_ids: Iterable[str], before_date: date) -> dict[str, float]:
        return {str(etf_id): self.get_previous_deferred_cash(str(etf_id), before_date) for etf_id in etf_ids}

    def get_spent_before(self, before_date: date) -> float:
        self.init_db()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(actual_amount), 0) AS spent FROM plan_results WHERE date < ?",
                (before_date.isoformat(),),
            ).fetchone()
        return 0.0 if row is None else float(row["spent"])

    def save_plan_rows(self, rows: Iterable[PlanRow]) -> None:
        self.init_db()
        payload = []
        for row in rows:
            payload.append(
                {
                    "date": row.date.isoformat(),
                    "etf_id": row.etf_id,
                    "etf_name": row.etf_name,
                    "index_id": row.index_id,
                    "index_name": row.index_name,
                    "target_amount": row.target_amount,
                    "deferred_cash_before": row.deferred_cash_before,
                    "available_amount": row.available_amount,
                    "executable_amount": row.executable_amount,
                    "actual_shares": row.actual_shares,
                    "actual_amount": row.actual_amount,
                    "deferred_cash": row.deferred_cash,
                    "etf_close": row.etf_close,
                    "premium": row.premium,
                    "index_close": row.index_close,
                    "ma_value": row.ma_value,
                    "drawdown": row.drawdown,
                    "price_ma_ratio": row.price_ma_ratio,
                    "valuation_percentile": row.valuation_percentile,
                    "valuation_missing": int(row.valuation_missing),
                    "valuation_multiplier": row.valuation_multiplier,
                    "drawdown_multiplier": row.drawdown_multiplier,
                    "trend_multiplier": row.trend_multiplier,
                    "final_multiplier": row.final_multiplier,
                    "reason": row.reason,
                }
            )
        if not payload:
            return

        columns = list(payload[0].keys())
        placeholders = ", ".join(f":{column}" for column in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column not in {"date", "etf_id"})
        sql = (
            f"INSERT INTO plan_results ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, etf_id) DO UPDATE SET {updates}"
        )
        with self.connect() as connection:
            connection.executemany(sql, payload)

    def clear_plan_results(self, start: date, end: date) -> None:
        self.init_db()
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM plan_results WHERE date >= ? AND date <= ?",
                (start.isoformat(), end.isoformat()),
            )


class SQLiteDataSource(DataSource):
    def __init__(self, db: SmartDcaDB) -> None:
        self.db = db

    def get_index_prices(self, index_id: str, end_date: date) -> pd.DataFrame:
        self.db.init_db()
        with self.db.connect() as connection:
            frame = pd.read_sql_query(
                """
                SELECT date, index_id, close
                FROM index_prices
                WHERE index_id = ? AND date <= ?
                ORDER BY date
                """,
                connection,
                params=(index_id, end_date.isoformat()),
            )
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
        return frame

    def get_etf_price(self, etf_id: str, target_date: date) -> ETFPriceRecord | None:
        self.db.init_db()
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT date, etf_id, close, premium
                FROM etf_prices
                WHERE etf_id = ? AND date <= ?
                ORDER BY date DESC
                LIMIT 1
                """,
                (str(etf_id), target_date.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return ETFPriceRecord(
            date=date.fromisoformat(row["date"]),
            etf_id=str(row["etf_id"]),
            close=float(row["close"]),
            premium=float(row["premium"]),
        )

    def get_valuation(self, index_id: str, target_date: date) -> ValuationRecord | None:
        self.db.init_db()
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT date, index_id, valuation_percentile
                FROM valuations
                WHERE index_id = ? AND date <= ?
                ORDER BY date DESC
                LIMIT 1
                """,
                (index_id, target_date.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return ValuationRecord(
            date=date.fromisoformat(row["date"]),
            index_id=str(row["index_id"]),
            valuation_percentile=None if row["valuation_percentile"] is None else float(row["valuation_percentile"]),
        )

    def available_dates(self, start: date, end: date) -> list[date]:
        self.db.init_db()
        with self.db.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT date
                FROM etf_prices
                WHERE date >= ? AND date <= ?
                ORDER BY date
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [date.fromisoformat(row["date"]) for row in rows]
