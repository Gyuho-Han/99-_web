"""Korea Investment Securities OHLCV data loader.

This module keeps API secrets out of source code. Set these environment
variables before calling the loader:

    KIS_APP_KEY
    KIS_APP_SECRET

Optionally set KIS_ACCESS_TOKEN to reuse an already issued token.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests


KIS_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
KIS_TOKEN_PATH = "/oauth2/tokenP"
KIS_DAILY_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
KIS_DAILY_PRICE_TR_ID = "FHKST03010100"

RATE_LIMIT_CODE = "EGW00201"
RATE_LIMIT_WAIT_SECONDS = 61
RATE_LIMIT_MAX_RETRIES = 3


@dataclass(frozen=True)
class KISCredentials:
    """Connection settings for Korea Investment Securities Open API."""

    app_key: str
    app_secret: str
    base_url: str = KIS_REAL_BASE_URL
    access_token: str | None = None
    timeout: float = 10.0

    @classmethod
    def from_env(
        cls,
        *,
        environment: str = "real",
        base_url: str | None = None,
        app_key_env: str = "KIS_APP_KEY",
        app_secret_env: str = "KIS_APP_SECRET",
        access_token_env: str = "KIS_ACCESS_TOKEN",
    ) -> "KISCredentials":
        app_key = os.getenv(app_key_env)
        app_secret = os.getenv(app_secret_env)

        if not app_key or not app_secret:
            raise RuntimeError(
                f"Set {app_key_env} and {app_secret_env} before using KIS API."
            )

        if base_url is None:
            base_url = (
                KIS_PAPER_BASE_URL
                if environment.lower() in {"paper", "demo", "vts"}
                else KIS_REAL_BASE_URL
            )

        return cls(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url.rstrip("/"),
            access_token=os.getenv(access_token_env),
        )


class KISDailyPriceLoader:
    """Fetch domestic daily OHLCV data from KIS Open API."""

    def __init__(
        self,
        credentials: KISCredentials,
        *,
        market: str = "J",
        period: str = "D",
        adjusted_price_code: str = "0",
        sleep_seconds: float = 0.25,
    ) -> None:
        self.credentials = credentials
        self.market = market
        self.period = period
        self.adjusted_price_code = adjusted_price_code
        self.sleep_seconds = sleep_seconds
        self._access_token = credentials.access_token

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start_date: str | date | datetime,
        end_date: str | date | datetime | None = None,
    ) -> pd.DataFrame:
        """Return daily OHLCV as a DataFrame indexed by date.

        The returned columns are always:
            open, high, low, close, volume
        """

        start_str = _to_yyyymmdd(start_date)
        end_str = _to_yyyymmdd(end_date or date.today())
        cursor_end = end_str
        rows: list[dict[str, Any]] = []
        seen_dates: set[str] = set()

        while True:
            page = self._request_daily_page(symbol, start_str, cursor_end)
            page_rows = page.get("output2") or []

            if not page_rows:
                break

            new_count = 0
            page_dates: list[str] = []
            for row in page_rows:
                row_date = str(row.get("stck_bsop_date", ""))
                if not row_date:
                    continue
                page_dates.append(row_date)

                if row_date in seen_dates:
                    continue
                if start_str <= row_date <= end_str:
                    rows.append(row)
                    seen_dates.add(row_date)
                    new_count += 1

            if not page_dates or new_count == 0:
                break

            oldest_date = min(page_dates)
            if oldest_date <= start_str or len(page_rows) < 100:
                break

            cursor_end = (
                datetime.strptime(oldest_date, "%Y%m%d") - timedelta(days=1)
            ).strftime("%Y%m%d")
            time.sleep(self.sleep_seconds)

        return _daily_rows_to_ohlcv(rows, start_str=start_str, end_str=end_str)

    def _request_daily_page(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_access_token()}",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
            "tr_id": KIS_DAILY_PRICE_TR_ID,
            "custtype": "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": self.market,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": self.period,
            "FID_ORG_ADJ_PRC": self.adjusted_price_code,
        }

        last_payload: dict[str, Any] | None = None
        for attempt in range(RATE_LIMIT_MAX_RETRIES):
            response = requests.get(
                self.credentials.base_url + KIS_DAILY_PRICE_PATH,
                headers=headers,
                params=params,
                timeout=self.credentials.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            last_payload = payload

            if payload.get("rt_cd") == "0":
                return payload

            if payload.get("msg_cd") == RATE_LIMIT_CODE:
                if attempt < RATE_LIMIT_MAX_RETRIES - 1:
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)
                    continue

            message = payload.get("msg1") or payload.get("msg_cd") or payload
            raise RuntimeError(f"KIS daily price request failed: {message}")

        raise RuntimeError(f"KIS daily price request failed: {last_payload}")

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        headers = {"content-type": "application/json; charset=utf-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
        }
        response = requests.post(
            self.credentials.base_url + KIS_TOKEN_PATH,
            headers=headers,
            json=body,
            timeout=self.credentials.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        token = payload.get("access_token")
        if not token:
            message = payload.get("msg1") or payload.get("error_description") or payload
            raise RuntimeError(f"KIS access token request failed: {message}")

        self._access_token = token
        return token


def _daily_rows_to_ohlcv(
    rows: list[dict[str, Any]],
    *,
    start_str: str,
    end_str: str,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []

    for row in rows:
        row_date = str(row.get("stck_bsop_date", ""))
        if not (start_str <= row_date <= end_str):
            continue

        records.append(
            {
                "date": datetime.strptime(row_date, "%Y%m%d"),
                "open": _to_number(row.get("stck_oprc")),
                "high": _to_number(row.get("stck_hgpr")),
                "low": _to_number(row.get("stck_lwpr")),
                "close": _to_number(row.get("stck_clpr")),
                "volume": _to_number(row.get("acml_vol")),
            }
        )

    if not records:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame.from_records(records)
    df = df.drop_duplicates(subset="date").set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _to_yyyymmdd(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")

    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return text
    return datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d")


def _to_number(value: Any) -> float:
    if value in {None, ""}:
        return float("nan")
    return float(str(value).replace(",", ""))
