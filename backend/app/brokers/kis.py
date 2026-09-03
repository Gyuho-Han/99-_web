"""한국투자증권 KIS Open API 어댑터.

실계좌(real)와 모의투자(paper)는 도메인과 TR_ID가 다를 뿐 요청 형태가 같으므로
env 값 하나로 분기한다.

주의: KIS는 TR_ID와 응답 필드명을 개편한 이력이 있다. TR_ID는 아래 _TR 표에
모아 두었으니, 연동 전에 KIS 개발자센터 문서와 대조해 한 번 확인하기 바란다.
접근토큰은 발급 제한이 있어 만료 1분 전까지 메모리에 캐시한다.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta

import httpx

from app.brokers.base import (
    Balance,
    BalanceItem,
    BrokerAdapter,
    BrokerError,
    Candle,
    Fill,
    OrderResult,
    Quote,
)
from app.core.config import settings

# (real, paper)
_TR = {
    "quote": ("FHKST01010100", "FHKST01010100"),
    "candles": ("FHKST03010100", "FHKST03010100"),
    "balance": ("TTTC8434R", "VTTC8434R"),
    "buy": ("TTTC0012U", "VTTC0012U"),
    "sell": ("TTTC0011U", "VTTC0011U"),
    "cancel": ("TTTC0013U", "VTTC0013U"),
    "fills": ("TTTC8001R", "VTTC8001R"),
}

def _num(v, default: float = 0.0) -> float:
    """KIS 응답은 모든 값이 문자열이고, 빈 문자열이 섞여 온다."""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# 앱키별 접근토큰 캐시. 프로세스 전체가 공유한다.
_token_cache: dict[str, tuple[str, datetime]] = {}
# 발급 실패 기록: 앱키 -> (재시도 가능 시각, 사유). 실패를 기억해 두지 않으면
# 매 요청마다 KIS를 다시 두드리게 되고, 그동안 화면이 멈춘 것처럼 보인다.
_token_fail: dict[str, tuple[float, str]] = {}
# 앱키별 발급 락. 네트워크 대기를 이 락 안에서 하지 않는 것이 핵심이다.
_token_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _token_locks.get(key)
        if lock is None:
            lock = _token_locks[key] = threading.Lock()
        return lock


def last_token_error(app_key: str, is_paper: bool) -> str | None:
    """가장 최근 토큰 발급 실패 사유. 화면에 왜 시뮬레이터로 내려갔는지 알려 주는 용도."""
    hit = _token_fail.get(f"{app_key}:{'paper' if is_paper else 'real'}")
    return hit[1] if hit and time.time() < hit[0] else None


class KISBroker(BrokerAdapter):
    name = "kis"

    def __init__(self, app_key: str, app_secret: str, account_no: str, is_paper: bool):
        self.app_key = app_key
        self.app_secret = app_secret
        # 계좌번호는 "12345678-01" 형태. 앞 8자리(CANO)와 상품코드(ACNT_PRDT_CD)로 분리한다.
        cleaned = account_no.replace("-", "").strip()
        self.cano = cleaned[:8]
        self.prdt_cd = cleaned[8:] or "01"
        self.is_paper = is_paper
        self.base = settings.kis_paper_base if is_paper else settings.kis_real_base
        # 연결은 더 짧게, 응답 대기는 설정값으로. 길게 잡으면 화면이 그만큼 멈춘다.
        self._client = httpx.Client(
            base_url=self.base,
            timeout=httpx.Timeout(
                settings.kis_timeout_seconds, connect=min(3.0, settings.kis_timeout_seconds)
            ),
        )

    # -- 인증 ---------------------------------------------------------------
    def _tr(self, key: str) -> str:
        real, paper = _TR[key]
        return paper if self.is_paper else real

    @property
    def _cache_key(self) -> str:
        return f"{self.app_key}:{'paper' if self.is_paper else 'real'}"

    def _cached_token(self) -> str | None:
        hit = _token_cache.get(self._cache_key)
        if hit and hit[1] > datetime.now() + timedelta(minutes=1):
            return hit[0]
        return None

    def _access_token(self) -> str:
        """접근토큰. 만료 1분 전까지 캐시한다.

        중요: 발급 네트워크 호출을 락 안에서 하지 않는다. 예전 구현은 전역 락을
        잡은 채로 KIS 응답을 기다렸기 때문에, KIS가 느리면 이 토큰을 쓰는 모든
        요청(대시보드 조회, 에이전트 루프)이 줄줄이 막혀 화면이 멈춘 것처럼 보였다.
        지금은 ① 캐시 확인 → ② 최근 실패면 즉시 실패 → ③ 락을 잡은 스레드 하나만
        발급을 시도하고, 나머지는 기다리지 않고 곧바로 돌아온다.
        """
        key = self._cache_key
        now = time.time()

        token = self._cached_token()
        if token:
            return token

        fail = _token_fail.get(key)
        if fail and now < fail[0]:
            # 최근에 실패했다. 재시도 시각까지는 네트워크를 두드리지 않는다.
            raise BrokerError(fail[1])

        lock = _lock_for(key)
        if not lock.acquire(blocking=False):
            # 다른 스레드가 이미 발급 중. 여기서 기다리면 그만큼 화면이 멈춘다.
            token = self._cached_token()
            if token:
                return token
            raise BrokerError("접근토큰을 발급하는 중입니다. 잠시 후 다시 시도하세요.")

        try:
            token = self._cached_token()   # 락을 기다리는 사이 다른 스레드가 채웠을 수 있다
            if token:
                return token

            try:
                res = self._client.post(
                    "/oauth2/tokenP",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self.app_key,
                        "appsecret": self.app_secret,
                    },
                )
                res.raise_for_status()
                data = res.json()
            except Exception as e:  # noqa: BLE001
                reason = f"접근토큰 발급 실패: {e}"
                _token_fail[key] = (now + settings.kis_token_retry_seconds, reason)
                raise BrokerError(reason) from e

            token = data.get("access_token")
            if not token:
                # KIS는 발급 횟수를 넘기면 EGW00133 같은 코드를 돌려준다.
                reason = data.get("msg1") or "접근토큰 발급에 실패했습니다."
                _token_fail[key] = (now + settings.kis_token_retry_seconds, reason)
                raise BrokerError(reason)

            _token_fail.pop(key, None)
            expires = datetime.now() + timedelta(seconds=int(data.get("expires_in", 86400)))
            _token_cache[key] = (token, expires)
            return token
        finally:
            lock.release()

    def _headers(self, tr_id: str, is_post: bool = False) -> dict[str, str]:
        h = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if is_post:
            h["hashkey"] = ""  # 필요 시 /uapi/hashkey 로 발급해 채운다
        return h

    # -- 조회 ---------------------------------------------------------------
    def verify(self) -> tuple[bool, str]:
        try:
            self._access_token()
            self.get_balance()
            env = "모의투자" if self.is_paper else "실계좌"
            return True, f"{env} 연결에 성공했습니다."
        except httpx.HTTPStatusError as e:
            return False, f"KIS 응답 오류 {e.response.status_code}: 키와 계좌번호를 확인하세요."
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def get_quote(self, symbol: str) -> Quote:
        res = self._client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers(self._tr("quote")),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        res.raise_for_status()
        body = res.json()
        if body.get("rt_cd") not in (None, "0"):
            raise BrokerError(body.get("msg1") or "시세 조회에 실패했습니다.")
        o = body.get("output") or {}

        price = _num(o.get("stck_prpr"))
        # 전일 종가는 기준가(stck_sdpr)를 직접 쓴다. prdy_vrss 는 절대값으로 오고
        # 등락 방향이 prdy_vrss_sign(1·2 상승 / 3 보합 / 4·5 하락)에 따로 실린다.
        prev_close = _num(o.get("stck_sdpr"))
        if prev_close <= 0:
            change = abs(_num(o.get("prdy_vrss")))
            if str(o.get("prdy_vrss_sign", "3")) in ("4", "5"):
                change = -change
            prev_close = price - change

        # hts_kor_isnm 이 종목명. bstp_kor_isnm 은 업종명이라 종목명이 아니다.
        name = o.get("hts_kor_isnm") or o.get("prdt_name") or symbol
        return Quote(
            symbol=symbol,
            name=name.strip() or symbol,
            price=price,
            prev_close=prev_close,
            open=_num(o.get("stck_oprc")),
            high=_num(o.get("stck_hgpr")),
            low=_num(o.get("stck_lwpr")),
            volume=int(_num(o.get("acml_vol"))),
            ts=datetime.now(),
        )

    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        # KIS 일봉 API는 1회 요청당 100건이 상한이다. 그 이상은 구간을 나눠
        # 여러 번 호출해야 하므로, 여기서는 최근 100영업일까지만 돌려준다.
        end = date.today()
        start = end - timedelta(days=int(min(days, 100) * 1.6) + 10)
        res = self._client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers=self._headers(self._tr("candles")),
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",  # 0=수정주가
            },
        )
        res.raise_for_status()
        body = res.json()
        if body.get("rt_cd") not in (None, "0"):
            raise BrokerError(body.get("msg1") or "일봉 조회에 실패했습니다.")
        rows = body.get("output2") or []
        candles = [
            Candle(
                date=datetime.strptime(r["stck_bsop_date"], "%Y%m%d").date().isoformat(),
                open=_num(r.get("stck_oprc")),
                high=_num(r.get("stck_hgpr")),
                low=_num(r.get("stck_lwpr")),
                close=_num(r.get("stck_clpr")),
                volume=int(_num(r.get("acml_vol"))),
            )
            for r in rows
            if r.get("stck_bsop_date") and _num(r.get("stck_clpr")) > 0
        ]
        candles.sort(key=lambda c: c.date)
        return candles[-days:]

    def get_balance(self) -> Balance:
        res = self._client.get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers(self._tr("balance")),
            params={
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.prdt_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        res.raise_for_status()
        body = res.json()
        holdings = [
            BalanceItem(
                symbol=r.get("pdno", ""),
                name=r.get("prdt_name", ""),
                quantity=int(float(r.get("hldg_qty", 0))),
                avg_price=float(r.get("pchs_avg_pric", 0)),
                current_price=float(r.get("prpr", 0)),
            )
            for r in (body.get("output1") or [])
            if int(float(r.get("hldg_qty", 0))) > 0
        ]
        summary = (body.get("output2") or [{}])[0]
        cash = float(summary.get("dnca_tot_amt", 0) or 0)
        return Balance(cash=cash, holdings=holdings)

    # -- 주문 ---------------------------------------------------------------
    def place_order(
        self, symbol: str, side: str, quantity: int, price: float = 0.0, order_type: str = "limit"
    ) -> OrderResult:
        ord_dvsn = "01" if order_type == "market" else "00"  # 01=시장가, 00=지정가
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt_cd,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0" if ord_dvsn == "01" else str(int(price)),
        }
        try:
            res = self._client.post(
                "/uapi/domestic-stock/v1/trading/order-cash",
                headers=self._headers(self._tr("buy" if side == "buy" else "sell"), is_post=True),
                json=payload,
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001
            return OrderResult(ok=False, message=f"주문 전송에 실패했습니다: {e}")

        if body.get("rt_cd") != "0":
            return OrderResult(ok=False, message=body.get("msg1", "주문이 거부되었습니다."))

        out = body.get("output", {}) or {}
        return OrderResult(
            ok=True,
            broker_order_id=out.get("ODNO"),
            filled_quantity=0,  # 접수 시점에는 미체결. 체결은 잔고/체결조회로 갱신한다.
            filled_price=0.0,
            message=body.get("msg1", "주문을 접수했습니다."),
        )

    # -- 체결 조회 -----------------------------------------------------------
    def get_fills(self, broker_order_ids: list[str]) -> dict[str, Fill]:
        """주식일별주문체결조회. 접수만 된 주문의 체결 수량·평균단가를 채운다.

        조회 한 번에 최근 구간의 주문이 통째로 오므로, 주문 하나당 한 번씩 부르지
        않고 받아 온 목록에서 필요한 주문번호만 골라낸다. KIS는 초당 요청 수 제한이
        있어서 이렇게 묶는 편이 안전하다.

        모의투자는 조회 가능 구간이 실전보다 짧다. 못 찾은 주문은 결과에서 빠지고,
        호출한 쪽은 그 주문을 건드리지 않는다.
        """
        wanted = {o for o in broker_order_ids if o}
        if not wanted:
            return {}

        end = date.today()
        start = end - timedelta(days=7)
        try:
            res = self._client.get(
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                headers=self._headers(self._tr("fills")),
                params={
                    "CANO": self.cano,
                    "ACNT_PRDT_CD": self.prdt_cd,
                    "INQR_STRT_DT": start.strftime("%Y%m%d"),
                    "INQR_END_DT": end.strftime("%Y%m%d"),
                    "SLL_BUY_DVSN_CD": "00",   # 00=전체
                    "INQR_DVSN": "00",         # 00=역순
                    "PDNO": "",
                    "CCLD_DVSN": "00",         # 00=전체(체결+미체결)
                    "ORD_GNO_BRNO": "",
                    "ODNO": "",
                    "INQR_DVSN_3": "00",
                    "INQR_DVSN_1": "",
                    "CTX_AREA_FK100": "",
                    "CTX_AREA_NK100": "",
                },
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001
            raise BrokerError(f"체결 조회에 실패했습니다: {e}") from e

        if body.get("rt_cd") not in (None, "0"):
            raise BrokerError(body.get("msg1") or "체결 조회에 실패했습니다.")

        out: dict[str, Fill] = {}
        for r in body.get("output1") or []:
            odno = (r.get("odno") or "").strip()
            # KIS는 주문번호를 0으로 채워 돌려주기도 한다. 접수 응답의 ODNO와
            # 그대로 비교하면 놓치므로 앞자리 0을 떼고도 한 번 맞춰 본다.
            key = odno if odno in wanted else odno.lstrip("0")
            if key not in wanted:
                continue
            out[key] = Fill(
                broker_order_id=key,
                ordered_quantity=int(_num(r.get("ord_qty"))),
                filled_quantity=int(_num(r.get("tot_ccld_qty"))),
                filled_price=_num(r.get("avg_prvs")),
                canceled=str(r.get("cncl_yn", "N")).upper() == "Y",
            )
        return out

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt_cd,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": broker_order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        try:
            res = self._client.post(
                "/uapi/domestic-stock/v1/trading/order-rvsecncl",
                headers=self._headers(self._tr("cancel"), is_post=True),
                json=payload,
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001
            return OrderResult(ok=False, message=f"취소 요청에 실패했습니다: {e}")
        ok = body.get("rt_cd") == "0"
        return OrderResult(ok=ok, broker_order_id=broker_order_id, message=body.get("msg1", ""))
