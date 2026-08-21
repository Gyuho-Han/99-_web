import { demoApi } from "./demoApi";

const BASE = import.meta.env.VITE_API_BASE || "/api";

/** 데모 빌드: 백엔드 없이 브라우저 안에서만 동작한다. */
export const DEMO = import.meta.env.VITE_DEMO === "1";

let token = null;
let onUnauthorized = () => {};

export function setToken(t) {
  token = t;
}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function request(path, { method = "GET", body, params } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    });
  }

  const res = await fetch(url.pathname + url.search, {
    method,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    onUnauthorized();
    throw new Error("세션이 만료되었습니다. 다시 로그인하세요.");
  }
  if (res.status === 204) return null;

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join(", ")
          : "요청을 처리하지 못했습니다.",
    );
  }
  return data;
}

const httpApi = {
  // 인증
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  signup: (payload) => request("/auth/signup", { method: "POST", body: payload }),
  me: () => request("/auth/me"),

  // 자격증명
  credentials: () => request("/credentials"),
  saveCredential: (payload) => request("/credentials", { method: "PUT", body: payload }),
  verifyCredential: (id) => request(`/credentials/${id}/verify`, { method: "POST" }),
  deleteCredential: (id) => request(`/credentials/${id}`, { method: "DELETE" }),

  // 시세
  marketStatus: (env) => request("/market/status", { params: { env } }),
  universe: () => request("/market/universe"),
  quote: (symbol, env) => request(`/market/quote/${symbol}`, { params: { env } }),
  candles: (symbol, env, days = 120) =>
    request(`/market/candles/${symbol}`, { params: { env, days } }),

  // 계좌 · 주문
  account: (env) => request("/account", { params: { env } }),
  orders: (env, params = {}) => request("/orders", { params: { env, ...params } }),
  placeOrder: (env, payload) => request("/orders", { method: "POST", params: { env }, body: payload }),
  cancelOrder: (env, id) => request(`/orders/${id}`, { method: "DELETE", params: { env } }),

  // 성과 · 에이전트
  performance: (env, days = 180) => request("/performance", { params: { env, days } }),
  agentConfig: (env) => request("/agent/config", { params: { env } }),
  updateAgentConfig: (env, payload) =>
    request("/agent/config", { method: "PATCH", params: { env }, body: payload }),
  signals: (env, limit = 60) => request("/agent/signals", { params: { env, limit } }),
  agentStep: (env, dryRun = true) =>
    request("/agent/step", { method: "POST", params: { env, dry_run: dryRun } }),
};

export const api = DEMO ? demoApi : httpApi;
