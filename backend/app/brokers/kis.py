"""한국투자증권 KIS Open API 어댑터.

실계좌(real)와 모의투자(paper)는 도메인과 TR_ID가 다를 뿐 요청 형태가 같으므로
env 값 하나로 분기한다.

주의: KIS는 TR_ID와 응답 필드명을 개편한 이력이 있다. TR_ID는 아래 _TR 표에
모아 두었으니, 연동 전에 KIS 개발자센터 문서와 대조해 한 번 확인하기 바란다.
접근토큰은 발급 제한이 있어 만료 1분 전까지 메모리에 캐시한다.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

import httpx

from app.brokers.base import (
    Balance,
    BalanceItem,
    BrokerAdapter,
    Candle,
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
}

def _num(v, default: float = 0.0) -> float:
    """KIS 응답은 모든 값이 문자열이고, 빈 문자열이 섞여 온다."""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


_token_cache: dict[str, tuple[str, datetime]] = {}
_token_lock = threading.Lock()


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
        self._client = httpx.Client(base_url=self.base, timeout=10.0)

    # -- 인증 ---------------------------------------------------------------
    def _tr(self, key: str) -> str:
        real, paper = _TR[key]
        return paper if self.is_paper else real

    @property
    def _cache_key(self) -> str:
        return f"{self.app_key}:{'paper' if self.is_paper else 'real'}"

    def _access_token(self) -> str:
        with _token_lock:
            hit = _token_cache.get(self._cache_key)
            if hit and hit[1] > datetime.now() + timedelta(minutes=1):
                return hit[0]

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
            token = data.get("access_token")
            if not token:
                raise RuntimeError(data.get("msg1") or "접근토큰 발급에 실패했습니다.")
            expires = datetime.now() + timedelta(seconds=int(data.get("expires_in", 86400)))
            _token_cache[self._cache_key] = (token, expires)
            return token

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
            raise RuntimeError(body.get("msg1") or "시세 조회에 실패했습니다.")
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
            raise RuntimeError(body.get("msg1") or "일봉 조회에 실패했습니다.")
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
