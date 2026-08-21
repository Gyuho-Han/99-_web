import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { useApp } from "../lib/store";
import { Button, Field, Input } from "../components/ui";

export default function Login() {
  const { login, signup, toast } = useApp();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", name: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await login(form.email, form.password);
      else await signup(form);
      toast("환영합니다.", "success");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const useDemo = async () => {
    setBusy(true);
    setError("");
    try {
      await login("demo@kairo.dev", "kairo1234");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.05fr_1fr]">
      <Hero />

      <div className="flex items-center justify-center px-6 py-14 bg-ink">
        <div className="w-full max-w-[352px] rise">
          <div className="eyebrow mb-2.5">
            {mode === "login" ? "SIGN IN" : "CREATE ACCOUNT"}
          </div>
          <h1 className="text-[27px] font-bold tracking-[-0.02em] leading-tight">
            {mode === "login" ? "콘솔에 접속" : "계정 만들기"}
          </h1>
          <p className="mt-2.5 text-[13px] text-muted leading-relaxed">
            {mode === "login"
              ? "증권사 자격증명은 접속 후 별도로 등록합니다."
              : "가입 직후에는 모의투자 환경만 활성화됩니다."}
          </p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            <Field label="이메일" required>
              <Input
                type="email"
                required
                autoComplete="email"
                value={form.email}
                onChange={set("email")}
                placeholder="you@example.com"
              />
            </Field>

            {mode === "signup" && (
              <Field label="이름" required>
                <Input
                  required
                  maxLength={40}
                  value={form.name}
                  onChange={set("name")}
                  placeholder="홍길동"
                />
              </Field>
            )}

            <Field label="비밀번호" hint={mode === "signup" ? "8자 이상" : undefined} required>
              <Input
                type="password"
                required
                minLength={8}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={set("password")}
              />
            </Field>

            {error && (
              <p className="text-[12.5px] text-up leading-snug" role="alert">
                {error}
              </p>
            )}

            <Button type="submit" variant="primary" size="lg" loading={busy} className="w-full">
              {mode === "login" ? "접속" : "가입하고 시작"}
              <ArrowRight size={15} />
            </Button>
          </form>

          <div className="mt-5 flex items-center gap-3">
            <span className="flex-1 h-px bg-line" />
            <span className="text-[10.5px] text-muted">또는</span>
            <span className="flex-1 h-px bg-line" />
          </div>

          <Button onClick={useDemo} variant="primary" size="lg" className="w-full mt-5" disabled={busy}>
            데모 계정으로 둘러보기
          </Button>

          <p className="mt-6 text-center text-[12.5px] text-muted">
            {mode === "login" ? "계정이 없으신가요?" : "이미 계정이 있으신가요?"}{" "}
            <button
              onClick={() => {
                setMode(mode === "login" ? "signup" : "login");
                setError("");
              }}
              className="text-brand hover:underline underline-offset-2"
            >
              {mode === "login" ? "가입하기" : "로그인"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * 좌측 히어로.
 * 상품을 설명하는 문장 대신, 이 시스템이 실제로 만들어 내는 산출물(정책 출력)을
 * 그대로 보여 준다. 막대 높이는 신뢰도, 점선은 실행 임계값이다.
 */
function Hero() {
  const bars = [
    0.31, 0.44, 0.58, 0.72, 0.49, 0.35, 0.63, 0.81, 0.88, 0.52, 0.4, 0.29, 0.47,
    0.69, 0.77, 0.58, 0.42, 0.34, 0.61, 0.86, 0.74, 0.5, 0.38, 0.56,
  ];
  const acts = [
    "h", "h", "b", "b", "h", "h", "b", "b", "b", "h", "h", "s",
    "h", "s", "s", "h", "h", "h", "b", "b", "b", "h", "h", "b",
  ];
  const color = (a) =>
    a === "b" ? "var(--up)" : a === "s" ? "var(--down)" : "var(--muted)";

  return (
    <div className="relative hidden lg:flex flex-col justify-between px-14 py-12 bg-surface border-r border-line overflow-hidden">
      <div className="flex items-center gap-2.5">
        <div className="w-[26px] h-[26px] rounded border border-brand/40 grid place-items-center">
          <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden>
            <rect x="1" y="6" width="2.4" height="6" fill="var(--brand)" />
            <rect x="5.3" y="3" width="2.4" height="9" fill="var(--brand)" opacity="0.55" />
            <rect x="9.6" y="8" width="2.4" height="4" fill="var(--brand)" opacity="0.3" />
          </svg>
        </div>
        <span className="text-[14.5px] font-bold tracking-[0.06em]">KAIRO</span>
      </div>

      <div className="max-w-[440px]">
        <div className="eyebrow mb-4">POLICY OUTPUT · 24 STEPS</div>

        <div className="relative h-[132px] mb-7">
          <div
            className="absolute left-0 right-0 flex items-center pointer-events-none"
            style={{ bottom: 132 * 0.55 }}
          >
            <div
              className="flex-1 border-t border-dashed"
              style={{ borderColor: "var(--brand-dim)" }}
            />
            <span className="num text-[9.5px] text-brand pl-2">실행 임계값</span>
          </div>
          <div className="flex items-end gap-[5px] h-full">
            {bars.map((v, i) => (
              <span
                key={i}
                className="flex-1 rounded-t-[2px] rise"
                style={{
                  height: `${v * 100}%`,
                  background: color(acts[i]),
                  opacity: v >= 0.55 ? 0.95 : 0.3,
                  animationDelay: `${i * 26}ms`,
                }}
              />
            ))}
          </div>
        </div>

        <h2 className="text-[30px] font-bold tracking-[-0.025em] leading-[1.22]">
          정책이 무엇을 보았고
          <br />
          왜 그렇게 움직였는지까지
        </h2>
        <p className="mt-4 text-[13.5px] text-muted leading-relaxed">
          강화학습 에이전트의 행동, 신뢰도, 리스크 게이트 통과 여부를 매 스텝
          기록합니다. 주문이 나가지 않은 이유도 함께 남습니다.
        </p>
      </div>

      <dl className="grid grid-cols-3 gap-6 max-w-[440px]">
        {[
          ["연동", "KIS Open API"],
          ["평가", "Sharpe · MDD"],
          ["환경", "모의 / 실계좌"],
        ].map(([k, v]) => (
          <div key={k}>
            <dt className="eyebrow mb-2">{k}</dt>
            <dd className="text-[13px] font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
