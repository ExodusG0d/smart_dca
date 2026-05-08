from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from smart_dca.data_sources.base import DataSource, ETFPriceRecord, ValuationRecord


class ManualCsvSource(DataSource):
    def __init__(self, data_dir: str | Path = "data/sample") -> None:
        self.data_dir = Path(data_dir)
        self._index_prices: pd.DataFrame | None = None
        self._etf_prices: pd.DataFrame | None = None
        self._valuations: pd.DataFrame | None = None

    def _read_csv(self, filename: str) -> pd.DataFrame:
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing CSV file: {path}")
        frame = pd.read_csv(path)
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
        return frame

    @property
    def index_prices(self) -> pd.DataFrame:
        if self._index_prices is None:
            self._index_prices = self._read_csv("index_prices.csv")
        return self._index_prices

    @property
    def etf_prices(self) -> pd.DataFrame:
        if self._etf_prices is None:
            self._etf_prices = self._read_csv("etf_prices.csv")
        return self._etf_prices

    @property
    def valuations(self) -> pd.DataFrame:
        if self._valuations is None:
            self._valuations = self._read_csv("valuations.csv")
        return self._valuations

    def get_index_prices(self, index_id: str, end_date: date) -> pd.DataFrame:
        frame = self.index_prices
        result = frame[(frame["index_id"] == index_id) & (frame["date"] <= end_date)]
        return result.sort_values("date").reset_index(drop=True)

    def get_etf_price(self, etf_id: str, target_date: date) -> ETFPriceRecord | None:
        frame = self.etf_prices
        result = frame[(frame["etf_id"].astype(str) == str(etf_id)) & (frame["date"] <= target_date)]
        if result.empty:
            return None
        row = result.sort_values("date").iloc[-1]
        return ETFPriceRecord(
            date=row["date"],
            etf_id=str(row["etf_id"]),
            close=float(row["close"]),
            premium=float(row["premium"]),
        )

    def get_valuation(self, index_id: str, target_date: date) -> ValuationRecord | None:
        frame = self.valuations
        result = frame[(frame["index_id"] == index_id) & (frame["date"] <= target_date)]
        if result.empty:
            return None
        row = result.sort_values("date").iloc[-1]
        value = row.get("valuation_percentile")
        percentile = None if pd.isna(value) else float(value)
        return ValuationRecord(date=row["date"], index_id=str(row["index_id"]), valuation_percentile=percentile)

    def available_dates(self, start: date, end: date) -> list[date]:
        frame = self.etf_prices
        dates = frame[(frame["date"] >= start) & (frame["date"] <= end)]["date"].drop_duplicates()
        return sorted(dates.tolist())
