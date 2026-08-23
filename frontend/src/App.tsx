import { useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import { getToken, clearToken, api } from "./api";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import Approvals from "./pages/Approvals";
import Dialer from "./pages/Dialer";
import HiringIntent from "./pages/HiringIntent";

function Login({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const body =
        mode === "login"
          ? { email, password }
          : { email, password, display_name: email.split("@")[0] };
      const data = await api(path, { method: "POST", body: JSON.stringify(body) });
      localStorage.setItem("orbit_token", data.token);
      onLogin();
    } catch (err: any) {
      setError(err.message);
    }
  }

  return (
    <div className="gtm-page min-h-screen items-center">
      <form onSubmit={submit} className="gtm-card p-8 w-96 space-y-4" style={{ marginTop: "10vh" }}>
        <div className="gtm-header" style={{ padding: 0 }}>
          <div className="gtm-logo">◎</div>
          <h1 className="gtm-title">Orbit</h1>
        </div>
        <input
          className="gtm-input w-full"
          placeholder="email" type="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required
        />
        <input
          className="gtm-input w-full"
          placeholder="password (min 10 chars)" type="password" value={password} minLength={10}
          onChange={(e) => setPassword(e.target.value)} required
        />
        {error && <p className="gtm-error">{error}</p>}
        <button className="gtm-btn w-full">{
          mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="w-full text-xs gtm-muted"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
        >
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}

const NAV = [
  ["◎", "Agents", "/"],
  ["☰", "Leads", "/leads"],
  ["⚡", "Hiring Intent", "/hiring-intent"],
  ["☏", "Dialer", "/dialer"],
  ["✓", "Approvals", "/approvals"],
] as const;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex" style={{ background: "#eef0f4" }}>
      <nav
        className="shrink-0 flex flex-col items-center py-5 gap-1"
        style={{
          width: 64, background: "#ffffff",
          borderRight: "1px solid #eef1f5",
        }}
      >
        <div className="gtm-logo" style={{ marginBottom: 18 }}>◎</div>
        {NAV.map(([icon, label, to]) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              `flex items-center justify-center rounded-xl`
              + ` ${isActive ? "text-white" : "text-slate-500 hover:bg-slate-100"}`
            }
            style={({ isActive }) =>
              isActive
                ? { width: 42, height: 42, background: "#0f172a", fontSize: 18 }
                : { width: 42, height: 42, fontSize: 18 }
            }
          >
            {icon}
          </NavLink>
        ))}
        <button
          onClick={() => { clearToken(); location.href = "/login"; }}
          title="Sign out"
          className="text-slate-400 hover:text-red-500 mt-auto"
          style={{ width: 42, height: 42, fontSize: 16 }}
        >
          ⏻
        </button>
      </nav>
      <main className="flex-1 p-6" style={{ maxWidth: 1100 }}>{children}</main>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());

  return (
    <BrowserRouter>
      {!authed ? (
        <Routes>
          <Route path="/login" element={<Login onLogin={() => setAuthed(true)} />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      ) : (
        <Shell>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/dialer" element={<Dialer />} />
            <Route path="/hiring-intent" element={<HiringIntent />} />
          </Routes>
        </Shell>
      )}
    </BrowserRouter>
  );
}
