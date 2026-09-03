/**
 * 데모 모드 데이터 계층.
 *
 * 백엔드 없이 브라우저에서만 화면을 확인할 수 있도록, 실제 API와 같은 모양의
 * 응답을 만들어 낸다. 시세는 종목코드를 시드로 하는 결정적 난수열이므로
 * 새로고침해도 같은 과거 시계열이 나온다. 주문·설정은 메모리에만 남는다.
 */

const UNIVERSE = {
  "005930": ["삼성전자", 74800],
  "000660": ["SK하이닉스", 197500],
  "035420": ["NAVER", 214000],
  "051910": ["LG화학", 382000],
  "005380": ["현대차", 246500],
  "035720": ["카카오", 41300],
  "207940": ["삼성바이오로직스", 812000],
  "068270": ["셀트리온", 178600],
};

const HORIZON = 520;
const START_EQUITY = 10_000_000;

function mulberry(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function seedOf(s) {
  let h = 2166136261;
  for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}
function gauss(rnd) {
  return (
    Math.sqrt(-2 * Math.log(1 - rnd())) * Math.cos(2 * Math.PI * rnd())
  );
}

const seriesCache = new Map();
function series(symbol) {
  if (seriesCache.has(symbol)) return seriesCache.get(symbol);
  const [, base] = UNIVERSE[symbol] ?? [symbol, 50000];
  const rnd = mulberry(seedOf(symbol));
  const drift = 0.0004;
  const vol = 0.018;
  let price = base * 0.82;
  const out = [];
  const today = new Date();

  for (let i = HORIZON; i > 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    if (d.getDay() === 0 || d.getDay() === 6) continue;
    price *= Math.exp(drift - 0.5 * vol * vol + vol * gauss(rnd));
    const o = price * (1 + gauss(rnd) * 0.003);
    const c = price;
    const r10 = (v) => Math.round(v / 10) * 10;
    out.push({
      date: d.toISOString().slice(0, 10),
      open: r10(o),
      high: r10(Math.max(o, c) * (1 + Math.abs(gauss(rnd)) * 0.004)),
      low: r10(Math.min(o, c) * (1 - Math.abs(gauss(rnd)) * 0.004)),
      close: r10(c),
      volume: Math.round(Math.abs(8_000_000 + gauss(rnd) * 2_500_000)),
    });
  }
  seriesCache.set(symbol, out);
  return out;
}

function quoteOf(symbol) {
  const s = series(symbol);
  const last = s.at(-1);
  const prev = s.at(-2);
  const [name] = UNIVERSE[symbol] ?? [symbol];
  const jitter = gauss(mulberry(seedOf(symbol) + new Date().getMinutes())) * 0.0015;
  const price = Math.round((last.close * (1 + jitter)) / 10) * 10;
  return {
    symbol,
    name,
    price,
    prev_close: prev.close,
    change: price - prev.close,
    change_pct: +(((price - prev.close) / prev.close) * 100).toFixed(2),
    open: last.open,
    high: Math.max(last.high, price),
    low: Math.min(last.low, price),
    volume: last.volume,
    ts: new Date().toISOString(),
  };
}

/* ---------------------------------------------------------------------------
   6개월치 백테스트 이력 (골든크로스 진입 / 데드크로스·손절·익절 청산)
   --------------------------------------------------------------------------- */
function buildHistory() {
  const symbols = ["005930", "000660", "035420"];
  const byDate = Object.fromEntries(
    symbols.map((s) => [s, Object.fromEntries(series(s).map((c) => [c.date, c]))]),
  );
  const days = series("005930")
    .map((c) => c.date)
    .slice(-180);

  const benchBase =
    symbols.reduce((a, s) => a + byDate[s][days[0]].close, 0) / symbols.length;

  let cash = START_EQUITY;
  const held = {};
  const orders = [];
  const signals = [];
  const curve = [];
  let oid = 1;

  days.forEach((d, i) => {
    symbols.forEach((s) => {
      const c = byDate[s][d];
      const hist = days
        .slice(Math.max(0, i - 25), i + 1)
        .map((x) => byDate[s][x].close);
      if (hist.length < 21) return;

      const avg = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
      const sma5 = avg(hist.slice(-5));
      const sma20 = avg(hist.slice(-20));
      const p5 = avg(hist.slice(-6, -1));
      const p20 = avg(hist.slice(-21, -1));
      const edge = (sma5 / sma20 - 1) * 100;
      const pos = held[s];
      const ret = pos ? c.close / pos.avg - 1 : 0;

      const golden = sma5 > sma20 && p5 <= p20;
      const dead = sma5 < sma20 && p5 >= p20;

      let action = "hold";
      let conf = 0.5;
      if (golden && !pos) {
        action = "buy";
        conf = Math.min(0.95, 0.6 + Math.abs(edge) / 6);
      } else if (pos && (dead || ret < -0.06 || ret > 0.14)) {
        action = "sell";
        conf = Math.min(0.95, 0.6 + Math.abs(edge) / 6);
      }

      let executed = false;
      const ts = `${d}T${String(10 + (i % 5)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}:00`;

      if (action === "buy") {
        const n = Math.floor(Math.min(cash, 2_000_000) / c.close);
        if (n >= 1) {
          const cost = n * c.close;
          const fee = Math.round(cost * 0.00015);
          cash -= cost + fee;
          held[s] = { qty: n, avg: c.close };
          executed = true;
          orders.push({
            id: oid++, broker_order_id: `SIM${i}${s.slice(-2)}`, symbol: s,
            name: UNIVERSE[s][0], side: "buy", order_type: "limit",
            quantity: n, price: c.close, filled_quantity: n, filled_price: c.close,
            fee, realized_pnl: 0, status: "filled", source: "agent",
            note: `골든크로스 ${edge >= 0 ? "+" : ""}${edge.toFixed(2)}% (신뢰도 ${conf.toFixed(2)})`,
            created_at: ts, filled_at: ts,
          });
        }
      } else if (action === "sell" && pos) {
        const gross = pos.qty * c.close;
        const fee = Math.round(gross * 0.00195);
        const realized = Math.round((c.close - pos.avg) * pos.qty - fee);
        cash += gross - fee;
        executed = true;
        orders.push({
          id: oid++, broker_order_id: `SIM${i}${s.slice(-2)}S`, symbol: s,
          name: UNIVERSE[s][0], side: "sell", order_type: "limit",
          quantity: pos.qty, price: c.close, filled_quantity: pos.qty,
          filled_price: c.close, fee, realized_pnl: realized, status: "filled",
          source: "agent",
          note: ret < -0.06 ? "손절 -6% 도달" : ret > 0.14 ? "익절 +14% 도달"
            : `데드크로스 ${edge.toFixed(2)}%`,
          created_at: ts, filled_at: ts,
        });
        delete held[s];
      }

      if (i >= days.length - 12) {
        signals.push({
          id: signals.length + 1, symbol: s, action,
          confidence: +conf.toFixed(3),
          q_buy: +(edge / 2).toFixed(3),
          q_hold: 0.25,
          q_sell: +(-edge / 2).toFixed(3),
          price: c.close, executed,
          reason: `SMA 격차 ${edge >= 0 ? "+" : ""}${edge.toFixed(2)}%${
            executed ? "" : action === "hold" ? " — 관망" : " — 임계값 미달"
          }`,
          created_at: ts,
        });
      }
    });

    const hv = Object.entries(held).reduce((a, [s, p]) => a + p.qty * byDate[s][d].close, 0);
    const bench = symbols.reduce((a, s) => a + byDate[s][d].close, 0) / symbols.length;
    curve.push({
      date: d,
      equity: Math.round(cash + hv),
      benchmark: Math.round((START_EQUITY * bench) / benchBase),
    });
  });

  return { cash, held, orders: orders.reverse(), signals: signals.reverse(), curve };
}

const H = buildHistory();

/* --------------------------------- 지표 --------------------------------- */
const TD = 252;
const RF = 0.032 / TD;

function metrics(equity, pnls = []) {
  if (equity.length < 2)
    return {
      total_return_pct: 0, cagr_pct: 0, sharpe: 0, sortino: 0,
      max_drawdown_pct: 0, calmar: 0, volatility_pct: 0, win_rate_pct: 0,
      profit_factor: 0, trades: 0, best_day_pct: 0, worst_day_pct: 0,
    };

  const rets = equity.slice(1).map((v, i) => v / equity[i] - 1);
  const n = rets.length;
  const mean = rets.reduce((a, b) => a + b, 0) / n;
  const std = Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / n);

  let peak = -Infinity;
  let mdd = 0;
  equity.forEach((v) => {
    peak = Math.max(peak, v);
    mdd = Math.min(mdd, v / peak - 1);
  });

  const years = n / TD;
  const cagr = ((equity.at(-1) / equity[0]) ** (1 / years) - 1) * 100;
  const down = rets.filter((r) => r < RF);
  const dstd = down.length
    ? Math.sqrt(down.reduce((a, r) => a + (r - RF) ** 2, 0) / down.length)
    : 0;

  const wins = pnls.filter((p) => p > 0);
  const losses = pnls.filter((p) => p < 0);
  const gl = Math.abs(losses.reduce((a, b) => a + b, 0));

  const r2 = (v) => +v.toFixed(2);
  return {
    total_return_pct: r2((equity.at(-1) / equity[0] - 1) * 100),
    cagr_pct: r2(cagr),
    sharpe: r2(std ? ((mean - RF) / std) * Math.sqrt(TD) : 0),
    sortino: r2(dstd ? ((mean - RF) / dstd) * Math.sqrt(TD) : 0),
    max_drawdown_pct: r2(mdd * 100),
    calmar: r2(mdd ? cagr / Math.abs(mdd * 100) : 0),
    volatility_pct: r2(std * Math.sqrt(TD) * 100),
    win_rate_pct: pnls.length ? +((wins.length / pnls.length) * 100).toFixed(1) : 0,
    profit_factor: r2(gl ? wins.reduce((a, b) => a + b, 0) / gl : 0),
    trades: pnls.length,
    best_day_pct: r2(Math.max(...rets) * 100),
    worst_day_pct: r2(Math.min(...rets) * 100),
  };
}

function drawdowns(equity) {
  let peak = -Infinity;
  return equity.map((v) => {
    peak = Math.max(peak, v);
    return +((v / peak - 1) * 100).toFixed(2);
  });
}

function monthly(curve) {
  const buckets = {};
  curve.forEach((p) => (buckets[p.date.slice(0, 7)] ??= []).push(p.equity));
  let prev = null;
  return Object.keys(buckets).sort().map((m) => {
    const vals = buckets[m];
    const start = prev ?? vals[0];
    prev = vals.at(-1);
    return { month: m, return_pct: +((vals.at(-1) / start - 1) * 100).toFixed(2) };
  });
}

/* ------------------------------ 가변 상태 ------------------------------ */
const state = {
  cash: { paper: H.cash, live: 10_000_000 },
  held: { paper: { ...H.held }, live: {} },
  orders: { paper: [...H.orders], live: [] },
  signals: { paper: [...H.signals], live: [] },
  creds: [],
  cfg: {
    paper: base_cfg(),
    live: base_cfg(),
  },
  nextId: 9000,
};

function base_cfg() {
  return {
    enabled: false,
    risk_ack_at: null,
    live_locked: false,
    account_linked: false,
    order_cooldown_seconds: 300,
    max_daily_orders: 20,
    model_name: "heuristic-baseline",
    available_models: ["heuristic-baseline", "random"],
    universe: ["005930", "000660", "035420"],
    max_position_pct: 30,
    max_order_amount: 2_000_000,
    daily_loss_limit_pct: 3,
    confidence_threshold: 0.55,
    trading_start: "09:05",
    trading_end: "15:15",
    updated_at: new Date().toISOString(),
  };
}

const delay = (v, ms = 130) => new Promise((r) => setTimeout(() => r(v), ms));

function holdings(env) {
  return Object.entries(state.held[env]).map(([symbol, p]) => {
    const cur = quoteOf(symbol).price;
    const mv = p.qty * cur;
    return {
      symbol, name: UNIVERSE[symbol][0], quantity: p.qty,
      avg_price: Math.round(p.avg), current_price: cur, market_value: mv,
      unrealized_pnl: Math.round((cur - p.avg) * p.qty),
      unrealized_pct: +(((cur / p.avg) - 1) * 100).toFixed(2),
      weight_pct: 0,
    };
  });
}

function accountOf(env) {
  const hs = holdings(env);
  const hv = hs.reduce((a, h) => a + h.market_value, 0);
  const equity = state.cash[env] + hv;
  hs.forEach((h) => (h.weight_pct = equity ? +((h.market_value / equity) * 100).toFixed(1) : 0));
  const prev = env === "paper" ? H.curve.at(-1).equity : 10_000_000;
  return {
    env, connected: state.creds.some((c) => c.env === env), broker: "demo",
    cash: Math.round(state.cash[env]),
    holdings_value: Math.round(hv),
    total_equity: Math.round(equity),
    deposit_total: START_EQUITY,
    total_pnl: Math.round(equity - START_EQUITY),
    total_pnl_pct: +(((equity / START_EQUITY) - 1) * 100).toFixed(2),
    day_pnl: Math.round(equity - prev),
    day_pnl_pct: +(((equity / prev) - 1) * 100).toFixed(2),
    holdings: hs,
  };
}

function performanceOf(env, days) {
  const curve = env === "paper" ? H.curve.slice(-Math.round(days * 0.7)) : [];
  if (!curve.length) {
    const empty = metrics([]);
    return { env, metrics: empty, benchmark_metrics: empty, curve: [], monthly: [] };
  }
  const eq = curve.map((p) => p.equity);
  const dd = drawdowns(eq);
  const pnls = state.orders[env].filter((o) => o.realized_pnl).map((o) => o.realized_pnl);
  return {
    env,
    metrics: metrics(eq, pnls),
    benchmark_metrics: metrics(curve.map((p) => p.benchmark)),
    curve: curve.map((p, i) => ({ ...p, drawdown: dd[i] })),
    monthly: monthly(curve),
  };
}

function stepOnce(env) {
  const cfg = state.cfg[env];
  const acct = accountOf(env);
  return cfg.universe.map((symbol) => {
    const s = series(symbol);
    const closes = s.map((c) => c.close);
    const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const sma5 = avg(closes.slice(-5));
    const sma20 = avg(closes.slice(-20));

    const deltas = closes.slice(-15).map((v, i, a) => (i ? v - a[i - 1] : 0)).slice(1);
    const gains = deltas.filter((d) => d > 0);
    const losses = deltas.filter((d) => d < 0).map((d) => -d);
    const rsi = 100 - 100 / (1 + (gains.reduce((a, b) => a + b, 0) / 14) /
      (losses.reduce((a, b) => a + b, 0) / 14 || 1e-9));

    let score = sma5 > sma20 ? 0.9 : -0.9;
    const notes = [sma5 > sma20 ? "5일선이 20일선 위" : "5일선이 20일선 아래"];
    if (rsi < 32) { score += 1.1; notes.push(`RSI ${rsi.toFixed(0)} 과매도`); }
    else if (rsi > 70) { score -= 1.1; notes.push(`RSI ${rsi.toFixed(0)} 과매수`); }

    const h = acct.holdings.find((x) => x.symbol === symbol);
    if (h && h.weight_pct > 40) { score -= 0.7; notes.push("보유 비중 과다"); }

    const q = { buy: +score.toFixed(3), hold: 0.25, sell: +(-score).toFixed(3) };
    const action = Object.keys(q).reduce((a, b) => (q[a] >= q[b] ? a : b));
    const sorted = Object.values(q).sort((a, b) => b - a);
    const confidence = +(1 / (1 + Math.exp(-(sorted[0] - sorted[1]) * 1.6))).toFixed(3);

    return {
      symbol, name: UNIVERSE[symbol][0], action, confidence, q_values: q,
      price: quoteOf(symbol).price, executed: false,
      reason: `${notes.slice(0, 3).join(" · ")} — 미리보기 실행`,
    };
  });
}

const maskOf = (v, head = 4, tail = 4) =>
  v.length <= head + tail ? "•".repeat(v.length) : `${v.slice(0, head)}${"•".repeat(8)}${v.slice(-tail)}`;

/* ------------------------------- 공개 API ------------------------------- */
export const demoApi = {
  marketStatus: async () => ({
    market: "kr",
    source: "simulator",
    configured: false,
    enabled: false,
    degraded: false,
    account_linked: false,
    currency: "KRW",
  }),
  login: async () => delay({ access_token: "demo", user: { id: 1, email: "demo@kairo.dev", name: "데모 계정" } }),
  signup: async (p) => delay({ access_token: "demo", user: { id: 1, email: p.email, name: p.name } }),
  me: async () => delay({ id: 1, email: "demo@kairo.dev", name: "데모 계정" }),

  credentials: async () => delay(state.creds),
  saveCredential: async (p) => {
    const market = p.market ?? "kr";
    const row = {
      id: state.creds.length + 1, broker: p.broker, env: p.env, market,
      label: p.label || (p.env === "paper" ? "모의투자 계좌" : "실계좌"),
      app_key_masked: maskOf(p.app_key),
      account_no_masked: maskOf(p.account_no, 2, 2),
      is_active: true, last_verified_at: null, last_error: null,
      updated_at: new Date().toISOString(),
    };
    // 저장 단위는 (환경, 시장) 조합이다. 같은 조합만 덮어쓴다.
    state.creds = [
      ...state.creds.filter((c) => !(c.env === p.env && (c.market ?? "kr") === market)),
      row,
    ];
    return delay(row);
  },
  verifyCredential: async (id) => {
    const c = state.creds.find((x) => x.id === id);
    if (c) c.last_verified_at = new Date().toISOString();
    return delay({ ok: true, message: "데모 모드입니다. 실제 증권사 서버에는 연결하지 않았습니다." }, 600);
  },
  deleteCredential: async (id) => {
    state.creds = state.creds.filter((c) => c.id !== id);
    return delay(null);
  },

  universe: async () => delay(Object.entries(UNIVERSE).map(([symbol, [name]]) => ({ symbol, name }))),
  quote: async (symbol) => delay(quoteOf(symbol), 60),
  candles: async (symbol, _env, days = 120) => delay(series(symbol).slice(-days), 60),

  account: async (env) => delay(accountOf(env)),

  portfolio: async (env) => {
    const a = accountOf(env);
    const equity = a.total_equity || 1;
    // 체결된 주문을 종목별로 묶어 실현손익과 체결 건수를 만든다. 서버와 같은 규칙이다.
    const stats = new Map();
    state.orders[env]
      .filter((o) => o.status === "filled")
      .forEach((o) => {
        const s = stats.get(o.symbol) ?? {
          symbol: o.symbol, name: o.name, realized_pnl: 0, trade_count: 0,
          last_traded_at: o.created_at,
        };
        s.realized_pnl += o.realized_pnl ?? 0;
        s.trade_count += 1;
        if (o.created_at > s.last_traded_at) s.last_traded_at = o.created_at;
        stats.set(o.symbol, s);
      });

    const held = new Set(a.holdings.map((h) => h.symbol));
    return delay({
      ...a,
      holdings: a.holdings.map((h) => ({
        ...h,
        realized_pnl: Math.round(stats.get(h.symbol)?.realized_pnl ?? 0),
        trade_count: stats.get(h.symbol)?.trade_count ?? 0,
        last_traded_at: stats.get(h.symbol)?.last_traded_at ?? null,
      })),
      closed: [...stats.values()]
        .filter((s) => !held.has(s.symbol))
        .map((s) => ({ ...s, realized_pnl: Math.round(s.realized_pnl) }))
        .sort((x, y) => (x.last_traded_at < y.last_traded_at ? 1 : -1)),
      cash_weight_pct: +((a.cash / equity) * 100).toFixed(1),
      realized_total: Math.round(
        [...stats.values()].reduce((t, s) => t + s.realized_pnl, 0),
      ),
      realized_supported: true,
    });
  },

  orders: async (env, p = {}) => {
    let items = state.orders[env];
    if (p.side) items = items.filter((o) => o.side === p.side);
    if (p.source) items = items.filter((o) => o.source === p.source);
    if (p.status) items = items.filter((o) => o.status === p.status);
    const page = p.page ?? 1;
    const size = p.page_size ?? 20;
    return delay({
      items: items.slice((page - 1) * size, page * size),
      total: items.length, page, page_size: size,
    });
  },

  placeOrder: async (env, p) => {
    const q = quoteOf(p.symbol);
    const price = p.order_type === "market" || !p.price ? q.price : p.price;
    const gross = price * p.quantity;
    const pos = state.held[env][p.symbol];

    if (p.side === "buy") {
      const fee = Math.round(gross * 0.00015);
      if (state.cash[env] < gross + fee) throw new Error("주문 가능 금액이 부족합니다.");
      state.cash[env] -= gross + fee;
      const qty = (pos?.qty ?? 0) + p.quantity;
      state.held[env][p.symbol] = { qty, avg: ((pos?.avg ?? 0) * (pos?.qty ?? 0) + gross) / qty };
    } else {
      if (!pos || pos.qty < p.quantity) throw new Error("보유 수량이 부족합니다.");
      const fee = Math.round(gross * 0.00195);
      state.cash[env] += gross - fee;
      pos.qty -= p.quantity;
      if (!pos.qty) delete state.held[env][p.symbol];
    }

    const now = new Date().toISOString();
    const order = {
      id: state.nextId++, broker_order_id: `DEMO${state.nextId}`,
      symbol: p.symbol, name: q.name, side: p.side, order_type: p.order_type,
      quantity: p.quantity, price, filled_quantity: p.quantity, filled_price: price,
      fee: Math.round(gross * (p.side === "buy" ? 0.00015 : 0.00195)),
      realized_pnl: 0, status: "filled", source: "manual",
      note: "데모 체결", created_at: now, filled_at: now,
    };
    state.orders[env] = [order, ...state.orders[env]];
    return delay(order, 350);
  },

  cancelOrder: async (env, id) => {
    const o = state.orders[env].find((x) => x.id === id);
    if (o) o.status = "canceled";
    return delay(o);
  },

  performance: async (env, days = 180) => delay(performanceOf(env, days)),

  agentConfig: async (env) => delay(state.cfg[env]),
  updateAgentConfig: async (env, p) => {
    const cfg = state.cfg[env];
    // risk_ack 는 설정값이 아니라 "한도를 확인했다"는 일회성 신호다.
    // 서버와 똑같이 저장하지 않고 확인 시각만 남긴다.
    const { risk_ack, ...rest } = p;
    if (risk_ack) cfg.risk_ack_at = new Date().toISOString();
    if (rest.enabled === true && !cfg.risk_ack_at) {
      throw new Error("자동매매를 켜기 전에 리스크 한도를 확인해야 합니다.");
    }
    Object.entries(rest).forEach(([k, v]) => {
      if (v === undefined || v === null) return;
      cfg[k] = k === "universe" ? String(v).split(",").filter(Boolean) : v;
    });
    cfg.updated_at = new Date().toISOString();
    return delay({ ...cfg });
  },

  connectionStatus: async (env) => {
    const cred = state.creds.find((c) => c.env === env && (c.market ?? "kr") === "kr");
    const cfg = state.cfg[env];
    const step = (key, title, done, detail) => ({ key, title, done, detail, blocked: null });
    return delay({
      env, market: "kr", broker: "kis",
      steps: [
        step("register", "앱키와 계좌번호 등록", !!cred,
          "데모 빌드에서는 실제 KIS 서버에 연결하지 않습니다. 입력값은 브라우저 안에만 남습니다."),
        step("verify", "연결 테스트 통과", !!cred?.last_verified_at,
          "데모 빌드에서는 항상 성공으로 처리됩니다."),
        step("risk", "리스크 한도 확인", !!cfg.risk_ack_at,
          "1회 주문금액·종목당 비중·일일 손실 한도·거래시간을 확인합니다."),
        step("run", "자동매매 가동", !!cfg.enabled,
          "가동해도 주문은 브라우저 안 시뮬레이터가 처리합니다."),
      ],
      matrix: ["kr", "us"].flatMap((market) =>
        ["paper", "live"].map((e) => {
          const c = state.creds.find((x) => x.env === e && (x.market ?? "kr") === market);
          return {
            market, env: e,
            registered: !!c,
            verified: !!c?.last_verified_at,
            agent_enabled: market === "kr" && !!state.cfg[e].enabled,
            locked: false,
          };
        }),
      ),
      account_linked: false,
      market_source: "simulator",
      live_trading_allowed: true,
      locked: false,
      lock_reason: null,
      ready: !!cred?.last_verified_at,
      open_orders: 0,
    });
  },

  panic: async () => {
    let disabled = 0;
    Object.values(state.cfg).forEach((c) => {
      if (c.enabled) { c.enabled = false; disabled += 1; }
    });
    return delay({
      disabled, canceled: 0, failed: 0,
      at: new Date().toISOString(),
      message: `자동매매 ${disabled}건을 껐습니다.`,
    }, 300);
  },

  signals: async (env, limit = 60) => delay(state.signals[env].slice(0, limit)),

  agentStep: async (env) => {
    const results = stepOnce(env);
    const now = new Date().toISOString();
    state.signals[env] = [
      ...results.map((r, i) => ({
        id: state.nextId++ + i, symbol: r.symbol, action: r.action,
        confidence: r.confidence, q_buy: r.q_values.buy, q_hold: r.q_values.hold,
        q_sell: r.q_values.sell, price: r.price, executed: false,
        reason: r.reason, created_at: now,
      })),
      ...state.signals[env],
    ].slice(0, 120);
    return delay({ results }, 420);
  },
};
