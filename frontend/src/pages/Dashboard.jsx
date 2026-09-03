import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Cpu, Play, Wallet } from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import {
  ACTION_LABEL, STATUS_LABEL, dateTime, signed, signedWon, toneOf, toneClass, won,
} from "../lib/format";
import { EquityChart } from "../components/Charts";
import SignalTape from "../components/SignalTape";
import {
  Badge, Button, Card, Empty, ErrorNote, Money, Segmented, Spinner, Stat, cx,
} from "../components/ui";

const RANGES = [
  { value: 30, label: "1개월" },
  { value: 90, label: "3개월" },
  { value: 180, label: "6개월" },
];

export default function Dashboard() {
  const { env, toast } = useApp();
  const [days, setDays] = useState(90);
  const [stepping, setStepping] = useState(false);

  const account = useAsync(() => api.account(env), [env], { interval: 20000 });
  const perf = useAsync(() => api.performance(env, days), [env, days]);
  const signals = useAsync(() => api.signals(env, 40), [env]);
  const orders = useAsync(() => api.orders(env, { page_size: 5 }), [env]);
  const agent = useAsync(() => api.agentConfig(env), [env]);

  const a = account.data;
  const curve = perf.data?.curve ?? [];
  const m = perf.data?.metrics;

  const runStep = async () => {
    setStepping(true);
    try {
      const res = await api.agentStep(env, true);
      const acted = res.results.filter((r) => r.action !== "hold").length;
      toast(`정책을 실행했습니다. ${res.results.length}종목 중 ${acted}건이 매매 신호입니다.`, "success");
      signals.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setStepping(false);
    }
  };

  if (account.error) return <ErrorNote message={account.error} onRetry={account.reload} />;
  if (!a) return <Spinner />;

  return (
    <div className="space-y-4">
      {/* KPI 4종 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Card className="rise">
          <Stat
            label="총 평가자산"
            value={<Money value={a.total_equity} size={30} />}
            badge={
              <Badge tone={toneOf(a.day_pnl)}>
                {signed(a.day_pnl_pct)}
              </Badge>
            }
            sub={`현금 ${won(a.cash)}`}
          />
        </Card>

        <Card className="rise" style={{ animationDelay: "60ms" }}>
          <Stat
            label="오늘 손익"
            value={<Money value={a.day_pnl} size={30} />}
            tone={toneOf(a.day_pnl)}
            sub="전 영업일 종가 대비"
          />
        </Card>

        <Card className="rise">
          <Stat
            label="누적 손익"
            value={<Money value={a.total_pnl} size={30} />}
            tone={toneOf(a.total_pnl)}
            badge={<Badge tone={toneOf(a.total_pnl)}>{signed(a.total_pnl_pct)}</Badge>}
            sub={`원금 ${won(a.deposit_total)}`}
          />
        </Card>

        <Card className="rise">
          <Stat
            label="위험조정 성과"
            value={
              <span className="num tracking-tight">
                {m ? m.sharpe.toFixed(2) : "—"}
                <span className="text-[13px] text-muted ml-2">Sharpe</span>
              </span>
            }
            sub={m ? `최대 낙폭 ${m.max_drawdown_pct.toFixed(2)}%` : ""}
          />
        </Card>
      </div>

      {/* 자산곡선 */}
      <Card
        eyebrow="EQUITY CURVE"
        title="자산 추이"
        action={
          <div className="flex items-center gap-2">
            <Segmented
              size="sm"
              value={days}
              onChange={setDays}
              options={RANGES.map((r) => ({ ...r }))}
            />
            <Link to="/performance">
              <Button size="sm" variant="ghost">
                상세 <ArrowUpRight size={13} />
              </Button>
            </Link>
          </div>
        }
      >
        <div className="flex flex-wrap items-baseline gap-x-10 gap-y-3 mb-5">
          <div>
            <div className="text-[12px] text-muted mb-1.5">평가자산</div>
            <div className="text-brand border-b-2 border-brand pb-1 inline-block">
              <Money value={a.total_equity} size={22} />
            </div>
          </div>
          <div>
            <div className="text-[12px] text-muted mb-1.5">투자원금</div>
            <div className="text-muted pb-1 inline-block">
              <Money value={a.deposit_total} size={22} />
            </div>
          </div>
          {m && (
            <div className="ml-auto flex items-center gap-6">
              <MiniMetric label="누적수익" value={signed(m.total_return_pct)} tone={toneOf(m.total_return_pct)} />
              <MiniMetric label="변동성" value={`${m.volatility_pct.toFixed(1)}%`} />
              <MiniMetric label="승률" value={`${m.win_rate_pct.toFixed(0)}%`} />
            </div>
          )}
        </div>
        {perf.loading ? <Spinner /> : <EquityChart data={curve} height={252} />}
      </Card>

      {/* 신호 테이프 + 에이전트 요약 */}
      <div className="grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-4">
        <Card
          eyebrow="POLICY OUTPUT"
          title="에이전트 신호 테이프"
          action={
            <Button size="sm" onClick={runStep} loading={stepping}>
              <Play size={12} /> 지금 실행
            </Button>
          }
        >
          {signals.loading ? (
            <Spinner />
          ) : (
            <SignalTape
              signals={signals.data ?? []}
              threshold={agent.data?.confidence_threshold ?? 0.55}
            />
          )}
        </Card>

        <Card eyebrow="AGENT" title="자동매매 상태">
          {agent.data ? (
            <div className="space-y-3.5">
              <div className="flex items-center justify-between">
                <span className="text-[13px] text-muted">상태</span>
                <Badge tone={agent.data.enabled ? "brand" : "neutral"}>
                  {agent.data.enabled ? "실행 중" : "정지"}
                </Badge>
              </div>
              {[
                ["정책 모델", agent.data.model_name],
                ["대상 종목", `${agent.data.universe.length}종목`],
                ["신뢰도 임계값", agent.data.confidence_threshold.toFixed(2)],
                ["종목당 한도", `${agent.data.max_position_pct}%`],
                ["일일 손실 한도", `${agent.data.daily_loss_limit_pct}%`],
                ["거래 시간", `${agent.data.trading_start}–${agent.data.trading_end}`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-[13px] text-muted">{k}</span>
                  <span className="num text-[12.5px]">{v}</span>
                </div>
              ))}
              <Link to="/agent" className="block pt-1">
                <Button size="sm" className="w-full">
                  <Cpu size={13} /> 에이전트 설정
                </Button>
              </Link>
            </div>
          ) : (
            <Spinner />
          )}
        </Card>
      </div>

      {/* 보유 종목 + 최근 주문 */}
      <div className="grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-4">
        <Card eyebrow="PORTFOLIO" title="보유 종목" pad={false}>
          {a.holdings.length === 0 ? (
            <Empty
              icon={Wallet}
              title="보유 중인 종목이 없습니다"
              description="에이전트를 켜거나 주문 화면에서 직접 매수하면 여기에 표시됩니다."
              action={
                <Link to="/trade">
                  <Button size="sm" variant="primary">주문하기</Button>
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-muted text-[11.5px] border-b border-line">
                    <Th className="pl-5 text-left">종목</Th>
                    <Th>수량</Th>
                    <Th>평균단가</Th>
                    <Th>현재가</Th>
                    <Th>평가금액</Th>
                    <Th>평가손익</Th>
                    <Th className="pr-5">비중</Th>
                  </tr>
                </thead>
                <tbody>
                  {a.holdings.map((h) => (
                    <tr key={h.symbol} className="border-b border-line/60 last:border-0 hover:bg-raise/50 transition-colors">
                      <td className="pl-5 py-3">
                        <div className="font-medium">{h.name}</div>
                        <div className="num text-[11px] text-muted mt-0.5">{h.symbol}</div>
                      </td>
                      <Td>{h.quantity.toLocaleString("ko-KR")}</Td>
                      <Td>{won(h.avg_price)}</Td>
                      <Td>{won(h.current_price)}</Td>
                      <Td>{won(h.market_value)}</Td>
                      <Td className={toneClass(h.unrealized_pnl)}>
                        {signedWon(h.unrealized_pnl)}
                        <div className="text-[11px] mt-0.5">{signed(h.unrealized_pct)}</div>
                      </Td>
                      <td className="pr-5 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-[42px] h-[3px] rounded-full bg-raise overflow-hidden">
                            <div className="h-full bg-brand rounded-full" style={{ width: `${Math.min(100, h.weight_pct)}%` }} />
                          </div>
                          <span className="num text-[12px] w-[38px] text-right">{h.weight_pct.toFixed(1)}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          eyebrow="RECENT"
          title="최근 주문"
          action={<Link to="/orders"><Button size="sm" variant="ghost">전체 <ArrowUpRight size={13} /></Button></Link>}
          pad={false}
        >
          {orders.data?.items?.length ? (
            <ul className="divide-y divide-line/60">
              {orders.data.items.map((o) => (
                <li key={o.id} className="flex items-center gap-3 px-5 py-3">
                  <span className={cx("w-[3px] h-8 rounded-full shrink-0", o.side === "buy" ? "bg-up" : "bg-down")} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium truncate">{o.name || o.symbol}</span>
                      <Badge tone={o.side === "buy" ? "up" : "down"}>{o.side === "buy" ? "매수" : "매도"}</Badge>
                    </div>
                    <div className="num text-[11px] text-muted mt-1">
                      {dateTime(o.created_at)} · {o.source === "agent" ? "에이전트" : "수동"}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="num text-[12.5px]">{o.quantity}주</div>
                    <div className="num text-[11px] text-muted mt-0.5">{STATUS_LABEL[o.status]}</div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="주문 기록이 없습니다" description="에이전트가 첫 주문을 내면 여기에 쌓입니다." />
          )}
        </Card>
      </div>
    </div>
  );
}

function MiniMetric({ label, value, tone }) {
  return (
    <div className="text-right">
      <div className="text-[11px] text-muted mb-1">{label}</div>
      <div className={cx("num text-[14px]", tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-body")}>
        {value}
      </div>
    </div>
  );
}

function Th({ children, className }) {
  return <th className={cx("py-2.5 font-normal text-right", className)}>{children}</th>;
}
function Td({ children, className }) {
  return <td className={cx("py-3 text-right num", className)}>{children}</td>;
}
