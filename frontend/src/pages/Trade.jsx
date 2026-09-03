import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { price as fmtPrice, signed, toneClass, won } from "../lib/format";
import { PriceSpark } from "../components/Charts";
import {
  Button, Card, ErrorNote, Field, Input, Segmented, Spinner, cx,
} from "../components/ui";

/* 백엔드 시뮬레이터(brokers/mock.py)의 요율을 그대로 옮긴 값.
   화면의 예상 수수료가 실제 체결 결과와 어긋나지 않게 한 곳을 보고 맞춘다. */
const FEE_RATE = {
  kr: { buy: 0.00015, sell: 0.00015 + 0.0018 },      // 위탁 0.015% (+ 매도 거래세 0.18%)
  us: { buy: 0.0025, sell: 0.0025 + 0.0000229 },     // 0.25% (+ 매도 SEC 수수료)
};

export default function Trade() {
  const { env, toast, isLive, isUS } = useApp();
  const [symbol, setSymbol] = useState("005930");
  const [side, setSide] = useState("buy");
  const [orderType, setOrderType] = useState("limit");
  const [qty, setQty] = useState(1);
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const universe = useAsync(() => api.universe(), []);
  const quote = useAsync(() => api.quote(symbol, env), [symbol, env], { interval: 10000 });
  const candles = useAsync(() => api.candles(symbol, env, 60), [symbol, env]);
  const account = useAsync(() => api.account(env), [env]);

  // 다른 종목의 시세가 남아 있는 동안에는 값을 쓰지 않는다. useAsync 는 다시
  // 불러오는 사이에도 이전 데이터를 들고 있어서, 이 가드가 없으면 종목을 바꾼 직후
  // 잠깐 이전 종목의 가격이 새 종목의 가격인 것처럼 보인다.
  const q = quote.data?.symbol === symbol ? quote.data : null;
  const quoteLoading = !q && !quote.error;

  useEffect(() => {
    if (q && !price) setPrice(String(q.price));
  }, [q, price]);
  useEffect(() => setPrice(""), [symbol]);

  // 시장을 바꾸면 종목 코드 체계가 달라진다(005930 ↔ AAPL).
  // 새 유니버스가 도착하면 그 시장의 첫 종목으로 옮겨 준다.
  useEffect(() => {
    const list = universe.data;
    if (!list?.length) return;
    if (!list.some((u) => u.symbol === symbol)) setSymbol(list[0].symbol);
  }, [universe.data, symbol]);

  // KIS 현재가 응답에 종목명이 비어 오는 때가 있다. 그러면 어댑터가 종목코드로
  // 대신 채우는데, 화면에 "005930" 이 제목으로 뜨는 것보다는 유니버스가 알고 있는
  // 이름을 쓰는 편이 낫다.
  const listedName = universe.data?.find((u) => u.symbol === symbol)?.name;
  const name = q ? (q.name && q.name !== q.symbol ? q.name : listedName || q.symbol) : null;

  const held = account.data?.holdings.find((h) => h.symbol === symbol);
  const effPrice = orderType === "market" ? q?.price ?? 0 : Number(price || 0);
  const estimate = effPrice * Number(qty || 0);
  const rate = FEE_RATE[isUS ? "us" : "kr"][side];
  // 원화는 원 단위, 달러는 센트 단위로 끊는다.
  const fee = isUS
    ? Math.round(estimate * rate * 100) / 100
    : Math.round(estimate * rate);

  const insufficient =
    side === "buy"
      ? estimate + fee > (account.data?.cash ?? 0)
      : Number(qty) > (held?.quantity ?? 0);

  const submit = async () => {
    setBusy(true);
    try {
      await api.placeOrder(env, {
        symbol,
        side,
        quantity: Number(qty),
        price: orderType === "market" ? 0 : Number(price),
        order_type: orderType,
      });
      toast(`${side === "buy" ? "매수" : "매도"} 주문을 접수했습니다.`, "success");
      setConfirm(false);
      account.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-4 items-start">
      <div className="space-y-4">
        <Card eyebrow="WATCHLIST" title="종목" pad={false}>
          <div className="grid grid-cols-2 sm:grid-cols-4 border-t border-line">
            {(universe.data ?? []).map((u) => (
              <button
                key={u.symbol}
                onClick={() => setSymbol(u.symbol)}
                className={cx(
                  "text-left px-4 py-3.5 border-b border-r border-line transition-colors",
                  u.symbol === symbol ? "bg-raise" : "hover:bg-raise/50",
                )}
              >
                <div className="text-[13px] font-medium truncate">{u.name}</div>
                <div className="num text-[11px] text-muted mt-0.5">{u.symbol}</div>
              </button>
            ))}
          </div>
        </Card>

        <Card eyebrow="QUOTE" title={name ?? "시세"}>
          {quote.error ? (
            <ErrorNote message={quote.error} onRetry={quote.reload} />
          ) : quoteLoading ? (
            <div className="py-10">
              <Spinner label="시세 불러오는 중" />
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-end justify-between gap-6 mb-5">
                <div>
                  <div className={cx("num text-[34px] leading-none tracking-tight", toneClass(q.change))}>
                    {fmtPrice(q.price)}
                    {!isUS && <span className="text-[15px] text-muted ml-1.5">원</span>}
                  </div>
                  <div className={cx("num text-[13px] mt-2.5", toneClass(q.change))}>
                    {q.change > 0 ? "▲" : q.change < 0 ? "▼" : "—"}{" "}
                    {fmtPrice(Math.abs(q.change))} ({signed(q.change_pct)})
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-[12px]">
                  {[
                    ["시가", q.open], ["고가", q.high],
                    ["저가", q.low], ["전일종가", q.prev_close],
                  ].map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-3 justify-between">
                      <dt className="text-muted">{k}</dt>
                      <dd className="num">{fmtPrice(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              {candles.data && !candles.loading && (
                <PriceSpark data={candles.data} up={q.change >= 0} height={168} />
              )}
            </>
          )}
        </Card>
      </div>

      {/* 주문표 */}
      <Card
        eyebrow="ORDER TICKET"
        title="주문"
        className={cx("xl:sticky xl:top-[76px]", isLive && "border-up/30")}
      >
        <div className="space-y-4">
          <Segmented
            value={side}
            onChange={setSide}
            options={[
              { value: "buy", label: "매수" },
              { value: "sell", label: "매도" },
            ]}
          />

          <div className="rounded-sm border border-line bg-ink px-4 py-3 space-y-2">
            <Row label="주문가능 현금" value={won(account.data?.cash ?? 0)} />
            <Row
              label="보유 수량"
              value={held ? `${held.quantity.toLocaleString("ko-KR")}주` : "0주"}
            />
            {held && (
              <Row
                label="평가손익"
                value={signed(held.unrealized_pct)}
                className={toneClass(held.unrealized_pnl)}
              />
            )}
          </div>

          <Field label="주문 유형">
            <Segmented
              size="sm"
              value={orderType}
              onChange={setOrderType}
              options={[
                { value: "limit", label: "지정가" },
                { value: "market", label: "시장가" },
              ]}
            />
          </Field>

          {orderType === "limit" && (
            <Field label="주문 단가" hint={isUS ? "USD" : "원"}>
              <Input type="number" mono min={0} step={isUS ? 0.01 : 10} value={price}
                onChange={(e) => setPrice(e.target.value)} />
            </Field>
          )}

          <Field
            label="수량"
            hint={
              side === "sell" && held ? (
                <button onClick={() => setQty(held.quantity)}
                  className="text-brand hover:underline underline-offset-2">전량</button>
              ) : "주"
            }
          >
            <Input type="number" mono min={1} step={1} value={qty}
              onChange={(e) => setQty(e.target.value)} />
          </Field>

          <div className="rounded-sm border border-line bg-ink px-4 py-3 space-y-2">
            <Row label="주문 금액" value={won(estimate)} />
            <Row label={side === "buy" ? "수수료" : "수수료·세금"} value={won(fee)} />
            <div className="h-px bg-line my-1" />
            <Row
              label={side === "buy" ? "총 필요금액" : "수령 예상액"}
              value={won(side === "buy" ? estimate + fee : estimate - fee)}
              strong
            />
          </div>

          {insufficient && (
            <p className="text-[12px] text-up leading-snug">
              {side === "buy" ? "주문가능 현금이 부족합니다." : "보유 수량이 부족합니다."}
            </p>
          )}

          {!confirm ? (
            <Button
              variant={side === "buy" ? "danger" : "primary"}
              size="lg"
              className="w-full"
              disabled={!q || insufficient || !qty || (orderType === "limit" && !price)}
              onClick={() => setConfirm(true)}
            >
              {side === "buy" ? "매수" : "매도"} 주문
            </Button>
          ) : (
            <div className="rounded-sm border border-line bg-raise p-4 rise">
              <p className="text-[13px] leading-relaxed mb-1">
                <span className="font-medium">{name}</span>{" "}
                {Number(qty).toLocaleString("ko-KR")}주를{" "}
                {orderType === "market"
                  ? "시장가로"
                  : `${fmtPrice(Number(price))}${isUS ? "에" : "원에"}`}{" "}
                {side === "buy" ? "매수" : "매도"}합니다.
              </p>
              <p className="text-[12px] text-muted mb-4">
                {isLive ? "실계좌 — 실제 자금이 사용됩니다." : "모의투자 환경입니다."}
              </p>
              <div className="flex gap-2">
                <Button variant={side === "buy" ? "danger" : "primary"} loading={busy}
                  onClick={submit} className="flex-1">
                  확인하고 주문
                </Button>
                <Button variant="ghost" onClick={() => setConfirm(false)}>취소</Button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function Row({ label, value, className, strong }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-[12px] text-muted">{label}</span>
      <span className={cx("num", strong ? "text-[13.5px]" : "text-[12.5px]", className)}>{value}</span>
    </div>
  );
}
