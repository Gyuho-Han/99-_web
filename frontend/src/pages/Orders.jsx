import { useState } from "react";
import { ChevronLeft, ChevronRight, Download, Receipt } from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { STATUS_LABEL, dateTime, price as fmtPrice, signedWon, toneClass } from "../lib/format";
import { Badge, Button, Card, Empty, ErrorNote, Segmented, Select, Spinner, cx } from "../components/ui";

export default function Orders() {
  const { env, toast } = useApp();
  const [page, setPage] = useState(1);
  const [side, setSide] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");

  const { data, error, loading, reload } = useAsync(
    () => api.orders(env, { page, page_size: 20, side, source, status }),
    [env, page, side, source, status],
  );

  const cancel = async (id) => {
    try {
      await api.cancelOrder(env, id);
      toast("주문을 취소했습니다.", "success");
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const exportCsv = () => {
    const rows = data?.items ?? [];
    if (!rows.length) return;
    const head = ["일시", "종목코드", "종목명", "구분", "수량", "주문가", "체결가", "수수료", "실현손익", "상태", "출처"];
    const body = rows.map((o) => [
      dateTime(o.created_at), o.symbol, o.name, o.side === "buy" ? "매수" : "매도",
      o.quantity, o.price, o.filled_price, o.fee, o.realized_pnl,
      STATUS_LABEL[o.status], o.source === "agent" ? "에이전트" : "수동",
    ]);
    const csv = "\uFEFF" + [head, ...body].map((r) => r.join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `kairo-orders-${env}-${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-4">
      <Card
        eyebrow="ORDER HISTORY"
        title={data ? `주문 ${data.total.toLocaleString("ko-KR")}건` : "거래 내역"}
        action={
          <Button size="sm" onClick={exportCsv} disabled={!data?.items?.length}>
            <Download size={13} /> CSV
          </Button>
        }
        pad={false}
      >
        <div className="flex flex-wrap items-center gap-2.5 px-5 pb-4">
          <Segmented
            size="sm"
            value={source}
            onChange={(v) => { setSource(v); setPage(1); }}
            options={[
              { value: "", label: "전체" },
              { value: "agent", label: "에이전트" },
              { value: "manual", label: "수동" },
            ]}
          />
          <Segmented
            size="sm"
            value={side}
            onChange={(v) => { setSide(v); setPage(1); }}
            options={[
              { value: "", label: "매수·매도" },
              { value: "buy", label: "매수" },
              { value: "sell", label: "매도" },
            ]}
          />
          <Select
            className="!h-8 !w-[132px] !text-[12.5px] rounded-full"
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          >
            <option value="">모든 상태</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </Select>
        </div>

        {error ? (
          <div className="px-5 pb-5"><ErrorNote message={error} onRetry={reload} /></div>
        ) : loading ? (
          <Spinner />
        ) : !data.items.length ? (
          <Empty
            icon={Receipt}
            title="조건에 맞는 주문이 없습니다"
            description="필터를 바꾸거나, 에이전트를 실행해 새 주문을 만들어 보세요."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px] min-w-[860px]">
                <thead>
                  <tr className="text-muted text-[11.5px] border-y border-line">
                    <th className="pl-5 py-2.5 text-left font-normal">일시</th>
                    <th className="py-2.5 text-left font-normal">종목</th>
                    <th className="py-2.5 text-left font-normal">구분</th>
                    <th className="py-2.5 text-right font-normal">수량</th>
                    <th className="py-2.5 text-right font-normal">주문가</th>
                    <th className="py-2.5 text-right font-normal">체결가</th>
                    <th className="py-2.5 text-right font-normal">수수료·세금</th>
                    <th className="py-2.5 text-right font-normal">실현손익</th>
                    <th className="py-2.5 text-center font-normal">상태</th>
                    <th className="pr-5 py-2.5 text-right font-normal">출처</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((o) => (
                    <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-raise/50 transition-colors align-top">
                      <td className="pl-5 py-3 num text-[12px] text-muted whitespace-nowrap">{dateTime(o.created_at)}</td>
                      <td className="py-3">
                        <div className="font-medium whitespace-nowrap">{o.name || o.symbol}</div>
                        <div className="num text-[11px] text-muted mt-0.5">{o.symbol}</div>
                      </td>
                      <td className="py-3">
                        <Badge tone={o.side === "buy" ? "up" : "down"}>
                          {o.side === "buy" ? "매수" : "매도"}
                        </Badge>
                        <div className="text-[11px] text-muted mt-1">
                          {o.order_type === "market" ? "시장가" : "지정가"}
                        </div>
                      </td>
                      <td className="py-3 text-right num">{o.quantity.toLocaleString("ko-KR")}</td>
                      <td className="py-3 text-right num">{fmtPrice(o.price)}</td>
                      <td className="py-3 text-right num">
                        {o.filled_price ? fmtPrice(o.filled_price) : "—"}
                      </td>
                      <td className="py-3 text-right num text-muted">
                        {o.fee ? fmtPrice(o.fee) : "—"}
                      </td>
                      <td className={cx("py-3 text-right num", toneClass(o.realized_pnl))}>
                        {o.realized_pnl ? signedWon(o.realized_pnl) : "—"}
                      </td>
                      <td className="py-3 text-center">
                        <span className={cx("num text-[12px]",
                          o.status === "filled" ? "text-body"
                            : o.status === "canceled" || o.status === "rejected" ? "text-muted"
                            : "text-brand")}>
                          {STATUS_LABEL[o.status]}
                        </span>
                        {o.note && (
                          <div className="text-[11px] text-muted mt-1 max-w-[190px] mx-auto leading-snug">
                            {o.note}
                          </div>
                        )}
                      </td>
                      <td className="pr-5 py-3 text-right">
                        <div className="text-[12px] text-muted">
                          {o.source === "agent" ? "에이전트" : "수동"}
                        </div>
                        {o.status === "pending" && (
                          <button onClick={() => cancel(o.id)}
                            className="mt-1 text-[11.5px] text-up hover:underline underline-offset-2">
                            취소
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between px-5 py-3.5 border-t border-line">
              <span className="num text-[12px] text-muted">
                {(data.page - 1) * data.page_size + 1}–
                {Math.min(data.page * data.page_size, data.total)} / {data.total}
              </span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  <ChevronLeft size={14} /> 이전
                </Button>
                <span className="num text-[12px] text-muted px-1">{page} / {totalPages}</span>
                <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  다음 <ChevronRight size={14} />
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
