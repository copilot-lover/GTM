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
    <div className="min-h-screen flex items-center justify-center bg-slate-100 px-4">
      <form
        onSubmit={submit}
        className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 w-full max-w-sm space-y-4"
      >
        <div className="flex items-center gap-3 mb-6">
          <div className="w-9 h-9 rounded-xl bg-slate-900 text-white flex items-center justify-center text-lg">
            ◎
          </div>
          <div>
            <div className="font-semibold text-slate-900">Orbit GTM OS</div>
            <div className="text-xs text-slate-500">One motion. Start to booked.</div>
          </div>
        </div>
        <input
          className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400"
          placeholder="email" type="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required
        />
        <input
          className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400"
          placeholder="password (min 10 chars)" type="password" value={password} minLength={10}
          onChange={(e) => setPassword(e.target.value)} required
        />
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <button className="w-full bg-slate-900 hover:bg-slate-700 transition-colors text-white font-medium rounded-lg px-3 py-2.5 text-sm">
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="w-full text-xs text-slate-500 hover:text-slate-800 transition-colors"
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
    <div className="min-h-screen flex bg-slate-100">
      <nav
        className="shrink-0 flex flex-col items-center py-5 gap-1 sticky top-0 h-screen bg-white border-r border-slate-200"
        style={{ width: 64 }}
      >
        <div className="w-9 h-9 rounded-xl bg-slate-900 text-white flex items-center justify-center text-lg mb-4">
          ◎
        </div>
        {NAV.map(([icon, label, to]) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              `flex items-center justify-center rounded-xl transition-colors `
              + (isActive
                ? "bg-slate-900 text-white"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-900")
            }
            style={{ width: 42, height: 42, fontSize: 17 }}
          >
            {icon}
          </NavLink>
        ))}
        <button
          onClick={() => { clearToken(); location.href = "/login"; }}
          title="Sign out"
          className="text-slate-400 hover:text-red-500 transition-colors mt-auto flex items-center justify-center"
          style={{ width: 42, height: 42, fontSize: 16 }}
        >
          ⏻
        </button>
      </nav>
      <main className="flex-1 min-w-0 p-6">{children}</main>
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
