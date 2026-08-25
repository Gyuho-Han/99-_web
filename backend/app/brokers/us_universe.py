"""미국주식 데모 유니버스와 거래소 코드 매핑.

KIS 해외주식 API는 종목코드만으로는 조회할 수 없고 거래소 코드(EXCD)를 같이
넘겨야 한다. NAS(나스닥) · NYS(뉴욕) · AMS(아멕스) 세 가지를 쓴다.
실 서비스에서는 증권사 종목 마스터로 대체할 자리다.
"""

from __future__ import annotations

from app.core.config import settings

# 종목코드 -> (종목명, 거래소, 기준가 USD — 시뮬레이터용)
UNIVERSE: dict[str, tuple[str, str, float]] = {
    "AAPL":  ("Apple",            "NAS", 224.50),
    "MSFT":  ("Microsoft",        "NAS", 421.30),
    "NVDA":  ("NVIDIA",           "NAS", 118.70),
    "AMZN":  ("Amazon",           "NAS", 186.40),
    "GOOGL": ("Alphabet",         "NAS", 165.20),
    "META":  ("Meta Platforms",   "NAS", 512.80),
    "TSLA":  ("Tesla",            "NAS", 241.60),
    "JPM":   ("JPMorgan Chase",   "NYS", 214.90),
}


def normalize(symbol: str) -> str:
    return (symbol or "").strip().upper()


def exchange_of(symbol: str) -> str:
    """거래소 코드. 모르는 종목은 .env의 US_DEFAULT_EXCHANGE(기본 NAS)로 둔다."""
    hit = UNIVERSE.get(normalize(symbol))
    return hit[1] if hit else (settings.us_default_exchange or "NAS")


def name_of(symbol: str) -> str:
    hit = UNIVERSE.get(normalize(symbol))
    return hit[0] if hit else normalize(symbol)


def base_price(symbol: str) -> float:
    hit = UNIVERSE.get(normalize(symbol))
    return hit[2] if hit else 100.0
