import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Activity, BarChart3, ChevronsLeft, Command, Cpu, KeyRound,
  LayoutDashboard, LogOut, Moon, PieChart, Receipt, Search, Sun,
} from "lucide-react";
import { DEMO, api } from "../lib/api";
import { useApp } from "../lib/store";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "인사이트", icon: LayoutDashboard, end: true },
  { to: "/portfolio", label: "포트폴리오", icon: PieChart },
  { to: "/agent", label: "에이전트", icon: Cpu },
  { to: "/trade", label: "주문", icon: Activity },
  { to: "/orders", label: "거래 내역", icon: Receipt },
  { to: "/performance", label: "수익 분석", icon: BarChart3 },
];

export default function Shell({ children }) {
  const { env } = useApp();
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const current =
    NAV.find((n) => (n.end ? n.to === pathname : pathname.startsWith(n.to))) ??
    (pathname.startsWith("/keys") ? { label: "연결" } : null);

  return (
    <div className="min-h-full flex bg-ink">
      <Rail collapsed={collapsed} onCollapse={() => setCollapsed((c) => !c)} />
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar title={current?.label ?? "KAIRO"} />
        {DEMO && <DemoBanner />}
        {env === "live" && <LiveBanner />}
        <main className="flex-1 px-5 md:px-7 py-6 max-w-[1520px] w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}

/** 데모 빌드에서만 노출. 화면의 수치가 실거래 결과가 아님을 분명히 한다. */
function DemoBanner() {
  return (
    <div className="px-5 md:px-7 pt-4 max-w-[1520px] w-full mx-auto">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded border border-line bg-surface px-4 py-2.5 text-[12.5px]">
        <span className="text-brand font-medium">데모 빌드</span>
        <span className="text-muted">
          백엔드 없이 브라우저 안에서만 돌아갑니다. 시세·주문·수익률은 전부 합성 데이터이며
          실거래 성과가 아닙니다.
        </span>
      </div>
    </div>
  );
}

function LiveBanner() {
  return (
    <div className="px-5 md:px-7 pt-4 max-w-[1520px] w-full mx-auto">
      <div className="flex items-center gap-2.5 rounded border border-up/40 bg-up/8 px-4 h-10 text-[12.5px]">
        <span className="live-dot w-[6px] h-[6px] rounded-full bg-up shrink-0" />
        <span className="text-up font-medium">실계좌</span>
        <span className="text-muted">지금 보고 있는 화면의 모든 주문은 실제 자금으로 체결됩니다.</span>
      </div>
    </div>
  );
}

function Rail({ collapsed, onCollapse }) {
  const item = ({ isActive }) =>
    cx(
      "flex items-center gap-3 h-9 rounded-sm text-[13px] transition-colors border",
      collapsed ? "justify-center px-0" : "px-3",
      isActive
        ? "bg-raise border-line text-body font-medium"
        : "border-transparent text-muted hover:text-body hover:bg-raise/60",
    );

  return (
    <nav
      className={cx(
        "hidden md:flex shrink-0 flex-col border-r border-line bg-surface sticky top-0 h-screen transition-[width] duration-200",
        collapsed ? "w-[64px]" : "w-[216px]",
      )}
      aria-label="주 메뉴"
    >
      <div className={cx("h-[60px] flex items-center border-b border-line",
        collapsed ? "justify-center" : "justify-between px-4")}>
        <Mark withText={!collapsed} />
        {!collapsed && (
          <button onClick={onCollapse} aria-label="메뉴 접기"
            className="w-7 h-7 grid place-items-center rounded text-muted hover:text-body hover:bg-raise transition-colors">
            <ChevronsLeft size={15} />
          </button>
        )}
      </div>

      <div className="flex-1 py-3 px-2.5 space-y-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} title={collapsed ? label : undefined} className={item}>
            <Icon size={15.5} strokeWidth={1.9} className="shrink-0" />
            {!collapsed && label}
          </NavLink>
        ))}
      </div>

      <div className="px-2.5 pb-3 pt-2 border-t border-line space-y-1">
        <NavLink to="/keys" title={collapsed ? "연결" : undefined} className={item}>
          <KeyRound size={15.5} strokeWidth={1.9} className="shrink-0" />
          {!collapsed && "연결"}
        </NavLink>
        {collapsed && (
          <button onClick={onCollapse} aria-label="메뉴 펼치기"
            className="w-full h-9 grid place-items-center rounded-sm text-muted hover:text-body hover:bg-raise transition-colors">
            <ChevronsLeft size={15} className="rotate-180" />
          </button>
        )}
      </div>
    </nav>
  );
}

function Mark({ withText = true }) {
  return (
    <span className="flex items-center gap-2.5 shrink-0">
      <span className="w-[26px] h-[26px] rounded-sm bg-brand/12 border border-brand/30 grid place-items-center">
        <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden>
          <rect x="1" y="6" width="2.4" height="6" rx="0.6" fill="var(--brand)" />
          <rect x="5.3" y="2.6" width="2.4" height="9.4" rx="0.6" fill="var(--brand)" opacity="0.6" />
          <rect x="9.6" y="8" width="2.4" height="4" rx="0.6" fill="var(--brand)" opacity="0.32" />
        </svg>
      </span>
      {withText && <span className="text-[14px] font-bold tracking-[0.07em] whitespace-nowrap">KAIRO</span>}
    </span>
  );
}

function TopBar({ title }) {
  const { session, logout, env, setEnv, market, setMarket, theme, setTheme } = useApp();
  const [menu, setMenu] = useState(false);
  return (
    <header className="sticky top-0 z-30 h-[60px] shrink-0 border-b border-line bg-ink/90 backdrop-blur-md">
      <div className="h-full px-5 md:px-7 max-w-[1520px] mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <span className="md:hidden"><Mark withText={false} /></span>
          <h1 className="text-[15px] font-semibold tracking-[-0.01em] truncate">{title}</h1>
        </div>
        <div className="flex items-center gap-2">
          <DataSourceBadge env={env} market={market} />
          <SearchBox />
          {!DEMO && <MarketSwitch market={market} setMarket={setMarket} />}
          <EnvSwitch env={env} setEnv={setEnv} />
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "밝은 테마로 전환" : "어두운 테마로 전환"}
            className="w-[34px] h-[34px] grid place-items-center rounded-full border border-line text-muted hover:text-body hover:border-muted/50 transition-colors"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <div className="relative">
            <button onClick={() => setMenu((m) => !m)} aria-label="계정 메뉴"
              className="w-[34px] h-[34px] rounded-full bg-brand/12 border border-brand/30 grid place-items-center text-[12px] font-semibold text-brand hover:brightness-125 transition">
              {session?.name?.[0] ?? "?"}
            </button>
            {menu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenu(false)} />
                <div className="absolute right-0 top-11 z-20 w-[236px] rounded-md border border-line bg-surface p-1.5 shadow-2xl shadow-black/60 rise">
                  <div className="px-3 py-2.5 border-b border-line mb-1.5">
                    <p className="text-[13px] font-medium truncate">{session?.name}</p>
                    <p className="text-[11.5px] text-muted truncate">{session?.email}</p>
                  </div>
                  <button onClick={logout}
                    className="w-full flex items-center gap-2.5 h-9 px-3 rounded-sm text-[13px] text-muted hover:text-body hover:bg-raise transition-colors">
                    <LogOut size={14} /> 로그아웃
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

/** 시세가 실제 KIS에서 오는지 시뮬레이터에서 오는지 한눈에 보여 준다. */
function DataSourceBadge({ env, market }) {
  const [info, setInfo] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .marketStatus(env)
        .then((d) => alive && setInfo(d))
        .catch(() => alive && setInfo(null));
    load();
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [env, market]);

  if (!info) return null;

  const live = info.source === "kis";
  const 시장 = market === "us" ? "미국" : "국내";
  const label = live ? "실시세" : "시뮬레이터";
  const title = live
    ? info.account_linked
      ? `KIS ${시장} 실계좌 연동 — 시세·잔고·주문 모두 실제입니다.`
      : `KIS ${시장} 실시세 — 가격은 실제, 잔고와 체결은 시뮬레이터입니다.`
    : info.degraded
      ? `KIS ${시장} 조회 실패로 시뮬레이터 시세로 동작합니다.` +
        (info.last_error ? `\n사유: ${info.last_error}` : "") +
        (info.retry_in ? `\n${info.retry_in}초 뒤 다시 시도합니다.` : "")
      : info.configured
        ? market === "us"
          ? "미국 실시세가 꺼져 있습니다 (US_MARKET_DATA=false)."
          : "실시세가 꺼져 있습니다 (KIS_MARKET_DATA=false)."
        : "backend/.env 에 KIS_APP_KEY / KIS_APP_SECRET 를 넣으면 실시세로 바뀝니다.";

  return (
    <span
      title={title}
      className={cx(
        "hidden sm:inline-flex items-center gap-1.5 h-[26px] px-2.5 rounded-full border text-[11px] font-medium tabular-nums",
        live
          ? "border-brand/35 bg-brand/10 text-brand"
          : "border-line bg-raise text-muted",
      )}
    >
      <span
        className={cx(
          "w-1.5 h-1.5 rounded-full",
          live ? "bg-brand" : "bg-muted/60",
        )}
      />
      {label}
    </span>
  );
}

function SearchBox() {
  const [value, setValue] = useState("");
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.getElementById("kairo-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <label className="hidden lg:flex items-center gap-2 h-[34px] w-[206px] px-3 rounded-full border border-line bg-surface focus-within:border-muted/60 transition-colors">
      <Search size={14} className="text-muted shrink-0" />
      <input id="kairo-search" value={value} onChange={(e) => setValue(e.target.value)}
        placeholder="종목 검색"
        className="flex-1 min-w-0 bg-transparent text-[12.5px] outline-none placeholder:text-muted/70" />
      <kbd className="num flex items-center gap-0.5 text-[10px] text-muted border border-line rounded px-1 py-0.5">
        <Command size={9} />K
      </kbd>
    </label>
  );
}

function MarketSwitch({ market, setMarket }) {
  return (
    <div
      className="flex items-center h-[34px] p-0.5 rounded-full border border-line bg-surface"
      role="group"
      aria-label="거래 시장"
    >
      {[
        ["kr", "한국", "KRW"],
        ["us", "미국", "USD"],
      ].map(([value, label, cur]) => {
        const active = market === value;
        return (
          <button
            key={value}
            onClick={() => setMarket(value)}
            aria-pressed={active}
            title={`${label} 시장 (${cur})`}
            className={cx(
              "h-[30px] px-3 rounded-full text-[12px] font-medium transition-colors",
              active ? "bg-raise text-body" : "text-muted hover:text-body",
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function EnvSwitch({ env, setEnv }) {
  const live = env === "live";
  return (
    <div className={cx("flex items-center h-[34px] p-0.5 rounded-full border transition-colors",
      live ? "border-up/50 bg-up/8" : "border-line bg-surface")} role="group" aria-label="거래 환경">
      {[["paper", "모의투자"], ["live", "실계좌"]].map(([value, label]) => {
        const active = env === value;
        return (
          <button key={value} onClick={() => setEnv(value)} aria-pressed={active}
            className={cx("h-[30px] px-3 rounded-full text-[12px] font-medium transition-colors flex items-center gap-1.5",
              active ? (value === "live" ? "bg-up/20 text-up" : "bg-raise text-body") : "text-muted hover:text-body")}>
            {active && value === "live" && <span className="live-dot w-[5px] h-[5px] rounded-full bg-up" />}
            {label}
          </button>
        );
      })}
    </div>
  );
}
