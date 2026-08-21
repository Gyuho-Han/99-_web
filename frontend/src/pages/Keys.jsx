import { useState } from "react";
import { CheckCircle2, ExternalLink, Eye, EyeOff, KeyRound, Lock, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { useApp, useAsync } from "../lib/store";
import { dateTime } from "../lib/format";
import { Badge, Button, Card, Field, Input, Spinner, cx } from "../components/ui";

const ENVS = [
  { value: "paper", label: "모의투자", host: "openapivts.koreainvestment.com:29443" },
  { value: "live", label: "실계좌", host: "openapi.koreainvestment.com:9443" },
];

export default function Keys() {
  const { toast } = useApp();
  const creds = useAsync(() => api.credentials(), []);

  return (
    <div className="space-y-4 max-w-[1080px]">
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
            모의투자와 실계좌는 별개의 자격증명입니다. 한쪽을 등록해도 다른 쪽에는 영향이 없습니다.
          </Point>
          <Point>
            키는 <a href="https://apiportal.koreainvestment.com" target="_blank" rel="noreferrer"
              className="text-brand hover:underline underline-offset-2 inline-flex items-center gap-1">
              KIS 개발자센터 <ExternalLink size={11} />
            </a>에서 직접 발급받아 아래 입력란에 붙여 넣으세요. 다른 사람에게 공유하지 마세요.
          </Point>
        </ul>
      </Card>

      {creds.loading ? (
        <Spinner />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {ENVS.map((e) => (
            <CredentialCard
              key={e.value}
              env={e}
              cred={(creds.data ?? []).find((c) => c.env === e.value)}
              onChanged={creds.reload}
              toast={toast}
            />
          ))}
        </div>
      )}
    </div>
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

function CredentialCard({ env, cred, onChanged, toast }) {
  const [form, setForm] = useState({ app_key: "", app_secret: "", account_no: "" });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState(null);
  const isLive = env.value === "live";

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.saveCredential({ broker: "kis", env: env.value, ...form });
      setForm({ app_key: "", app_secret: "", account_no: "" });
      toast(`${env.label} 자격증명을 저장했습니다.`, "success");
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
      eyebrow={isLive ? "LIVE ACCOUNT" : "PAPER ACCOUNT"}
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
      <p className="num text-[11px] text-muted mb-4">{env.host}</p>

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

        <Field label="계좌번호" hint="예: 50123456-01" required>
          <Input required minLength={8} mono value={form.account_no} onChange={set("account_no")}
            placeholder="50123456-01" autoComplete="off" spellCheck={false} />
        </Field>

        <Button type="submit" variant={isLive ? "danger" : "primary"} loading={busy} className="w-full">
          <KeyRound size={14} />
          {cred ? "자격증명 교체" : `${env.label} 연결`}
        </Button>

        {isLive && (
          <p className="text-[11.5px] text-muted leading-relaxed">
            실계좌를 연결하면 에이전트가 실제 자금으로 주문을 냅니다. 먼저 모의투자에서
            리스크 한도와 정책 동작을 충분히 확인하세요.
          </p>
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
