"""Feature engineering utilities for DQN trading state inputs."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .preprocessing import clean_ohlcv


MARKET_FEATURE_GROUPS = {
    "ohlc": [
        "gap_return",
        "intraday_return",
        "high_low_range",
        "close_position",
    ],
    "trend": [
        "close_ma5_ratio",
        "close_ma20_ratio",
        "close_ma60_ratio",
        "close_ma120_ratio",
        "ma5_ma20_ratio",
        "ma20_ma60_ratio",
        "ma60_ma120_ratio",
    ],
    "momentum": [
        "rsi14_norm",
    ],
    "volatility": [
        "atr14_ratio",
    ],
    "volume": [
        "volume_ma20_ratio",
        "volume_change",
    ],
}

MARKET_FEATURES = [
    feature
    for group_features in MARKET_FEATURE_GROUPS.values()
    for feature in group_features
]


def make_features(
    df: pd.DataFrame,
    *,
    selected_features: list[str] | None = None,
    dropna: bool = True,
) -> pd.DataFrame:
    """Create market-state features from OHLCV data.

    All features use only current or past values through rolling windows and
    shifts, so they are safe for chronological train/test splits.
    """

    out = clean_ohlcv(df)
    open_price = out["open"]
    high = out["high"]
    low = out["low"]
    close = out["close"]
    volume = out["volume"]
    previous_close = close.shift(1)

    out["gap_return"] = _safe_ratio(open_price, previous_close) - 1
    out["intraday_return"] = _safe_ratio(close, open_price) - 1
    out["high_low_range"] = _safe_ratio(high, low) - 1
    out["close_position"] = _close_position(close, high, low)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()

    out["close_ma5_ratio"] = _safe_ratio(close, ma5) - 1
    out["close_ma20_ratio"] = _safe_ratio(close, ma20) - 1
    out["close_ma60_ratio"] = _safe_ratio(close, ma60) - 1
    out["close_ma120_ratio"] = _safe_ratio(close, ma120) - 1
    out["ma5_ma20_ratio"] = _safe_ratio(ma5, ma20) - 1
    out["ma20_ma60_ratio"] = _safe_ratio(ma20, ma60) - 1
    out["ma60_ma120_ratio"] = _safe_ratio(ma60, ma120) - 1

    out["rsi14_norm"] = _rsi(close, period=14) / 100.0
    out["atr14_ratio"] = _atr(high, low, previous_close, period=14) / close
    out["volume_ma20_ratio"] = _safe_ratio(volume, volume.rolling(20).mean()) - 1
    out["volume_change"] = _safe_ratio(volume, volume.shift(1)) - 1

    out = out.replace([np.inf, -np.inf], np.nan)
    feature_names = selected_features or MARKET_FEATURES

    if dropna:
        out = out.dropna(subset=feature_names)

    return out


def get_market_feature_names(config: dict[str, Any] | None = None) -> list[str]:
    """Return configured market feature names in model input order."""

    if config is None:
        return MARKET_FEATURES.copy()

    groups = config.get("state", {}).get("market_features", {})
    if not groups:
        return MARKET_FEATURES.copy()

    feature_names: list[str] = []
    for group_features in groups.values():
        feature_names.extend(group_features)
    return feature_names


def infer_state_dim(
    *,
    window: int,
    market_feature_count: int,
    portfolio_feature_count: int,
) -> int:
    """Return flattened DQN state dimension."""

    return window * market_feature_count + portfolio_feature_count


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    return numerator / denominator


def _close_position(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.Series:
    day_range = high - low
    position = (close - low) / day_range.replace(0, np.nan)
    return position.fillna(0.5).clip(lower=0.0, upper=1.0)


def _rsi(close: pd.Series, *, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # No losses means RSI=100, not neutral 50. Preserve initial warm-up NaNs.
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)


def _atr(
    high: pd.Series,
    low: pd.Series,
    previous_close: pd.Series,
    *,
    period: int,
) -> pd.Series:
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()
