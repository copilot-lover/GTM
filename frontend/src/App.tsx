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
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={submit} className="bg-[#14161b] border border-zinc-800 rounded-lg p-8 w-96 space-y-4">
        <h1 className="text-xl font-semibold text-[#22c55e]">Orbit GTM OS</h1>
        <input
          className="w-full bg-black/40 border border-zinc-700 rounded px-3 py-2 text-sm"
          placeholder="email" type="email" value={email}
          onChange={(e) => setEmail(e.target.value)} required
        />
        <input
          className="w-full bg-black/40 border border-zinc-700 rounded px-3 py-2 text-sm"
          placeholder="password" type="password" value={password} minLength={10}
          onChange={(e) => setPassword(e.target.value)} required
        />
        {error && <p className="text-red-400 text-xs">{error}</p>}
        <button className="w-full bg-[#22c55e] text-black font-medium rounded px-3 py-2 text-sm hover:brightness-110">
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="w-full text-xs text-zinc-500 hover:text-zinc-300"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
        >
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}

const NAV = [
  ["Dashboard", "/"],
  ["Leads", "/leads"],
  ["Hiring Intent", "/hiring-intent"],
  ["Dialer", "/dialer"],
  ["Approvals", "/approvals"],
] as const;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex">
      <nav className="w-48 shrink-0 border-r border-zinc-800 p-4 space-y-1">
        <div className="mono text-[#22c55e] font-bold mb-6">ORBIT</div>
        {NAV.map(([label, to]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `block rounded px-3 py-2 text-sm ${isActive ? "bg-[#22c55e]/10 text-[#22c55e]" : "text-zinc-400 hover:bg-zinc-800/60"}`
            }
          >
            {label}
          </NavLink>
        ))}
        <button
          onClick={() => { clearToken(); location.href = "/login"; }}
          className="block px-3 py-2 mt-8 text-xs text-zinc-600 hover:text-red-400"
        >
          Sign out
        </button>
      </nav>
      <main className="flex-1 p-6 max-w-7xl">{children}</main>
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
