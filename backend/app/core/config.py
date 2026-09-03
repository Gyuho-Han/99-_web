"""애플리케이션 전역 설정.

민감값(마스터 암호화 키, JWT 시크릿, 증권사 앱키)은 반드시 환경변수 또는 .env로
주입한다. 개발 편의를 위해 값이 없으면 자동 생성하지만, 서버 재시작 시 기존
암호문을 복호화할 수 없으므로 운영에서는 반드시 고정값을 지정해야 한다.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    # 실행 위치와 무관하게 backend/.env 를 읽는다.
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "KAIRO Trading Server"
    version: str = "0.1.0"

    # 보안
    secret_key: str = ""          # JWT 서명 키
    master_key: str = ""          # 브로커 자격증명 암호화 키 (Fernet, base64 32B)
    access_token_ttl_min: int = 60 * 12

    # DB
    database_url: str = f"sqlite:///{DATA_DIR / 'kairo.db'}"

    # 한국투자증권 KIS Open API 엔드포인트
    kis_real_base: str = "https://openapi.koreainvestment.com:9443"
    kis_paper_base: str = "https://openapivts.koreainvestment.com:29443"

    # ------------------------------------------------------------------
    # 서버 공용 KIS 앱키 (.env)
    #
    # 사용자별 자격증명(/keys 화면, DB 암호화 저장)과는 별개로, 서버 전체가
    # 공유하는 시세 조회용 키다. 이 키가 있으면 로그인한 모든 사용자에게
    # 실제 시세가 나가고, 잔고·주문은 그대로 시뮬레이터가 처리한다.
    #
    # 주의: KIS 시세조회 API는 모의투자 도메인(openapivts)에서 지원하지 않는다.
    #       따라서 시세용 키는 실전투자 앱키여야 한다.
    # ------------------------------------------------------------------
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""          # 시세만 쓸 거면 비워 둬도 된다
    kis_market_data: bool = True      # False면 키가 있어도 시뮬레이터 시세를 쓴다
    kis_market_use_paper: bool = False  # 시세 조회 도메인. 기본은 실전.

    # ------------------------------------------------------------------
    # 미국주식 (KIS 해외주식 API)
    #
    # 앱키는 국내와 같은 것을 쓴다. 추가로 발급받을 키는 없다.
    # 다만 잔고·주문까지 붙이려면 해외주식 계좌번호가 따로 필요하고,
    # 미국 실시간 시세는 KIS에서 별도 신청해야 한다(신청 전에는 지연시세).
    # ------------------------------------------------------------------
    kis_overseas_account_no: str = ""   # 예: 50123456-01 (해외주식 계좌)
    us_market_data: bool = True         # False면 미국도 시뮬레이터 시세를 쓴다
    us_default_exchange: str = "NAS"    # NAS(나스닥) · NYS(뉴욕) · AMS(아멕스)
    usd_krw_rate: float = 0.0           # 0이면 환산하지 않고 USD 그대로 표기한다

    # 시세 캐시 TTL(초). KIS는 초당 요청수 제한이 있어 반드시 캐시한다.
    quote_cache_seconds: int = 3
    candle_cache_seconds: int = 300

    # KIS 호출 타임아웃(초). 화면이 멈추지 않으려면 짧아야 한다.
    kis_timeout_seconds: float = 4.0
    # 접근토큰 발급에 실패하면 이 시간 동안은 KIS를 다시 두드리지 않는다.
    # (KIS는 토큰 발급 자체에도 횟수 제한이 있어, 실패를 반복하면 더 오래 막힌다)
    kis_token_retry_seconds: int = 60

    # 에이전트 루프 주기(초). 데모에서는 짧게, 운영에서는 캔들 주기에 맞춘다.
    agent_tick_seconds: int = 5

    # ------------------------------------------------------------------
    # 실거래 안전장치
    #
    # False 이면 실계좌(env=live)에서 주문 전송과 자동매매 가동이 서버에서 막힌다.
    # 자격증명 등록 · 연결 테스트 · 잔고와 시세 조회는 그대로 된다. 즉 실계좌를
    # "붙여 보고 확인"까지는 되지만 "돈이 나가는 것"은 이 스위치를 켜야만 열린다.
    #
    # 코드 한 줄이 아니라 서버 환경변수로 둔 이유는, 프런트엔드나 API 호출만으로는
    # 절대 풀 수 없는 마지막 잠금이 하나 필요하기 때문이다.
    # ------------------------------------------------------------------
    allow_live_trading: bool = False

    # 미체결 주문 체결 폴링 주기(초). 0 이하면 폴러를 띄우지 않는다.
    # KIS 주문 API는 접수만 알려 주므로, 체결 수량·체결가는 따로 조회해야 한다.
    fill_poll_seconds: int = 20
    # 폴링 대상 주문의 최대 나이(일). 이보다 오래된 미체결은 더 이상 조회하지 않는다.
    fill_poll_max_age_days: int = 7

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    @property
    def kis_keys_present(self) -> bool:
        return bool(self.kis_app_key and self.kis_app_secret)

    @property
    def kis_market_ready(self) -> bool:
        """.env 앱키로 국내 실시세를 붙일 수 있는 상태인지."""
        return bool(self.kis_market_data and self.kis_keys_present)

    @property
    def us_market_ready(self) -> bool:
        """.env 앱키로 미국 실시세를 붙일 수 있는 상태인지. 앱키는 국내와 공용이다."""
        return bool(self.us_market_data and self.kis_keys_present)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.secret_key:
        s.secret_key = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
    if not s.master_key:
        s.master_key = os.getenv("MASTER_KEY") or Fernet.generate_key().decode()
    return s


settings = get_settings()
