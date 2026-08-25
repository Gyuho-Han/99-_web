"""한국투자증권 KIS 해외주식(미국) 어댑터.

국내주식 어댑터(kis.py)와 앱키·토큰을 공유하고 엔드포인트만 다르다.
따라서 추가로 발급받아야 하는 API 키는 없다. 잔고·주문까지 쓰려면
해외주식 계좌번호(KIS_OVERSEAS_ACCOUNT_NO)만 있으면 된다.

국내와 다른 점
  · 조회 시 거래소 코드(EXCD: NAS · NYS · AMS)를 함께 넘겨야 한다
  · 금액이 USD이고 소수점 둘째 자리까지 쓴다 (국내는 원 단위 정수)
  · 주문 TR_ID가 매수/매도로 갈린다 (국내는 ORD_DVSN으로 갈림)

주의: KIS는 TR_ID와 응답 필드명을 개편한 이력이 있다. 아래 _TR 표를 연동 전에
KIS 개발자센터 최신 문서와 한 번 대조하기 바란다. 특히 주문·취소 TR_ID가 그렇다.
"""

from __future__ import annotations

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
from app.brokers.kis import _num, KISBroker
from app.brokers.us_universe import exchange_of, name_of, normalize
from app.core.config import settings

# (real, paper) — 미국 시장 기준
_TR = {
    "quote":   ("HHDFS00000300", "HHDFS00000300"),
    "candles": ("HHDFS76240000", "HHDFS76240000"),
    "balance": ("TTTS3012R", "VTTS3012R"),
    "buy":     ("TTTT1002U", "VTTT1002U"),
    "sell":    ("TTTT1006U", "VTTT1001U"),
    "cancel":  ("TTTT1004U", "VTTT1004U"),
}


class KISOverseasBroker(BrokerAdapter):
    """미국주식용 KIS 어댑터. 토큰 발급은 국내 어댑터 것을 그대로 재사용한다."""

    name = "kis-us"
    currency = "USD"

    def __init__(self, app_key: str, app_secret: str, account_no: str, is_paper: bool):
        # 토큰 캐시·발급 로직을 공유하기 위해 국내 어댑터를 내부에 둔다.
        self._auth = KISBroker(
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no or "00000000-01",
            is_paper=is_paper,
        )
        self.app_key = app_key
        self.app_secret = app_secret
        self.is_paper = is_paper
        cleaned = (account_no or "").replace("-", "").strip()
        self.cano = cleaned[:8]
        self.prdt_cd = cleaned[8:] or "01"
        self.base = settings.kis_paper_base if is_paper else settings.kis_real_base
        self._client = httpx.Client(
            base_url=self.base,
            timeout=httpx.Timeout(
                settings.kis_timeout_seconds, connect=min(3.0, settings.kis_timeout_seconds)
            ),
        )

    # -- 공통 ---------------------------------------------------------------
    def _tr(self, key: str) -> str:
        real, paper = _TR[key]
        return paper if self.is_paper else real

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._auth._access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    @staticmethod
    def _ok(body: dict) -> bool:
        return body.get("rt_cd") in (None, "0")

    # -- 조회 ---------------------------------------------------------------
    def verify(self) -> tuple[bool, str]:
        try:
            self._auth._access_token()
            self.get_quote("AAPL")
            env = "모의투자" if self.is_paper else "실계좌"
            if not self.cano or self.cano == "00000000":
                return True, f"{env} 시세 조회에 성공했습니다. (주문은 해외주식 계좌번호가 필요합니다)"
            self.get_balance()
            return True, f"{env} 해외주식 연결에 성공했습니다."
        except httpx.HTTPStatusError as e:
            return False, f"KIS 응답 오류 {e.response.status_code}: 키와 해외주식 계좌번호를 확인하세요."
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize(symbol)
        excd = exchange_of(symbol)
        res = self._client.get(
            "/uapi/overseas-price/v1/quotations/price",
            headers=self._headers(self._tr("quote")),
            params={"AUTH": "", "EXCD": excd, "SYMB": symbol},
        )
        res.raise_for_status()
        body = res.json()
        if not self._ok(body):
            raise RuntimeError(body.get("msg1") or "미국 시세 조회에 실패했습니다.")
        o = body.get("output") or {}

        price = _num(o.get("last"))
        # base = 전일종가, diff = 전일대비(절대값), sign = 등락부호(1·2 상승 / 4·5 하락)
        prev_close = _num(o.get("base"))
        if prev_close <= 0:
            diff = abs(_num(o.get("diff")))
            if str(o.get("sign", "3")) in ("4", "5"):
                diff = -diff
            prev_close = price - diff

        return Quote(
            symbol=symbol,
            name=name_of(symbol),
            price=price,
            prev_close=prev_close,
            open=_num(o.get("open")),
            high=_num(o.get("high")),
            low=_num(o.get("low")),
            volume=int(_num(o.get("tvol"))),
            ts=datetime.now(),
            currency="USD",
            exchange=excd,
        )

    def get_candles(self, symbol: str, days: int = 120) -> list[Candle]:
        symbol = normalize(symbol)
        # 해외 일봉도 1회 요청당 100건이 상한이다.
        want = min(days, 100)
        res = self._client.get(
            "/uapi/overseas-price/v1/quotations/dailyprice",
            headers=self._headers(self._tr("candles")),
            params={
                "AUTH": "",
                "EXCD": exchange_of(symbol),
                "SYMB": symbol,
                "GUBN": "0",                                  # 0=일봉
                "BYMD": date.today().strftime("%Y%m%d"),      # 조회 기준일
                "MODP": "1",                                  # 1=수정주가
            },
        )
        res.raise_for_status()
        body = res.json()
        if not self._ok(body):
            raise RuntimeError(body.get("msg1") or "미국 일봉 조회에 실패했습니다.")

        rows = body.get("output2") or []
        candles = [
            Candle(
                date=datetime.strptime(r["xymd"], "%Y%m%d").date().isoformat(),
                open=_num(r.get("open")),
                high=_num(r.get("high")),
                low=_num(r.get("low")),
                close=_num(r.get("clos")),
                volume=int(_num(r.get("tvol"))),
            )
            for r in rows
            if r.get("xymd") and _num(r.get("clos")) > 0
        ]
        candles.sort(key=lambda c: c.date)
        return candles[-want:]

    def get_balance(self) -> Balance:
        res = self._client.get(
            "/uapi/overseas-stock/v1/trading/inquire-balance",
            headers=self._headers(self._tr("balance")),
            params={
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.prdt_cd,
                "OVRS_EXCG_CD": "NASD",   # NASD가 미국 전체(나스닥·뉴욕·아멕스) 통합 조회
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )
        res.raise_for_status()
        body = res.json()
        if not self._ok(body):
            raise RuntimeError(body.get("msg1") or "해외 잔고 조회에 실패했습니다.")

        holdings = [
            BalanceItem(
                symbol=normalize(r.get("ovrs_pdno", "")),
                name=r.get("ovrs_item_name") or name_of(r.get("ovrs_pdno", "")),
                quantity=int(_num(r.get("ovrs_cblc_qty"))),
                avg_price=_num(r.get("pchs_avg_pric")),
                current_price=_num(r.get("now_pric2")),
            )
            for r in (body.get("output1") or [])
            if int(_num(r.get("ovrs_cblc_qty"))) > 0
        ]
        summary = body.get("output2") or {}
        if isinstance(summary, list):
            summary = summary[0] if summary else {}
        # 외화 예수금. 필드명이 계정 유형에 따라 갈려서 후보를 순서대로 본다.
        cash = 0.0
        for key in ("frcr_dncl_amt1", "frcr_dncl_amt_2", "frcr_evlu_tota", "tot_dncl_amt"):
            cash = _num(summary.get(key))
            if cash:
                break
        return Balance(cash=cash, holdings=holdings, currency="USD")

    # -- 주문 ---------------------------------------------------------------
    def place_order(
        self, symbol: str, side: str, quantity: int, price: float = 0.0, order_type: str = "limit"
    ) -> OrderResult:
        if not self.cano or self.cano == "00000000":
            return OrderResult(
                ok=False,
                message="해외주식 계좌번호가 없습니다. .env의 KIS_OVERSEAS_ACCOUNT_NO를 채우세요.",
            )
        symbol = normalize(symbol)
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt_cd,
            "OVRS_EXCG_CD": {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}.get(
                exchange_of(symbol), "NASD"
            ),
            "PDNO": symbol,
            "ORD_QTY": str(int(quantity)),
            # 미국은 시장가 주문이 없다. 시장가 요청은 현재가 지정가로 낸다.
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",   # 00=지정가
        }
        try:
            res = self._client.post(
                "/uapi/overseas-stock/v1/trading/order",
                headers=self._headers(self._tr("buy" if side == "buy" else "sell")),
                json=payload,
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001
            return OrderResult(ok=False, message=f"미국주식 주문 전송에 실패했습니다: {e}")

        if not self._ok(body):
            return OrderResult(ok=False, message=body.get("msg1", "주문이 거부되었습니다."))

        out = body.get("output") or {}
        return OrderResult(
            ok=True,
            broker_order_id=out.get("ODNO"),
            filled_quantity=0,   # 접수 시점에는 미체결. 체결은 잔고 조회로 갱신한다.
            filled_price=0.0,
            message=body.get("msg1", "주문을 접수했습니다."),
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        payload = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "PDNO": "",
            "ORGN_ODNO": broker_order_id,
            "RVSE_CNCL_DVSN_CD": "02",   # 02=취소
            "ORD_QTY": "0",
            "OVRS_ORD_UNPR": "0",
        }
        try:
            res = self._client.post(
                "/uapi/overseas-stock/v1/trading/order-rvsecncl",
                headers=self._headers(self._tr("cancel")),
                json=payload,
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001
            return OrderResult(ok=False, message=f"취소 요청에 실패했습니다: {e}")
        return OrderResult(
            ok=self._ok(body), broker_order_id=broker_order_id, message=body.get("msg1", "")
        )
