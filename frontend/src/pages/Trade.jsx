import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { signed, toneClass, won } from "../lib/format";
import { PriceSpark } from "../components/Charts";
import { Button, Card, Field, Input, Segmented, Spinner, cx } from "../components/ui";

export default function Trade() {
  const { env, toast, isLive } = useApp();
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

  useEffect(() => {
    if (quote.data && !price) setPrice(String(quote.data.price));
  }, [quote.data, price]);
  useEffect(() => setPrice(""), [symbol]);

  // 시장을 바꾸면 종목 코드 체계가 달라진다(005930 ↔ AAPL).
  // 새 유니버스가 도착하면 그 시장의 첫 종목으로 옮겨 준다.
  useEffect(() => {
    const list = universe.data;
    if (!list?.length) return;
    if (!list.some((u) => u.symbol === symbol)) setSymbol(list[0].symbol);
  }, [universe.data, symbol]);

  const q = quote.data;
  const held = account.data?.holdings.find((h) => h.symbol === symbol);
  const effPrice = orderType === "market" ? q?.price ?? 0 : Number(price || 0);
  const estimate = effPrice * Number(qty || 0);
  const fee = Math.round(estimate * (side === "buy" ? 0.00015 : 0.00195));

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

        <Card eyebrow="QUOTE" title={q ? q.name : "시세"}>
          {!q ? (
            <Spinner />
          ) : (
            <>
              <div className="flex flex-wrap items-end justify-between gap-6 mb-5">
                <div>
                  <div className={cx("num text-[34px] leading-none tracking-tight", toneClass(q.change))}>
                    {q.price.toLocaleString("ko-KR")}
                    <span className="text-[15px] text-muted ml-1.5">원</span>
                  </div>
                  <div className={cx("num text-[13px] mt-2.5", toneClass(q.change))}>
                    {q.change > 0 ? "▲" : q.change < 0 ? "▼" : "—"}{" "}
                    {Math.abs(q.change).toLocaleString("ko-KR")} ({signed(q.change_pct)})
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-[12px]">
                  {[
                    ["시가", q.open], ["고가", q.high],
                    ["저가", q.low], ["전일종가", q.prev_close],
                  ].map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-3 justify-between">
                      <dt className="text-muted">{k}</dt>
                      <dd className="num">{v.toLocaleString("ko-KR")}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              {candles.data && (
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
            <Field label="주문 단가" hint="원">
              <Input type="number" mono min={0} step={10} value={price}
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
              disabled={insufficient || !qty || (orderType === "limit" && !price)}
              onClick={() => setConfirm(true)}
            >
              {side === "buy" ? "매수" : "매도"} 주문
            </Button>
          ) : (
            <div className="rounded-sm border border-line bg-raise p-4 rise">
              <p className="text-[13px] leading-relaxed mb-1">
                <span className="font-medium">{q?.name}</span>{" "}
                {Number(qty).toLocaleString("ko-KR")}주를{" "}
                {orderType === "market" ? "시장가로" : `${Number(price).toLocaleString("ko-KR")}원에`}{" "}
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
