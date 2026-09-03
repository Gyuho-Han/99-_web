import { useState } from "react";
import { ACTION_LABEL, dateTime, isUSD, price as fmtPrice } from "../lib/format";
import { cx } from "./ui";

/**
 * 신호 테이프 — 정책이 매 스텝 내놓은 행동과 신뢰도를 시간순으로 늘어놓는다.
 *
 * 막대 높이는 신뢰도, 색은 행동(매수 적색 / 매도 청색 / 관망 회색)이고
 * 가로 점선이 실행 임계값이다. 임계값 위로 올라온 막대만 주문으로 나가므로,
 * 이 한 장에서 "정책이 무엇을 보았고 왜 실행되지 않았는가"가 바로 읽힌다.
 */
export default function SignalTape({ signals = [], threshold = 0.55, height = 116 }) {
  const [hover, setHover] = useState(null);
  const items = [...signals].reverse(); // 오래된 → 최신
  const barArea = height - 34;

  if (!items.length) {
    return (
      <div
        className="flex items-center justify-center text-[12.5px] text-muted border border-dashed border-line rounded"
        style={{ height }}
      >
        아직 기록된 신호가 없습니다. 에이전트를 한 번 실행해 보세요.
      </div>
    );
  }

  const colorOf = (a) =>
    a === "buy" ? "var(--up)" : a === "sell" ? "var(--down)" : "var(--muted)";

  return (
    <div className="relative">
      <div
        className="relative overflow-x-auto overflow-y-hidden pb-1"
        style={{ height: height + 8 }}
      >
        {/* 실행 임계값 기준선 */}
        <div
          className="absolute left-0 right-0 pointer-events-none z-10 flex items-center"
          style={{ bottom: 34 + barArea * threshold }}
        >
          <div
            className="flex-1 border-t border-dashed"
            style={{ borderColor: "var(--brand-dim)" }}
          />
          <span className="num text-[9.5px] text-brand pl-2 pr-0.5 bg-surface">
            임계 {threshold.toFixed(2)}
          </span>
        </div>

        <div className="flex items-end gap-[3px] h-full min-w-full">
          {items.map((s) => {
            const h = Math.max(3, s.confidence * barArea);
            const active = hover?.id === s.id;
            return (
              <button
                key={s.id}
                onMouseEnter={() => setHover(s)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(s)}
                onBlur={() => setHover(null)}
                className={cx(
                  "group relative shrink-0 w-[26px] flex flex-col items-center justify-end rounded-xs",
                  "transition-colors",
                  active ? "bg-raise" : "hover:bg-raise/60",
                )}
                style={{ height }}
                aria-label={`${s.symbol} ${ACTION_LABEL[s.action]} 신뢰도 ${s.confidence.toFixed(2)}`}
              >
                <span
                  className="w-[11px] rounded-t-[2px] transition-all duration-200"
                  style={{
                    height: h,
                    background: colorOf(s.action),
                    opacity: s.executed ? 1 : 0.34,
                  }}
                />
                {/* 실제 주문으로 나간 신호만 아래에 채워진 점을 찍는다 */}
                <span
                  className="mt-[6px] w-[4px] h-[4px] rounded-full shrink-0"
                  style={{
                    background: s.executed ? colorOf(s.action) : "transparent",
                    border: s.executed ? "none" : "1px solid var(--line)",
                  }}
                />
                <span className="num text-[8.5px] text-muted mt-[5px] leading-none">
                  {new Date(s.created_at).getHours()}시
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {hover && <SignalTooltip s={hover} />}

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-muted">
        <Legend color="var(--up)" label="매수" />
        <Legend color="var(--down)" label="매도" />
        <Legend color="var(--muted)" label="관망" />
        <span className="flex items-center gap-1.5">
          <span className="w-[4px] h-[4px] rounded-full bg-body" />
          주문 실행됨
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-[4px] h-[4px] rounded-full border border-line" />
          미실행
        </span>
      </div>
    </div>
  );
}

function Legend({ color, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-[7px] h-[9px] rounded-[1px]" style={{ background: color }} />
      {label}
    </span>
  );
}

function SignalTooltip({ s }) {
  const q = [
    ["매수", s.q_buy, "var(--up)"],
    ["관망", s.q_hold, "var(--muted)"],
    ["매도", s.q_sell, "var(--down)"],
  ];
  const span = Math.max(1, ...q.map(([, v]) => Math.abs(v)));

  return (
    <div className="mt-3 rounded border border-line bg-ink px-4 py-3 rise">
      <div className="flex items-center justify-between gap-4 mb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold">{s.symbol}</span>
          <span className="num text-[12px] text-muted">
            {fmtPrice(s.price)}
            {!isUSD() && "원"}
          </span>
        </div>
        <span className="num text-[11px] text-muted">{dateTime(s.created_at)}</span>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3">
        {q.map(([label, v, color]) => (
          <div key={label}>
            <div className="flex items-baseline justify-between mb-1">
              <span className="text-[11px] text-muted">{label}</span>
              <span className="num text-[11px]" style={{ color }}>
                {v >= 0 ? "+" : "−"}
                {Math.abs(v).toFixed(2)}
              </span>
            </div>
            <div className="h-[3px] rounded-full bg-raise overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${(Math.abs(v) / span) * 100}%`, background: color }}
              />
            </div>
          </div>
        ))}
      </div>

      <p className="text-[11.5px] text-muted leading-relaxed">
        선택 <span className="text-body">{ACTION_LABEL[s.action]}</span> · 신뢰도{" "}
        <span className="num text-body">{s.confidence.toFixed(2)}</span>
        {s.reason ? ` — ${s.reason}` : ""}
      </p>
    </div>
  );
}
