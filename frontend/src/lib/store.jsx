import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setMarket as setApiMarket, setToken, setUnauthorizedHandler } from "./api";
import { setCurrency } from "./format";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

// 브라우저 저장소가 없는 환경에서도 동작하도록 메모리로 대체한다.
const memory = new Map();
const store = {
  get(k) {
    try {
      return window.sessionStorage.getItem(k);
    } catch {
      return memory.get(k) ?? null;
    }
  },
  set(k, v) {
    try {
      window.sessionStorage.setItem(k, v);
    } catch {
      memory.set(k, v);
    }
  },
  del(k) {
    try {
      window.sessionStorage.removeItem(k);
    } catch {
      memory.delete(k);
    }
  },
};

export function AppProvider({ children }) {
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(false);
  const [env, setEnvState] = useState(() => store.get("kairo.env") || "paper");
  const [market, setMarketState] = useState(() => {
    // 새로고침으로 되살아난 시장은 첫 렌더 '전에' 반영해야 한다. 아래 useEffect 로만
    // 맞추면 첫 렌더는 기본값(KRW)으로 그려지고, 그 뒤 setCurrency 는 모듈 변수만
    // 바꾸므로 다시 그려지지 않는다. 미국 시장인데 금액이 원으로 남아 있던 원인이다.
    const m = store.get("kairo.market") === "us" ? "us" : "kr";
    setApiMarket(m);
    setCurrency(m === "us" ? "USD" : "KRW");
    return m;
  });
  const [theme, setTheme] = useState(() => store.get("kairo.theme") || "dark");
  const [toasts, setToasts] = useState([]);

  const toast = useCallback((message, tone = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    store.del("kairo.token");
    setSession(null);
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await api.login(email, password);
    setToken(data.access_token);
    store.set("kairo.token", data.access_token);
    setSession(data.user);
    return data.user;
  }, []);

  const signup = useCallback(async (payload) => {
    const data = await api.signup(payload);
    setToken(data.access_token);
    store.set("kairo.token", data.access_token);
    setSession(data.user);
    return data.user;
  }, []);

  const setEnv = useCallback((next) => {
    setEnvState(next);
    store.set("kairo.env", next);
  }, []);

  const setMarket = useCallback((next) => {
    const m = next === "us" ? "us" : "kr";
    setMarketState(m);
    store.set("kairo.market", m);
    setApiMarket(m);                                 // 이후 모든 요청에 실린다
    setCurrency(m === "us" ? "USD" : "KRW");         // 금액 표기도 함께 바꾼다
  }, []);

  // 새로고침으로 되살아난 시장 값을 api/포맷터에도 즉시 반영한다.
  useEffect(() => {
    setApiMarket(market);
    setCurrency(market === "us" ? "USD" : "KRW");
  }, [market]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    document.documentElement.classList.toggle("dark", theme === "dark");
    store.set("kairo.theme", theme);
  }, [theme]);

  useEffect(() => {
    const saved = store.get("kairo.token");
    if (!saved) {
      setReady(true);
      return;
    }
    setToken(saved);
    api
      .me()
      .then(setSession)
      .catch(() => store.del("kairo.token"))
      .finally(() => setReady(true));
  }, []);

  const value = useMemo(
    () => ({
      session, ready, login, signup, logout,
      env, setEnv, isLive: env === "live",
      market, setMarket, isUS: market === "us",
      currency: market === "us" ? "USD" : "KRW",
      theme, setTheme, toast, toasts,
    }),
    [session, ready, login, signup, logout, env, setEnv, market, setMarket, theme, toast, toasts],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

/** 데이터 로딩 헬퍼. env나 시장(kr/us)이 바뀌면 자동으로 다시 부른다.
 *
 *  시장은 요청 파라미터에 api.js가 알아서 실어 주므로 각 화면은 넘길 필요가 없다.
 *  다만 재조회는 해야 하므로 여기서 의존성에 끼워 넣는다. 덕분에 화면 코드는
 *  한 줄도 바뀌지 않는다.
 */
export function useAsync(fn, deps = [], { interval } = {}) {
  const ctx = useContext(AppContext);
  const market = ctx?.market ?? "kr";
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fn()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((e) => alive && setState({ data: null, error: e.message, loading: false }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, market, nonce]);

  useEffect(() => {
    if (!interval) return;
    const id = setInterval(reload, interval);
    return () => clearInterval(id);
  }, [interval, reload]);

  return { ...state, reload };
}
