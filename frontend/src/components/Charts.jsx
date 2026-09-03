import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { dateShort, signed, won, wonShort } from "../lib/format";

const axis = {
  stroke: "var(--line)",
  tick: { fill: "var(--muted)", fontSize: 10.5, fontFamily: "IBM Plex Mono" },
  tickLine: false,
  axisLine: false,
};

function Frame({ label, children }) {
  return (
    <div className="rounded border border-line bg-ink px-3.5 py-2.5 text-[12px]">
      <div className="num text-[10.5px] text-muted mb-1.5">{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Row({ name, value, color }) {
  return (
    <div className="flex items-center justify-between gap-6">
      <span className="flex items-center gap-1.5 text-muted">
        <span className="w-[7px] h-[2px] rounded-full" style={{ background: color }} />
        {name}
      </span>
      <span className="num" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

/** 자산곡선 — 에이전트 대 Buy & Hold 벤치마크 */
export function EquityChart({ data, height = 260, showBenchmark = true }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -8 }}>
        <defs>
          <linearGradient id="gEquity" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.26} />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={dateShort} minTickGap={44} {...axis} />
        <YAxis tickFormatter={wonShort} width={52} {...axis} />
        <Tooltip
          cursor={{ stroke: "var(--muted)", strokeWidth: 1, strokeDasharray: "3 3" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <Frame label={label}>
                <Row
                  name="에이전트"
                  value={won(payload[0].value)}
                  color="var(--brand)"
                />
                {showBenchmark && payload[1] && (
                  <Row
                    name="Buy & Hold"
                    value={won(payload[1].value)}
                    color="var(--muted)"
                  />
                )}
              </Frame>
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="var(--brand)"
          strokeWidth={1.8}
          fill="url(#gEquity)"
          dot={false}
          activeDot={{ r: 3, fill: "var(--brand)", stroke: "var(--ink)", strokeWidth: 2 }}
        />
        {showBenchmark && (
          <Line
            type="monotone"
            dataKey="benchmark"
            stroke="var(--muted)"
            strokeWidth={1.2}
            strokeDasharray="4 4"
            dot={false}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** 낙폭(drawdown) — 항상 0 이하이므로 아래로만 채운다 */
export function DrawdownChart({ data, height = 150 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -8 }}>
        <defs>
          <linearGradient id="gDD" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--down)" stopOpacity={0} />
            <stop offset="100%" stopColor="var(--down)" stopOpacity={0.3} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={dateShort} minTickGap={44} {...axis} />
        <YAxis
          tickFormatter={(v) => `${v.toFixed(0)}%`}
          width={52}
          domain={["dataMin", 0]}
          {...axis}
        />
        <Tooltip
          cursor={{ stroke: "var(--muted)", strokeWidth: 1, strokeDasharray: "3 3" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <Frame label={label}>
                <Row
                  name="고점 대비"
                  value={signed(payload[0].value, 2)}
                  color="var(--down)"
                />
              </Frame>
            ) : null
          }
        />
        <ReferenceLine y={0} stroke="var(--line)" />
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke="var(--down)"
          strokeWidth={1.4}
          fill="url(#gDD)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** 월별 수익률 — 상승 적색 / 하락 청색 */
export function MonthlyChart({ data, height = 190 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -12 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="month" tickFormatter={(m) => `${+m.slice(5)}월`} {...axis} />
        <YAxis tickFormatter={(v) => `${v}%`} width={46} {...axis} />
        <Tooltip
          cursor={{ fill: "var(--raise)" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <Frame label={label}>
                <Row
                  name="월 수익률"
                  value={signed(payload[0].value, 2)}
                  color={payload[0].value >= 0 ? "var(--up)" : "var(--down)"}
                />
              </Frame>
            ) : null
          }
        />
        <ReferenceLine y={0} stroke="var(--line)" />
        <Bar dataKey="return_pct" radius={[2, 2, 0, 0]} maxBarSize={30}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.return_pct >= 0 ? "var(--up)" : "var(--down)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** 종가 스파크라인 — 주문 화면의 종목 카드용 */
export function PriceSpark({ data, up, height = 64 }) {
  const color = up ? "var(--up)" : "var(--down)";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`gS${up ? "u" : "d"}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.24} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Area
          type="monotone"
          dataKey="close"
          stroke={color}
          strokeWidth={1.4}
          fill={`url(#gS${up ? "u" : "d"})`}
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
