"""KIS 앱키가 제대로 붙었는지 확인하는 점검 스크립트.

    cd backend && python scripts/check_kis.py          # 삼성전자로 확인
    cd backend && python scripts/check_kis.py 000660   # 종목 지정

.env 의 KIS_APP_KEY / KIS_APP_SECRET 만 있으면 된다. 계좌번호는 필요 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.brokers import market  # noqa: E402
from app.core.config import settings  # noqa: E402


def mask(v: str) -> str:
    return f"{v[:4]}…{v[-4:]} ({len(v)}자)" if len(v) > 8 else "(설정 안 됨)"


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "005930"

    print("─" * 56)
    print("KIS 실시세 점검")
    print("─" * 56)
    print(f"  .env 위치      : {Path(settings.model_config['env_file'])}")
    print(f"  KIS_APP_KEY    : {mask(settings.kis_app_key)}")
    print(f"  KIS_APP_SECRET : {mask(settings.kis_app_secret)}")
    print(f"  도메인         : {settings.kis_paper_base if settings.kis_market_use_paper else settings.kis_real_base}")
    print(f"  실시세 사용    : {settings.kis_market_data}")
    print()

    if not settings.kis_market_ready:
        print("  ✗ 앱키가 비어 있습니다. backend/.env 의 KIS_APP_KEY / KIS_APP_SECRET 를 채우세요.")
        print("    지금 상태로 서버를 띄우면 내장 시뮬레이터 시세로 동작합니다.")
        return 1

    print(f"  [1/2] 현재가 조회 — {symbol}")
    q = market.get_quote(symbol)
    if q is None:
        print("  ✗ 실패. 원인 후보:")
        print("    · 모의투자 앱키를 넣었다 (시세조회는 실전 앱키만 지원)")
        print("    · 앱키/시크릿 오타, 또는 KIS 개발자센터에서 아직 승인 전")
        print("    · 종목코드가 6자리 숫자가 아니다")
        return 1
    print(f"      {q.name} {q.price:,.0f}원  전일대비 {q.change:+,.0f} ({q.change_pct:+.2f}%)")
    print(f"      시가 {q.open:,.0f} / 고가 {q.high:,.0f} / 저가 {q.low:,.0f} / 거래량 {q.volume:,}")
    print()

    print("  [2/2] 일봉 조회")
    rows = market.get_candles(symbol, 100)
    if not rows:
        print("  ✗ 일봉 조회 실패. 현재가는 되는데 일봉이 안 되면 TR_ID를 확인하세요.")
        return 1
    print(f"      {len(rows)}건  {rows[0].date} ~ {rows[-1].date}")
    for c in rows[-3:]:
        print(f"      {c.date}  종가 {c.close:,.0f}  거래량 {c.volume:,}")
    print()
    print("  ✓ 실시세 연결 정상입니다. 서버를 띄우면 대시보드가 실제 가격으로 채워집니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
