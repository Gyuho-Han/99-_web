import { AlertTriangle, Check, Info, Loader2, X } from "lucide-react";
import { useApp } from "../lib/store";
import { isUSD } from "../lib/format";

const cx = (...c) => c.filter(Boolean).join(" ");

/* -------------------------------------------------------------------------
   Card — 상단의 눈금선(tickrule)이 계기판의 기준선 역할을 한다.
   ------------------------------------------------------------------------- */
export function Card({ title, eyebrow, action, children, className, style, pad = true }) {
  return (
    <section
      style={style}
      className={cx(
        "rounded-lg border border-line bg-surface overflow-hidden flex flex-col",
        className,
      )}
    >
      <div className="sheen" aria-hidden />
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 px-5 pt-4 pb-3">
          <div>
            {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
            {title && (
              <h2 className="text-[15px] font-semibold tracking-[-0.01em] leading-tight">
                {title}
              </h2>
            )}
          </div>
          {action}
        </header>
      )}
      {/* 헤더가 없는 카드는 본문이 상단 여백까지 책임진다. 예전에는 이게 없어서
          화면마다 <div className="pt-1"> 을 덧대 4px 로 버티고 있었다. */}
      <div
        className={cx(
          "flex-1 min-h-0",
          pad && (title || action ? "px-5 pb-5" : "p-5"),
        )}
      >
        {children}
      </div>
    </section>
  );
}

export function Button({
  children,
  variant = "default",
  size = "md",
  loading,
  className,
  ...props
}) {
  const variants = {
    default: "bg-raise border-line hover:border-brand/60 text-body",
    primary:
      "bg-brand/14 border-brand/45 text-brand hover:bg-brand/22 hover:border-brand",
    solid: "bg-indigo border-indigo text-white hover:brightness-110",
    danger: "bg-up/10 border-up/40 text-up hover:bg-up/18 hover:border-up",
    ghost: "bg-transparent border-transparent text-muted hover:text-body hover:bg-raise",
  };
  const sizes = {
    sm: "h-8 px-3 text-[12.5px]",
    md: "h-10 px-4 text-[13.5px]",
    lg: "h-12 px-5 text-[14.5px]",
  };
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded border font-medium",
        "transition-colors duration-150 disabled:opacity-45 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children, required }) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[12.5px] font-medium text-body">
          {label}
          {required && <span className="text-brand ml-1">*</span>}
        </span>
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
      {children}
      {error && <p className="mt-1.5 text-[11.5px] text-up">{error}</p>}
    </label>
  );
}

export function Input({ className, mono, ...props }) {
  return (
    <input
      {...props}
      className={cx(
        "w-full h-10 px-3 rounded border border-line bg-ink text-body text-[13.5px]",
        "placeholder:text-muted/60 transition-colors",
        "hover:border-muted/50 focus:border-brand focus:outline-none",
        mono && "num",
        className,
      )}
    />
  );
}

export function Select({ className, children, ...props }) {
  return (
    <select
      {...props}
      className={cx(
        "w-full h-10 px-3 rounded border border-line bg-ink text-body text-[13.5px]",
        "hover:border-muted/50 focus:border-brand focus:outline-none appearance-none",
        "bg-[length:11px] bg-no-repeat bg-[right_12px_center]",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath d='M1 1.5 6 6.5 11 1.5' stroke='%237d8fa6' stroke-width='1.6' fill='none' stroke-linecap='round'/%3E%3C/svg%3E\")",
      }}
    >
      {children}
    </select>
  );
}

export function Switch({ checked, onChange, label, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative w-[42px] h-[23px] rounded-full border transition-colors duration-200 shrink-0",
        checked ? "bg-brand/25 border-brand" : "bg-raise border-line",
        disabled && "opacity-40 pointer-events-none",
      )}
    >
      <span
        className={cx(
          "absolute top-[3px] w-[15px] h-[15px] rounded-full transition-all duration-200",
          checked ? "left-[23px] bg-brand" : "left-[3px] bg-muted",
        )}
      />
    </button>
  );
}

export function Badge({ tone = "neutral", children, className }) {
  const tones = {
    neutral: "border-line text-muted bg-raise",
    flat: "border-line text-muted bg-raise",
    up: "border-up/40 text-up bg-up/10",
    down: "border-down/40 text-down bg-down/10",
    brand: "border-brand/40 text-brand bg-brand/10",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 h-[22px] px-2 rounded-full border",
        "num text-[11px] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/**
 * 금액 조판. 레퍼런스처럼 정수부는 크게, 단위는 작게 붙인다.
 * 원화는 소수점을 쓰지 않으므로 "만/억" 단위를 작은 글자로 분리하고,
 * 달러는 소수점 두 자리를 작은 글자로 분리한다.
 */
export function Money({ value, size = 30, unit, className }) {
  // 달러: 1,234.56 을 "1,234" + ".56" 으로 나눠 조판한다.
  if (isUSD()) {
    const raw = value ?? 0;
    const neg = raw < 0;
    const abs = Math.abs(raw);
    const whole = Math.floor(abs);
    const cents = Math.round((abs - whole) * 100);
    return (
      <span
        className={cx("amount leading-none inline-flex items-baseline", className)}
        style={{ fontSize: size }}
      >
        {neg && <span className="mr-[0.06em]">−</span>}
        <span className="unit mr-[0.04em]">$</span>
        {whole.toLocaleString("en-US")}
        <span className="unit">.{String(cents).padStart(2, "0")}</span>
      </span>
    );
  }

  const v = Math.round(value ?? 0);
  const neg = v < 0;
  const abs = Math.abs(v);
  let head = abs.toLocaleString("ko-KR");
  let tail = unit ?? "원";

  if (abs >= 100_000_000) {
    const eok = Math.floor(abs / 100_000_000);
    const man = Math.round((abs % 100_000_000) / 10_000);
    head = `${eok.toLocaleString("ko-KR")}`;
    tail = man ? `억 ${man.toLocaleString("ko-KR")}만원` : "억원";
  } else if (abs >= 10_000) {
    head = Math.floor(abs / 10_000).toLocaleString("ko-KR");
    const rest = abs % 10_000;
    tail = rest ? `만 ${String(rest).padStart(4, "0")}원` : "만원";
  }

  return (
    <span className={cx("amount leading-none inline-flex items-baseline", className)} style={{ fontSize: size }}>
      {neg && <span className="mr-[0.06em]">−</span>}
      {head}
      <span className="unit">{tail}</span>
    </span>
  );
}

/** 큰 수치 하나 + 라벨 + 우측 상단 변화 배지 */
export function Stat({ label, value, badge, delta, tone, sub, size = 30 }) {
  const toneCls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-body";
  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-3">
        <span className="text-[12.5px] text-muted">{label}</span>
        {badge}
      </div>
      <div className={cx("leading-none", toneCls)} style={{ fontSize: size }}>
        {value}
      </div>
      {/* 숫자 0 은 falsy 라서 `delta && ...` 로 쓰면 JSX 가 "0" 을 그대로 그린다.
          빈 값과 0 을 구분하려면 null 검사여야 한다. */}
      {(delta != null && delta !== "") || sub ? (
        <div className="mt-2.5 flex items-center gap-2 text-[12px]">
          {delta != null && delta !== "" && (
            <span className={cx("num", toneCls)}>{delta}</span>
          )}
          {sub && <span className="text-muted">{sub}</span>}
        </div>
      ) : null}
    </div>
  );
}

/** 알약형 세그먼트 컨트롤 (레퍼런스의 Daily / Weekly) */
export function Segmented({ value, onChange, options, size = "md" }) {
  const h = size === "sm" ? "h-8" : "h-9";
  return (
    <div className={cx("inline-flex items-center p-0.5 rounded-full border border-line bg-surface", h)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cx(
              "h-full px-3.5 rounded-full text-[12.5px] font-medium transition-colors",
              active ? "bg-raise text-body" : "text-muted hover:text-body",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Empty({ title, description, action, icon: Icon = Info }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      <div className="w-10 h-10 rounded-full border border-line grid place-items-center mb-4">
        <Icon size={17} className="text-muted" />
      </div>
      <p className="text-[14px] font-medium">{title}</p>
      {description && (
        <p className="mt-1.5 text-[12.5px] text-muted max-w-[380px] leading-relaxed">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "불러오는 중" }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-14 text-muted text-[12.5px]">
      <Loader2 size={15} className="animate-spin" />
      {label}
    </div>
  );
}

export function ErrorNote({ message, onRetry }) {
  return (
    <div className="flex items-start gap-3 rounded border border-up/35 bg-up/8 px-4 py-3">
      <AlertTriangle size={15} className="text-up mt-0.5 shrink-0" />
      <div className="flex-1">
        <p className="text-[13px] text-body">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 text-[12px] text-brand hover:underline underline-offset-2"
          >
            다시 시도
          </button>
        )}
      </div>
    </div>
  );
}

export function Toasts() {
  const { toasts } = useApp();
  const icons = { info: Info, success: Check, error: X };
  const tones = {
    info: "border-line",
    success: "border-brand/50",
    error: "border-up/50",
  };
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => {
        const Icon = icons[t.tone] || Info;
        return (
          <div
            key={t.id}
            role="status"
            className={cx(
              "rise flex items-start gap-2.5 max-w-[340px] rounded border bg-surface",
              "px-4 py-3 text-[13px] shadow-2xl shadow-black/40",
              tones[t.tone],
            )}
          >
            <Icon
              size={14}
              className={cx(
                "mt-0.5 shrink-0",
                t.tone === "error" ? "text-up" : t.tone === "success" ? "text-brand" : "text-muted",
              )}
            />
            <span className="leading-snug">{t.message}</span>
          </div>
        );
      })}
    </div>
  );
}

export { cx };
