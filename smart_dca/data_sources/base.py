from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd
from pydantic import BaseModel


class ETFPriceRecord(BaseModel):
    date: date
    etf_id: str
    close: float
    premium: float


class ValuationRecord(BaseModel):
    date: date
    index_id: str
    valuation_percentile: float | None


class DataSource(ABC):
    @abstractmethod
    def get_index_prices(self, index_id: str, end_date: date) -> pd.DataFrame:
        """Return index prices on or before end_date with date and close columns."""

    @abstractmethod
    def get_etf_price(self, etf_id: str, target_date: date) -> ETFPriceRecord | None:
        """Return the latest ETF price on or before target_date."""

    @abstractmethod
    def get_valuation(self, index_id: str, target_date: date) -> ValuationRecord | None:
        """Return the latest valuation record on or before target_date."""

    @abstractmethod
    def available_dates(self, start: date, end: date) -> list[date]:
        """Return available trading dates between start and end."""
