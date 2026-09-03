import { useState } from "react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { signed } from "../lib/format";
import { DrawdownChart, EquityChart, MonthlyChart } from "../components/Charts";
import { Card, ErrorNote, Money, Segmented, Spinner, cx } from "../components/ui";

const RANGES = [
  { value: 30, label: "1개월" },
  { value: 90, label: "3개월" },
  { value: 180, label: "6개월" },
  { value: 365, label: "1년" },
];

/** 지표 정의를 화면 안에 둔다. 심사·리뷰 때 되묻지 않아도 되게. */
const DEFS = {
  sharpe: "무위험수익률을 뺀 초과수익을 변동성으로 나눈 값. 위험 한 단위당 수익.",
  sortino: "하방 변동성만으로 나눈 값. 상승 변동은 위험으로 보지 않는다.",
  mdd: "고점 대비 최대 하락폭. 전략이 견뎌야 했던 최악의 구간.",
  calmar: "연환산 수익률을 최대 낙폭으로 나눈 값.",
  pf: "총이익 ÷ 총손실. 1을 넘으면 이익이 손실보다 크다.",
};

export default function Performance() {
  const { env } = useApp();
  const [days, setDays] = useState(180);
  const { data, error, loading, reload } = useAsync(() => api.performance(env, days), [env, days]);

  if (error) return <ErrorNote message={error} onRetry={reload} />;
  if (loading || !data) return <Spinner />;

  const m = data.metrics;
  const b = data.benchmark_metrics;
  const last = data.curve.at(-1);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-[12.5px] text-muted">
          {data.curve.length}거래일 · {env === "live" ? "실계좌" : "모의투자"} 기준
        </p>
        <Segmented value={days} onChange={setDays} options={RANGES} size="sm" />
      </div>

      {/* 핵심 지표 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Headline label="누적 수익률" value={signed(m.total_return_pct)} tone={m.total_return_pct} sub={`연환산 ${signed(m.cagr_pct)}`} />
        <Headline label="Sharpe 비율" value={m.sharpe.toFixed(2)} tone={m.sharpe} sub={DEFS.sharpe} small />
        <Headline label="최대 낙폭" value={`${m.max_drawdown_pct.toFixed(2)}%`} tone={-1} sub={DEFS.mdd} small />
        <Headline label="평가자산" value={<Money value={last?.equity ?? 0} size={26} />} sub={`고점 대비 ${signed(last?.drawdown ?? 0)}`} />
      </div>

      {/* 에이전트 vs Buy & Hold */}
      <Card eyebrow="AGENT VS BUY & HOLD" title="벤치마크 비교">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-4 mb-5">
          <Compare label="누적 수익률" a={signed(m.total_return_pct)} bch={signed(b.total_return_pct)} better={m.total_return_pct >= b.total_return_pct} />
          <Compare label="Sharpe" a={m.sharpe.toFixed(2)} bch={b.sharpe.toFixed(2)} better={m.sharpe >= b.sharpe} />
          <Compare label="최대 낙폭" a={`${m.max_drawdown_pct.toFixed(2)}%`} bch={`${b.max_drawdown_pct.toFixed(2)}%`} better={m.max_drawdown_pct >= b.max_drawdown_pct} />
          <Compare label="변동성" a={`${m.volatility_pct.toFixed(1)}%`} bch={`${b.volatility_pct.toFixed(1)}%`} better={m.volatility_pct <= b.volatility_pct} />
        </div>
        <EquityChart data={data.curve} height={264} />
        <p className="mt-4 text-[12px] text-muted leading-relaxed">
          강화학습 전략의 이점은 절대수익이 아니라 위험조정수익에서 드러납니다. 상승장에서는
          Buy &amp; Hold를 밑돌더라도, 낙폭과 변동성이 낮으면 Sharpe 기준으로는 앞설 수 있습니다.
        </p>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card eyebrow="DRAWDOWN" title="고점 대비 낙폭">
          <DrawdownChart data={data.curve} height={196} />
        </Card>
        <Card eyebrow="MONTHLY" title="월별 수익률">
          <MonthlyChart data={data.monthly} height={196} />
        </Card>
      </div>

      {/* 전체 지표 */}
      <Card eyebrow="ALL METRICS" title="세부 지표" pad={false}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 border-t border-line">
          {[
            ["연환산 수익률", signed(m.cagr_pct), null],
            ["Sortino 비율", m.sortino.toFixed(2), DEFS.sortino],
            ["Calmar 비율", m.calmar.toFixed(2), DEFS.calmar],
            ["연환산 변동성", `${m.volatility_pct.toFixed(2)}%`, null],
            ["승률", `${m.win_rate_pct.toFixed(1)}%`, `총 ${m.trades}회 청산 기준`],
            ["손익비", m.profit_factor.toFixed(2), DEFS.pf],
            ["최고 일간 수익", signed(m.best_day_pct), null],
            ["최저 일간 수익", signed(m.worst_day_pct), null],
            ["체결 완료 주문", `${m.trades}건`, null],
          ].map(([label, value, desc]) => (
            <div key={label} className="px-5 py-4 border-b border-r border-line last:border-r-0">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[12.5px] text-muted">{label}</span>
                <span className="num text-[15px]">{value}</span>
              </div>
              {desc && <p className="mt-1.5 text-[11px] text-muted leading-relaxed">{desc}</p>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Headline({ label, value, tone, sub, small }) {
  const cls = tone > 0 ? "text-up" : tone < 0 ? "text-down" : "text-body";
  return (
    <Card>
      <div className="text-[12.5px] text-muted mb-3">{label}</div>
      <div className={cx("num text-[26px] leading-none tracking-tight", cls)}>{value}</div>
      {sub && (
        <p className={cx("mt-2.5 text-muted leading-relaxed", small ? "text-[11px]" : "text-[12px] num")}>
          {sub}
        </p>
      )}
    </Card>
  );
}

function Compare({ label, a, bch, better }) {
  return (
    <div>
      <div className="text-[11.5px] text-muted mb-2">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className={cx("num text-[17px]", better ? "text-brand" : "text-body")}>{a}</span>
        <span className="num text-[12px] text-muted">vs {bch}</span>
      </div>
      <div className="mt-2 h-[2px] rounded-full bg-raise overflow-hidden">
        <div className={cx("h-full rounded-full", better ? "bg-brand" : "bg-muted")}
          style={{ width: better ? "100%" : "42%" }} />
      </div>
    </div>
  );
}
