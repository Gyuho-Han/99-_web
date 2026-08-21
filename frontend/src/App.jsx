import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider, useApp } from "./lib/store";
import { Spinner, Toasts } from "./components/ui";
import Shell from "./components/Shell";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Agent from "./pages/Agent";
import Trade from "./pages/Trade";
import Orders from "./pages/Orders";
import Performance from "./pages/Performance";
import Keys from "./pages/Keys";

function Gate() {
  const { session, ready } = useApp();

  if (!ready) {
    return (
      <div className="min-h-screen grid place-items-center">
        <Spinner label="세션 확인 중" />
      </div>
    );
  }
  if (!session) return <Login />;

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/agent" element={<Agent />} />
        <Route path="/trade" element={<Trade />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/performance" element={<Performance />} />
        <Route path="/keys" element={<Keys />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Gate />
        <Toasts />
      </BrowserRouter>
    </AppProvider>
  );
}
