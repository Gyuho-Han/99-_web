import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Info, PieChart, Wallet } from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import {
  dateTime, signed, signedWon, toneClass, toneOf, won, wonShort,
} from "../lib/format";
import {
  Badge, Button, Card, Empty, ErrorNote, Money, Spinner, Stat, cx,
} from "../components/ui";

/* --------------------------------------------------------------------------
   자산 구성 색
   기존 UI의 시안 액센트와 등락색(상승 적색·하락 청색)은 이미 뜻이 정해져 있어서
   종목 색으로 쓸 수 없다. 그래서 그 셋을 피한 6색을 따로 골라 두고, 다크/라이트
   각각의 배경에서 검증했다(색맹 인접쌍 ΔE 9.4 / 9.2, 명도대비 다크 전부 3:1 이상).
   라이트 모드는 일부 색이 3:1 아래라 범례 텍스트와 아래 표가 색만으로 구분하지
   않게 받쳐 준다.
   -------------------------------------------------------------------------- */
const PALETTE = {
  dark: {
    series: ["#199e70", "#d95926", "#9085e9", "#c98500", "#d55181", "#008300"],
    // 예수금과 '기타'는 종목이 아니다. 채도 없는 뉴트럴로 두어 색이 정체성을
    // 주장하지 않게 한다. 배경보다 밝게(다크) · 어둡게(라이트) 만들어 보이기만 하면 된다.
    cash: "#3f3f4a",
    rest: "#5a5a68",
  },
  light: {
    series: ["#1baf7a", "#eb6834", "#4a3aa7", "#eda100", "#e87ba4", "#008300"],
    cash: "#d5d5de",
    rest: "#b4b4c0",
  },
};
const MAX_SERIES = 6;

// hide: 폭이 모자랄 때 접는 열. 평가금액·평가손익·비중이 먼저 살아남아야 한다.
const COLUMNS = [
  { key: "name", label: "종목", align: "left" },
  { key: "quantity", label: "수량" },
  { key: "avg_price", label: "평균단가", hide: "hidden lg:table-cell" },
  { key: "current_price", label: "현재가", hide: "hidden md:table-cell" },
  { key: "market_value", label: "평가금액" },
  { key: "unrealized_pnl", label: "평가손익" },
  { key: "weight_pct", label: "비중" },
  { key: "realized_pnl", label: "실현손익", last: true },
];

export default function Portfolio() {
  const { env, theme } = useApp();
  const pf = useAsync(() => api.portfolio(env), [env], { interval: 20000 });
  const [sort, setSort] = useState({ key: "market_value", dir: "desc" });

  const pal = PALETTE[theme === "light" ? "light" : "dark"];

  // 색은 비중이 큰 순서로 고정한다. 정렬을 바꿔도 종목의 색은 그대로여야
  // 막대와 표가 같은 것을 가리킨다.
  const colorOf = useMemo(() => {
    const byWeight = [...(pf.data?.holdings ?? [])].sort(
      (a, b) => b.market_value - a.market_value,
    );
    const map = new Map();
    byWeight.slice(0, MAX_SERIES).forEach((h, i) => map.set(h.symbol, pal.series[i]));
    return (symbol) => map.get(symbol) ?? pal.rest;   // 색을 못 받은 종목은 '기타'와 같은 뉴트럴
  }, [pf.data, pal]);

  if (pf.error) return <ErrorNote message={pf.error} onRetry={pf.reload} />;
  if (!pf.data) return <Spinner />;

  const p = pf.data;
  const rows = [...p.holdings].sort((a, b) => {
    const dir = sort.dir === "asc" ? 1 : -1;
    const x = a[sort.key];
    const y = b[sort.key];
    if (typeof x === "string") return x.localeCompare(y, "ko") * dir;
    return (x - y) * dir;
  });

  const toggle = (key) =>
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" },
    );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Card className="rise">
          <Stat
            label="총 평가자산"
            value={<Money value={p.total_equity} size={30} />}
            badge={<Badge tone={toneOf(p.day_pnl)}>{signed(p.day_pnl_pct)}</Badge>}
            sub="전 영업일 종가 대비"
          />
        </Card>

        <Card className="rise" style={{ animationDelay: "60ms" }}>
          <Stat
            label="예수금"
            value={<Money value={p.cash} size={30} />}
            sub={`전체의 ${p.cash_weight_pct}%`}
          />
        </Card>

        <Card className="rise" style={{ animationDelay: "120ms" }}>
          <Stat
            label="보유 평가금액"
            value={<Money value={p.holdings_value} size={30} />}
            sub={p.holdings.length ? `${p.holdings.length}종목` : "보유 종목 없음"}
          />
        </Card>

        <Card className="rise" style={{ animationDelay: "180ms" }}>
          <Stat
            label="평가손익"
            value={<Money value={p.total_pnl} size={30} />}
            tone={toneOf(p.total_pnl)}
            badge={<Badge tone={toneOf(p.total_pnl)}>{signed(p.total_pnl_pct)}</Badge>}
            sub={`원금 ${won(p.deposit_total)}`}
          />
        </Card>
      </div>

      <Composition portfolio={p} colorOf={colorOf} pal={pal} />

      <Card
        eyebrow="HOLDINGS"
        title="보유 종목"
        action={
          p.connected ? <Badge tone="brand">증권사 계좌</Badge> : <Badge>시뮬레이터</Badge>
        }
        pad={false}
      >
        {rows.length === 0 ? (
          <Empty
            icon={Wallet}
            title="보유 중인 종목이 없습니다"
            description="에이전트를 켜거나 주문 화면에서 직접 매수하면 여기에 표시됩니다."
            action={<Link to="/trade"><Button size="sm" variant="primary">주문하기</Button></Link>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-muted text-[11.5px] border-b border-line">
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className={cx(
                        "font-medium py-2.5 whitespace-nowrap",
                        c.align === "left" ? "pl-5 text-left" : "px-3 text-right",
                        c.last && "pr-5",
                        c.hide,
                      )}
                    >
                      <button
                        onClick={() => toggle(c.key)}
                        className={cx(
                          "inline-flex items-center gap-1 hover:text-body transition-colors",
                          sort.key === c.key && "text-body",
                        )}
                        aria-label={`${c.label} 기준 정렬`}
                      >
                        {c.label}
                        {sort.key === c.key &&
                          (sort.dir === "desc" ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((h) => (
                  <tr
                    key={h.symbol}
                    className="border-b border-line/60 last:border-0 hover:bg-raise/50 transition-colors"
                  >
                    <td className="pl-5 py-3">
                      <div className="flex items-center gap-2.5">
                        <Swatch color={colorOf(h.symbol)} />
                        <div className="min-w-0">
                          <div className="font-medium truncate">{h.name}</div>
                          <div className="num text-[11px] text-muted mt-0.5">{h.symbol}</div>
                        </div>
                      </div>
                    </td>
                    <Td>{h.quantity.toLocaleString("ko-KR")}</Td>
                    <Td className="hidden lg:table-cell">{won(h.avg_price)}</Td>
                    <Td className="hidden md:table-cell">{won(h.current_price)}</Td>
                    <Td>{won(h.market_value)}</Td>
                    <Td className={toneClass(h.unrealized_pnl)}>
                      {signedWon(h.unrealized_pnl)}
                      <div className="text-[11px] mt-0.5">{signed(h.unrealized_pct)}</div>
                    </Td>
                    <Td>
                      <div className="flex items-center justify-end gap-2">
                        <span className="w-[42px] h-[3px] rounded-full bg-raise overflow-hidden inline-block">
                          <span
                            className="block h-full rounded-full"
                            style={{
                              width: `${Math.min(100, h.weight_pct)}%`,
                              background: colorOf(h.symbol),
                            }}
                          />
                        </span>
                        <span className="num w-[40px] text-right">{h.weight_pct.toFixed(1)}%</span>
                      </div>
                    </Td>
                    <Td className={cx("pr-5", h.realized_pnl && toneClass(h.realized_pnl))}>
                      {p.realized_supported
                        ? h.realized_pnl
                          ? signedWon(h.realized_pnl)
                          : "—"
                        : "—"}
                      <div className="text-[11px] text-muted mt-0.5">체결 {h.trade_count}건</div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {p.closed.length > 0 && (
        <Card
          eyebrow="CLOSED"
          title="청산한 종목"
          action={
            p.realized_supported ? (
              <span className="num text-[12.5px]">
                합계 <span className={toneClass(p.realized_total)}>{signedWon(p.realized_total)}</span>
              </span>
            ) : null
          }
          pad={false}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-muted text-[11.5px] border-b border-line">
                  <th className="font-medium py-2.5 pl-5 text-left">종목</th>
                  <th className="font-medium py-2.5 px-3 text-right">체결</th>
                  <th className="font-medium py-2.5 px-3 text-right">실현손익</th>
                  <th className="font-medium py-2.5 pr-5 text-right">마지막 거래</th>
                </tr>
              </thead>
              <tbody>
                {p.closed.map((x) => (
                  <tr key={x.symbol} className="border-b border-line/60 last:border-0">
                    <td className="pl-5 py-3">
                      <div className="font-medium">{x.name}</div>
                      <div className="num text-[11px] text-muted mt-0.5">{x.symbol}</div>
                    </td>
                    <Td>{x.trade_count}건</Td>
                    <Td className={p.realized_supported ? toneClass(x.realized_pnl) : undefined}>
                      {p.realized_supported ? signedWon(x.realized_pnl) : "—"}
                    </Td>
                    <Td className="pr-5 text-muted">
                      {x.last_traded_at ? dateTime(x.last_traded_at) : "—"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!p.realized_supported && (
        <p className="flex items-start gap-2 text-[12px] text-muted leading-relaxed">
          <Info size={13} className="mt-[2px] shrink-0" />
          증권사 계좌가 연결되어 있을 때는 실현손익을 계산하지 않습니다. 매도 시점의
          취득단가를 증권사 잔고가 갖고 있어서, 우리가 어림값을 채우면 화면이 조용히
          틀린 숫자를 보여 주게 됩니다. 평가손익과 보유 수량은 증권사 잔고 그대로입니다.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 자산 구성                                                            */
/* ------------------------------------------------------------------ */

function Composition({ portfolio: p, colorOf, pal }) {
  const [hover, setHover] = useState(null);

  const segments = useMemo(() => {
    const equity = p.total_equity || 1;
    const sorted = [...p.holdings].sort((a, b) => b.market_value - a.market_value);
    const top = sorted.slice(0, MAX_SERIES).map((h) => ({
      key: h.symbol,
      label: h.name,
      sub: h.symbol,
      value: h.market_value,
      pct: (h.market_value / equity) * 100,
      color: colorOf(h.symbol),
    }));

    const rest = sorted.slice(MAX_SERIES);
    if (rest.length) {
      const value = rest.reduce((s, h) => s + h.market_value, 0);
      top.push({
        key: "__rest",
        label: "기타",
        sub: `${rest.length}종목`,
        value,
        pct: (value / equity) * 100,
        color: pal.rest,
      });
    }
    // 현금은 종목이 아니므로 색이 아니라 뉴트럴로 둔다. 항상 마지막.
    top.push({
      key: "__cash",
      label: "예수금",
      sub: "현금",
      value: p.cash,
      pct: p.cash_weight_pct,
      color: pal.cash,
    });
    return top.filter((s) => s.pct > 0);
  }, [p, colorOf, pal]);

  if (segments.length === 0) return null;

  return (
    <Card
      eyebrow="ALLOCATION"
      title="자산 구성"
      action={<PieChart size={15} className="text-muted" />}
    >
      <p className="text-[12.5px] text-muted leading-relaxed mb-4">
        예수금을 포함한 전체 평가자산 {won(p.total_equity)} 기준입니다.
      </p>

      {/* 스택 막대. 조각 사이 2px는 배경색 틈이라 색이 붙어 보이지 않는다. */}
      <div
        className="flex gap-[2px] h-9 w-full rounded overflow-hidden"
        role="img"
        aria-label={`자산 구성: ${segments.map((s) => `${s.label} ${s.pct.toFixed(1)}%`).join(", ")}`}
        onMouseLeave={() => setHover(null)}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            onMouseEnter={() => setHover(s.key)}
            title={`${s.label} ${s.pct.toFixed(1)}% · ${won(s.value)}`}
            style={{ width: `${s.pct}%`, background: s.color }}
            className={cx(
              "min-w-[3px] h-full transition-opacity",
              "first:rounded-l last:rounded-r",
              hover && hover !== s.key && "opacity-45",
            )}
          />
        ))}
      </div>

      {/* 범례는 항상 있다. 색만으로 구분하지 않게 이름과 수치를 함께 적는다. */}
      <ul className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
        {segments.map((s) => (
          <li
            key={s.key}
            onMouseEnter={() => setHover(s.key)}
            onMouseLeave={() => setHover(null)}
            className={cx(
              "flex items-center gap-2.5 py-1 transition-opacity",
              hover && hover !== s.key && "opacity-45",
            )}
          >
            <Swatch color={s.color} />
            <span className="text-[12.5px] truncate flex-1 min-w-0">
              {s.label}
              <span className="text-muted text-[11px] ml-1.5">{s.sub}</span>
            </span>
            <span className="num text-[12.5px] shrink-0 w-[52px] text-right">
              {s.pct.toFixed(1)}%
            </span>
            <span className="num text-[11.5px] text-muted shrink-0 w-[64px] text-right">
              {wonShort(s.value)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Swatch({ color }) {
  return (
    <span aria-hidden className="w-2.5 h-2.5 rounded-[3px] shrink-0" style={{ background: color }} />
  );
}

function Td({ children, className }) {
  return (
    <td className={cx("px-3 py-3 text-right num whitespace-nowrap", className)}>{children}</td>
  );
}
