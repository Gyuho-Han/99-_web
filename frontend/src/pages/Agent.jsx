import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Play, Save, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { ACTION_LABEL } from "../lib/format";
import SignalTape from "../components/SignalTape";
import {
  Badge, Button, Card, ErrorNote, Field, Input, Select, Spinner, Switch, cx,
} from "../components/ui";

export default function Agent() {
  const { env, toast, isLive } = useApp();
  const cfg = useAsync(() => api.agentConfig(env), [env]);
  const signals = useAsync(() => api.signals(env, 60), [env]);
  const universe = useAsync(() => api.universe(), []);

  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    if (cfg.data) setDraft({ ...cfg.data, universe: [...cfg.data.universe] });
  }, [cfg.data]);

  if (cfg.error) return <ErrorNote message={cfg.error} onRetry={cfg.reload} />;
  if (!draft) return <Spinner />;

  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  const dirty = JSON.stringify(draft) !== JSON.stringify(cfg.data);

  const toggleSymbol = (s) =>
    set("universe", draft.universe.includes(s)
      ? draft.universe.filter((x) => x !== s)
      : [...draft.universe, s]);

  const save = async (override = {}) => {
    setSaving(true);
    try {
      const payload = {
        enabled: draft.enabled,
        model_name: draft.model_name,
        universe: draft.universe.join(","),
        max_position_pct: Number(draft.max_position_pct),
        max_order_amount: Number(draft.max_order_amount),
        daily_loss_limit_pct: Number(draft.daily_loss_limit_pct),
        confidence_threshold: Number(draft.confidence_threshold),
        trading_start: draft.trading_start,
        trading_end: draft.trading_end,
        ...override,
      };
      await api.updateAgentConfig(env, payload);
      toast("설정을 저장했습니다.", "success");
      cfg.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const runStep = async () => {
    setStepping(true);
    try {
      const res = await api.agentStep(env, true);
      setPreview(res.results);
      signals.reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setStepping(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* 실행 스위치 */}
      <Card className={cx(draft.enabled && "border-brand/35")}>
        <div className="flex flex-wrap items-center justify-between gap-5">
          <div className="flex items-start gap-4">
            <span className={cx("mt-1 w-2 h-2 rounded-full shrink-0",
              draft.enabled ? "bg-brand live-dot" : "bg-muted")} />
            <div>
              <div className="flex items-center gap-2.5 mb-1.5">
                <h2 className="text-[16px] font-semibold">자동매매</h2>
                <Badge tone={draft.enabled ? "brand" : "neutral"}>
                  {draft.enabled ? "실행 중" : "정지"}
                </Badge>
                {isLive && <Badge tone="up">실계좌</Badge>}
              </div>
              <p className="text-[12.5px] text-muted leading-relaxed max-w-[520px]">
                켜면 정책이 주기적으로 시세를 읽고, 아래 리스크 한도를 모두 통과한 신호만
                주문으로 나갑니다. 차단된 신호도 기록은 남습니다.
              </p>
            </div>
          </div>
          <Switch
            checked={draft.enabled}
            onChange={(v) => { set("enabled", v); save({ enabled: v }); }}
            label="자동매매 실행"
          />
        </div>

        {isLive && draft.enabled && (
          <div className="mt-4 flex items-start gap-2.5 rounded-sm border border-up/35 bg-up/8 px-4 py-3">
            <AlertTriangle size={14} className="text-up mt-0.5 shrink-0" />
            <p className="text-[12.5px] leading-relaxed">
              실계좌에서 자동매매가 켜져 있습니다. 실제 자금으로 주문이 나갑니다.
            </p>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-4">
        {/* 정책 */}
        <Card eyebrow="POLICY" title="정책 모델">
          <div className="space-y-4">
            <Field label="사용할 정책" hint="학습한 모델은 서버에 등록하면 여기 나타납니다">
              <Select value={draft.model_name} onChange={(e) => set("model_name", e.target.value)}>
                {[...new Set([draft.model_name, ...draft.available_models])].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </Select>
            </Field>

            <div>
              <div className="text-[12.5px] font-medium mb-2.5">대상 종목</div>
              <div className="flex flex-wrap gap-2">
                {(universe.data ?? []).map((u) => {
                  const on = draft.universe.includes(u.symbol);
                  return (
                    <button key={u.symbol} onClick={() => toggleSymbol(u.symbol)}
                      aria-pressed={on}
                      className={cx(
                        "h-8 px-3 rounded-full border text-[12.5px] transition-colors",
                        on ? "border-brand/50 bg-brand/12 text-brand" : "border-line text-muted hover:text-body",
                      )}>
                      {u.name}
                      <span className="num text-[10.5px] ml-1.5 opacity-70">{u.symbol}</span>
                    </button>
                  );
                })}
              </div>
              {draft.universe.length === 0 && (
                <p className="mt-2 text-[11.5px] text-up">최소 한 종목은 선택해야 합니다.</p>
              )}
            </div>

            <Field label="신뢰도 임계값" hint={draft.confidence_threshold.toFixed(2)}>
              <input type="range" min="0" max="0.95" step="0.01" className="w-full"
                value={draft.confidence_threshold}
                onChange={(e) => set("confidence_threshold", Number(e.target.value))} />
              <p className="mt-2 text-[11.5px] text-muted leading-relaxed">
                이 값보다 낮은 신뢰도의 신호는 주문으로 나가지 않습니다. 높일수록 거래가
                줄고 신중해집니다.
              </p>
            </Field>
          </div>
        </Card>

        {/* 리스크 */}
        <Card
          eyebrow="RISK LIMITS"
          title="리스크 한도"
          action={<ShieldCheck size={15} className="text-brand" />}
        >
          <div className="grid grid-cols-2 gap-4">
            <Field label="종목당 최대 비중" hint="%">
              <Input type="number" mono min={1} max={100} step={1}
                value={draft.max_position_pct}
                onChange={(e) => set("max_position_pct", e.target.value)} />
            </Field>
            <Field label="1회 최대 주문금액" hint="원">
              <Input type="number" mono min={10000} step={100000}
                value={draft.max_order_amount}
                onChange={(e) => set("max_order_amount", e.target.value)} />
            </Field>
            <Field label="일일 손실 한도" hint="%">
              <Input type="number" mono min={0.5} max={50} step={0.5}
                value={draft.daily_loss_limit_pct}
                onChange={(e) => set("daily_loss_limit_pct", e.target.value)} />
            </Field>
            <Field label="거래 시간">
              <div className="flex items-center gap-2">
                <Input type="time" mono value={draft.trading_start}
                  onChange={(e) => set("trading_start", e.target.value)} />
                <span className="text-muted">–</span>
                <Input type="time" mono value={draft.trading_end}
                  onChange={(e) => set("trading_end", e.target.value)} />
              </div>
            </Field>
          </div>

          <p className="mt-4 text-[11.5px] text-muted leading-relaxed">
            일일 손실 한도에 닿으면 그날의 신규 주문이 전부 중단됩니다. 이미 보유한
            포지션은 그대로 유지됩니다.
          </p>

          <div className="flex gap-2 mt-5">
            <Button variant="primary" onClick={() => save()} loading={saving}
              disabled={!dirty || draft.universe.length === 0}>
              <Save size={14} /> {dirty ? "변경사항 저장" : "저장됨"}
            </Button>
            <Button onClick={runStep} loading={stepping}>
              <Play size={13} /> 미리 실행
            </Button>
          </div>
        </Card>
      </div>

      {/* 미리보기 결과 */}
      {preview && (
        <Card eyebrow="DRY RUN" title="정책 미리 실행 결과" pad={false}>
          <div className="px-5 pb-2 -mt-1">
            <p className="text-[12px] text-muted">
              주문은 나가지 않았습니다. 지금 자동매매를 켜면 어떤 판단을 내리는지만 보여 줍니다.
            </p>
          </div>
          <div className="divide-y divide-line/60 border-t border-line mt-3">
            {preview.map((r) => (
              <div key={r.symbol} className="flex items-center gap-4 px-5 py-3.5">
                <span className={cx("w-[3px] h-9 rounded-full shrink-0",
                  r.action === "buy" ? "bg-up" : r.action === "sell" ? "bg-down" : "bg-muted")} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-medium">{r.name}</span>
                    <Badge tone={r.action === "buy" ? "up" : r.action === "sell" ? "down" : "neutral"}>
                      {ACTION_LABEL[r.action]}
                    </Badge>
                  </div>
                  <p className="text-[11.5px] text-muted mt-1 leading-snug">{r.reason}</p>
                </div>
                <div className="text-right shrink-0">
                  <div className="num text-[13px]">{r.confidence.toFixed(2)}</div>
                  <div className="text-[10.5px] text-muted mt-0.5">신뢰도</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card eyebrow="SIGNAL LOG" title="신호 기록">
        {signals.loading ? (
          <Spinner />
        ) : (
          <SignalTape signals={signals.data ?? []} threshold={draft.confidence_threshold} height={132} />
        )}
      </Card>

      <p className="text-[12px] text-muted">
        증권사 자격증명이 없으면 내장 시뮬레이터로 동작합니다.{" "}
        <Link to="/keys" className="text-brand hover:underline underline-offset-2">API 키 등록</Link>
      </p>
    </div>
  );
}
