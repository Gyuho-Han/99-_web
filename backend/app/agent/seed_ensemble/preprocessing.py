"""Preprocessing helpers for cleaning OHLCV market data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean OHLCV DataFrame indexed by trading date.

    The loader should already return this shape, but this function makes the
    downstream feature code tolerant of CSV/API sources with minor differences.
    """

    cleaned = df.copy()
    cleaned.columns = [str(column).strip().lower() for column in cleaned.columns]

    if "date" in cleaned.columns:
        cleaned["date"] = pd.to_datetime(cleaned["date"])
        cleaned = cleaned.set_index("date")
    elif not isinstance(cleaned.index, pd.DatetimeIndex):
        cleaned.index = pd.to_datetime(cleaned.index)

    missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in cleaned]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    cleaned = cleaned.sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]

    for column in REQUIRED_OHLCV_COLUMNS:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
    cleaned = cleaned.dropna(subset=REQUIRED_OHLCV_COLUMNS)

    valid_price = (cleaned[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid_volume = cleaned["volume"] >= 0
    valid_range = (cleaned["high"] >= cleaned[["open", "close", "low"]].max(axis=1)) & (
        cleaned["low"] <= cleaned[["open", "close"]].min(axis=1)
    )
    cleaned = cleaned[valid_price & valid_volume & valid_range & ~cleaned.index.isna()]

    return cleaned[list(REQUIRED_OHLCV_COLUMNS)]


def prepare_splits(
    feature_df: pd.DataFrame, config: dict[str, Any]
) -> dict[str, pd.DataFrame]:
    """Keep trailing context, but begin validation/test execution at their boundary.

    With next-open execution, W preceding rows provide the initial state. Only
    the rows after this context generate evaluation returns or trades.
    """
    window = config["state"]["window"]
    validation_date = pd.Timestamp(config["data"]["validation_start"])
    test_date = pd.Timestamp(config["data"]["split_date"])
    if not feature_df.index.is_monotonic_increasing or not feature_df.index.is_unique:
        raise ValueError("Feature dates must be sorted and unique.")
    if validation_date >= test_date:
        raise ValueError("validation_start must precede split_date.")
    validation_index = int(feature_df.index.searchsorted(validation_date))
    test_index = int(feature_df.index.searchsorted(test_date))
    if validation_index < window + 1 or not validation_index < test_index < len(
        feature_df
    ):
        raise ValueError(
            "Need nonempty train, validation and test periods with enough context."
        )
    return {
        "train": feature_df.iloc[:validation_index].copy(),
        "validation": feature_df.iloc[validation_index - window : test_index].copy(),
        "test": feature_df.iloc[test_index - window :].copy(),
    }
