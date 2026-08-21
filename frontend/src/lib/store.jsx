import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setToken, setUnauthorizedHandler } from "./api";

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
      theme, setTheme, toast, toasts,
    }),
    [session, ready, login, signup, logout, env, setEnv, theme, toast, toasts],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

/** 데이터 로딩 헬퍼. env가 바뀌면 자동으로 다시 부른다. */
export function useAsync(fn, deps = [], { interval } = {}) {
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
  }, [...deps, nonce]);

  useEffect(() => {
    if (!interval) return;
    const id = setInterval(reload, interval);
    return () => clearInterval(id);
  }, [interval, reload]);

  return { ...state, reload };
}
