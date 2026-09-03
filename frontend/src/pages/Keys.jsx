import { useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, ExternalLink, Eye, EyeOff,
  KeyRound, Lock, Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { dateTime } from "../lib/format";
import { Badge, Button, Card, Field, Input, Spinner, cx } from "../components/ui";

const ENVS = [
  { value: "paper", label: "모의투자", host: "openapivts.koreainvestment.com:29443" },
  { value: "live", label: "실계좌", host: "openapi.koreainvestment.com:9443" },
];

const MARKET_LABEL = { kr: "국내주식", us: "미국주식" };

/** 시장별로 다른 것은 계좌번호뿐이다. 앱키는 국내·미국이 같은 것을 쓴다. */
const ACCOUNT_HINT = {
  kr: { placeholder: "12345678-01", hint: "종합계좌번호. 예: 12345678-01" },
  us: { placeholder: "50123456-01", hint: "해외주식 계좌번호. 국내 계좌와 다릅니다" },
};

export default function Keys() {
  const { toast, env, market } = useApp();
  const creds = useAsync(() => api.credentials(), []);
  const status = useAsync(() => api.connectionStatus(env), [env]);

  const reloadAll = () => {
    creds.reload();
    status.reload();
  };

  const rows = (creds.data ?? []).filter((c) => (c.market ?? "kr") === market);

  return (
    <div className="space-y-4 max-w-[1080px]">
      <Flow status={status} market={market} env={env} />

      {creds.loading ? (
        <Spinner />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {ENVS.map((e) => (
            <CredentialCard
              key={e.value}
              env={e}
              market={market}
              cred={rows.find((c) => c.env === e.value)}
              locked={e.value === "live" && status.data?.live_trading_allowed === false}
              onChanged={reloadAll}
              toast={toast}
            />
          ))}
        </div>
      )}

      <Matrix matrix={status.data?.matrix} />
      <SecurityNote />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 연결 진행 상황                                                       */
/* ------------------------------------------------------------------ */

function Flow({ status, market, env }) {
  const data = status.data;
  const envLabel = env === "live" ? "실계좌" : "모의투자";

  if (status.loading && !data) return <Card><Spinner /></Card>;
  if (!data) {
    return (
      <Card eyebrow="CONNECTION" title="연결 진행 상황">
        <p className="text-[13px] text-muted">진행 상황을 불러오지 못했습니다.</p>
      </Card>
    );
  }

  const doneCount = data.steps.filter((s) => s.done).length;

  return (
    <Card
      eyebrow="CONNECTION"
      title={`${MARKET_LABEL[market]} · ${envLabel} 연결`}
      action={
        <Badge tone={data.ready ? "brand" : "neutral"}>
          {doneCount} / {data.steps.length} 단계
        </Badge>
      }
    >
      <p className="text-[13px] text-muted leading-relaxed mb-5">
        아래 네 단계를 모두 지나야 정책이 낸 신호가 실제 주문으로 나갑니다.
        상단의 <span className="text-body">한국 / 미국</span>,{" "}
        <span className="text-body">모의투자 / 실계좌</span> 토글이 가리키는 조합의 상태입니다.
      </p>

      <ol className="space-y-0">
        {data.steps.map((s, i) => (
          <Step
            key={s.key}
            index={i + 1}
            step={s}
            last={i === data.steps.length - 1}
            cta={
              s.key === "risk" || s.key === "run"
                ? { to: "/agent", label: s.key === "run" ? "에이전트 화면에서 가동" : "리스크 한도 확인" }
                : null
            }
          />
        ))}
      </ol>

      {data.lock_reason && (
        <div className="mt-5 flex items-start gap-2.5 rounded-sm border border-up/35 bg-up/8 px-4 py-3">
          <Lock size={14} className="text-up mt-0.5 shrink-0" />
          <div className="text-[12.5px] leading-relaxed">
            <p className="text-up font-medium mb-0.5">실계좌 주문이 잠겨 있습니다</p>
            <p className="text-muted">{data.lock_reason}</p>
            <p className="text-muted mt-1">
              잠긴 동안에도 자격증명 등록과 연결 테스트, 잔고·시세 조회는 됩니다.
              즉 연결이 제대로 됐는지는 지금 확인할 수 있습니다.
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}

function Step({ index, step, last, cta }) {
  return (
    <li className="flex gap-3.5">
      {/* 번호 + 세로선 */}
      <div className="flex flex-col items-center shrink-0">
        <span
          className={cx(
            "num w-[26px] h-[26px] rounded-full border grid place-items-center text-[11.5px] font-semibold",
            step.done
              ? "border-brand/50 bg-brand/12 text-brand"
              : "border-line bg-raise text-muted",
          )}
        >
          {step.done ? <Check size={13} /> : index}
        </span>
        {!last && <span className={cx("w-px flex-1 my-1", step.done ? "bg-brand/30" : "bg-line")} />}
      </div>

      <div className={cx("min-w-0", last ? "pb-0" : "pb-5")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className={cx("text-[13.5px] font-medium", !step.done && "text-muted")}>
            {step.title}
          </span>
          {step.done && <Badge tone="brand">완료</Badge>}
          {step.blocked && <Badge tone="up">잠김</Badge>}
        </div>
        <p className="text-[12.5px] text-muted leading-relaxed mt-1">{step.detail}</p>
        {cta && !step.done && !step.blocked && (
          <Link
            to={cta.to}
            className="inline-flex items-center gap-1 mt-2 text-[12.5px] text-brand hover:underline underline-offset-2"
          >
            {cta.label} <ArrowRight size={12} />
          </Link>
        )}
      </div>
    </li>
  );
}

/* ------------------------------------------------------------------ */
/* 네 조합 현황                                                         */
/* ------------------------------------------------------------------ */

function Matrix({ matrix }) {
  if (!matrix?.length) return null;
  const cell = (m, e) => matrix.find((x) => x.market === m && x.env === e);

  return (
    <Card eyebrow="OVERVIEW" title="등록 현황">
      <p className="text-[12.5px] text-muted leading-relaxed mb-4">
        자격증명은 시장(국내·미국)과 환경(모의투자·실계좌) 조합마다 따로 저장됩니다.
        한쪽을 등록해도 나머지 세 조합에는 영향이 없습니다.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px] border-collapse">
          <thead>
            <tr className="text-muted">
              <th className="text-left font-medium py-2 pr-4">시장</th>
              {ENVS.map((e) => (
                <th key={e.value} className="text-left font-medium py-2 pr-4">{e.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {["kr", "us"].map((m) => (
              <tr key={m} className="border-t border-line">
                <td className="py-2.5 pr-4">{MARKET_LABEL[m]}</td>
                {ENVS.map((e) => (
                  <td key={e.value} className="py-2.5 pr-4">
                    <MatrixCell state={cell(m, e.value)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function MatrixCell({ state }) {
  if (!state) return <span className="text-muted">—</span>;
  if (!state.registered) return <Badge>미등록</Badge>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge tone={state.verified ? "brand" : "neutral"}>
        {state.verified ? "연결 확인됨" : "미확인"}
      </Badge>
      {state.agent_enabled && <Badge tone="brand">가동 중</Badge>}
      {state.locked && <Badge tone="up">주문 잠김</Badge>}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* 자격증명 카드                                                        */
/* ------------------------------------------------------------------ */

function CredentialCard({ env, market, cred, locked, onChanged, toast }) {
  const [form, setForm] = useState({ app_key: "", app_secret: "", account_no: "" });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState(null);
  const isLive = env.value === "live";
  const account = ACCOUNT_HINT[market];

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      // market 을 반드시 함께 보낸다. 이것이 빠지면 미국 계좌를 넣어도 국내 자리에 저장된다.
      await api.saveCredential({ broker: "kis", env: env.value, market, ...form });
      setForm({ app_key: "", app_secret: "", account_no: "" });
      setResult(null);
      toast(`${MARKET_LABEL[market]} ${env.label} 자격증명을 저장했습니다.`, "success");
      onChanged();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setVerifying(true);
    setResult(null);
    try {
      const r = await api.verifyCredential(cred.id);
      setResult(r);
      toast(r.message, r.ok ? "success" : "error");
      onChanged();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setVerifying(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteCredential(cred.id);
      toast(`${env.label} 자격증명을 삭제했습니다.`, "success");
      onChanged();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      className={cx(isLive && "border-up/30")}
      eyebrow={`${market.toUpperCase()} · ${isLive ? "LIVE ACCOUNT" : "PAPER ACCOUNT"}`}
      title={`한국투자증권 · ${env.label}`}
      action={
        cred ? (
          <Badge tone={cred.last_verified_at ? "brand" : "neutral"}>
            {cred.last_verified_at ? "연결 확인됨" : "미확인"}
          </Badge>
        ) : (
          <Badge>미등록</Badge>
        )
      }
    >
      <p className="num text-[11px] text-muted mb-1">{env.host}</p>
      <p className="text-[11.5px] text-muted mb-4">
        {MARKET_LABEL[market]} · {account.hint}
      </p>

      {cred && (
        <div className="rounded-sm border border-line bg-ink px-4 py-3.5 mb-4 space-y-2.5">
          <Row label="App Key" value={cred.app_key_masked} />
          <Row label="계좌번호" value={cred.account_no_masked} />
          <Row
            label="마지막 확인"
            value={cred.last_verified_at ? dateTime(cred.last_verified_at) : "없음"}
          />
          {cred.last_error && <p className="text-[12px] text-up leading-snug pt-1">{cred.last_error}</p>}
          {result?.ok && (
            <p className="flex items-center gap-1.5 text-[12px] text-brand pt-1">
              <CheckCircle2 size={12} /> {result.message}
            </p>
          )}
          <div className="flex gap-2 pt-2">
            <Button size="sm" variant="primary" onClick={verify} loading={verifying}>
              연결 테스트
            </Button>
            <Button size="sm" variant="danger" onClick={remove} disabled={busy}>
              <Trash2 size={12} /> 삭제
            </Button>
          </div>
        </div>
      )}

      <form onSubmit={save} className="space-y-3.5">
        <Field label="App Key" required>
          <Input required minLength={8} mono value={form.app_key} onChange={set("app_key")}
            placeholder="PS0abc..." autoComplete="off" spellCheck={false} />
        </Field>

        <Field
          label="App Secret"
          required
          hint={
            <button type="button" onClick={() => setShow((s) => !s)}
              className="inline-flex items-center gap-1 text-muted hover:text-body transition-colors">
              {show ? <EyeOff size={11} /> : <Eye size={11} />}
              {show ? "가리기" : "보기"}
            </button>
          }
        >
          <Input required minLength={8} mono type={show ? "text" : "password"}
            value={form.app_secret} onChange={set("app_secret")} autoComplete="off" spellCheck={false} />
        </Field>

        <Field label="계좌번호" hint={account.hint} required>
          <Input required minLength={8} mono value={form.account_no} onChange={set("account_no")}
            placeholder={account.placeholder} autoComplete="off" spellCheck={false} />
        </Field>

        <Button type="submit" variant={isLive ? "danger" : "primary"} loading={busy} className="w-full">
          <KeyRound size={14} />
          {cred ? "자격증명 교체" : `${env.label} 연결`}
        </Button>

        {isLive && (
          locked ? (
            <p className="flex items-start gap-2 text-[11.5px] text-muted leading-relaxed">
              <Lock size={12} className="mt-[2px] shrink-0 text-up" />
              지금은 실계좌 주문이 서버에서 잠겨 있습니다. 키를 등록해 연결 확인까지는 되지만
              주문은 나가지 않습니다.
            </p>
          ) : (
            <p className="flex items-start gap-2 text-[11.5px] text-muted leading-relaxed">
              <AlertTriangle size={12} className="mt-[2px] shrink-0 text-up" />
              실계좌를 연결하면 에이전트가 실제 자금으로 주문을 냅니다. 먼저 모의투자에서
              리스크 한도와 정책 동작을 충분히 확인하세요.
            </p>
          )
        )}
      </form>
    </Card>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-[12.5px] text-muted">{label}</span>
      <span className="num text-[12.5px]">{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function SecurityNote() {
  return (
    <Card eyebrow="SECURITY" title="자격증명은 어떻게 보관되나요">
      <ul className="space-y-2.5 text-[13px] text-muted leading-relaxed">
        <Point>
          App Secret과 계좌번호는 서버에서 <span className="text-body">Fernet(AES-128-CBC + HMAC)</span>으로
          암호화해 저장합니다. 복호화 키는 데이터베이스가 아니라 서버 환경변수에 있습니다.
        </Point>
        <Point>
          어떤 응답에도 평문 키가 실리지 않습니다. 화면과 로그에는 앞뒤 몇 자만 남긴 마스킹 값만 나갑니다.
        </Point>
        <Point>
          자격증명 등록·검증·삭제와 자동매매 토글은 감사로그(audit_logs)에 남습니다.
        </Point>
        <Point>
          키는 <a href="https://apiportal.koreainvestment.com" target="_blank" rel="noreferrer"
            className="text-brand hover:underline underline-offset-2 inline-flex items-center gap-1">
            KIS 개발자센터 <ExternalLink size={11} />
          </a>에서 직접 발급받아 입력란에 붙여 넣으세요. 다른 사람에게 공유하지 마세요.
        </Point>
      </ul>
    </Card>
  );
}

function Point({ children }) {
  return (
    <li className="flex gap-2.5">
      <Lock size={13} className="mt-[3px] shrink-0 text-brand" />
      <span>{children}</span>
    </li>
  );
}
