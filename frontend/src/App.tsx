import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  SquaresFour, Compass, GearSix, Star, Broadcast, ListDashes,
  Lightning, CheckSquare, Phone, EnvelopeSimple, Cloud, Warning,
  ClockCounterClockwise, PaperPlaneTilt, SlidersHorizontal, MagnifyingGlass,
} from "@phosphor-icons/react";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import Approvals from "./pages/Approvals";
import Dialer from "./pages/Dialer";
import HiringIntent from "./pages/HiringIntent";
import ControlCenter from "./pages/ControlCenter";
import AgentsDashboard from "./pages/AgentsDashboard";
import TodayBestLeads from "./pages/TodayBestLeads";
import SignalsDashboard from "./pages/SignalsDashboard";
import ProviderDashboard from "./pages/ProviderDashboard";
import MailboxManager from "./pages/MailboxManager";
import AlertsCenter from "./pages/AlertsCenter";
import AuditHistory from "./pages/AuditHistory";
import TelegramSettings from "./pages/TelegramSettings";
import Settings from "./pages/Settings";
import GtmExplorer from "./pages/GtmExplorer";
import { api } from "./api";

type NavItem = { icon: React.ReactNode; label: string; to: string };

const WORKSPACE: NavItem[] = [
  { icon: <SquaresFour size={17} weight="bold" />, label: "Control Center", to: "/control-center" },
  { icon: <Compass size={17} weight="bold" />, label: "GTM Explorer", to: "/explorer" },
  { icon: <ListDashes size={17} weight="bold" />, label: "Leads", to: "/leads" },
  { icon: <Star size={17} weight="bold" />, label: "Best Leads", to: "/best-leads" },
  { icon: <Broadcast size={17} weight="bold" />, label: "Signals", to: "/signals" },
  { icon: <Lightning size={17} weight="bold" />, label: "Hiring Intent", to: "/hiring-intent" },
  { icon: <CheckSquare size={17} weight="bold" />, label: "Approvals", to: "/approvals" },
  { icon: <Phone size={17} weight="bold" />, label: "Dialer", to: "/dialer" },
];

const SYSTEM: NavItem[] = [
  { icon: <GearSix size={17} weight="bold" />, label: "Agents", to: "/agents" },
  { icon: <EnvelopeSimple size={17} weight="bold" />, label: "Mailboxes", to: "/mailboxes" },
  { icon: <Cloud size={17} weight="bold" />, label: "Providers", to: "/providers" },
  { icon: <Warning size={17} weight="bold" />, label: "Alerts", to: "/alerts" },
  { icon: <ClockCounterClockwise size={17} weight="bold" />, label: "Audit", to: "/audit" },
  { icon: <PaperPlaneTilt size={17} weight="bold" />, label: "Telegram", to: "/telegram" },
  { icon: <SlidersHorizontal size={17} weight="bold" />, label: "Settings", to: "/settings" },
];

function useHealth() {
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    const poll = () =>
      api("/system-health").then((h) => { if (alive) setHealth(h); }).catch(() => {});
    poll();
    const t = setInterval(poll, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return health;
}

function NavGroup({ label, items }: { label: string; items: NavItem[] }) {
  return (
    <div className="mb-5">
      <div className="mono text-[10px] uppercase tracking-[0.1em] px-3 mb-1.5" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
      {items.map(({ icon, label: text, to }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            "flex items-center gap-2.5 rounded-lg px-3 py-[7px] text-[13.5px] font-medium transition-colors "
            + (isActive ? "" : "hover:bg-[#f4f4f2]")
          }
          style={({ isActive }) => ({
            background: isActive ? "var(--line-soft)" : undefined,
            color: isActive ? "var(--ink)" : "var(--ink-2)",
          })}
        >
          {icon}
          {text}
        </NavLink>
      ))}
    </div>
  );
}

function TopBar({ title }: { title: string }) {
  const health = useHealth();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const checks: Record<string, any> = health?.checks ?? {};
  const down = Object.entries(checks).some(
    ([k, v]) => k !== "agent_failures_24h" && (v === "down" || String(v).startsWith("http_"))
  );
  const warn = !down && Object.entries(checks).some(
    ([k, v]) => k !== "agent_failures_24h" && !(v === "ok" || v === "configured")
  );
  return (
    <header
      className="sticky top-0 z-10 flex items-center gap-4 px-6 h-14 bg-white/90 backdrop-blur border-b"
      style={{ borderColor: "var(--line)" }}
    >
      <h1 className="text-[15px] font-semibold shrink-0" style={{ color: "var(--ink)" }}>{title}</h1>
      <form
        className="flex-1 max-w-md mx-auto"
        onSubmit={(e) => { e.preventDefault(); if (q.trim()) { nav(`/leads?q=${encodeURIComponent(q.trim())}`); setQ(""); } }}
      >
        <div className="relative">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--ink-3)" }} />
          <input
            className="input w-full pl-8 pr-8 py-1.5 text-[13px] rounded-lg"
            placeholder="Search leads…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search leads"
          />
          <kbd className="mono absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] px-1.5 py-0.5 rounded border" style={{ color: "var(--ink-3)", borderColor: "var(--line)" }}>/</kbd>
        </div>
      </form>
      <span
        className="shrink-0 inline-flex items-center gap-1.5 border rounded-full px-3 py-1 text-[12px] font-medium"
        style={{ borderColor: "var(--line)", color: down ? "var(--bad-deep)" : warn ? "var(--warn-deep)" : "var(--good-deep)" }}
        title="system health"
      >
        <span className={`hdot mr-0 hdot-${down ? "down" : warn ? "warn" : "ok"}`} />
        {down ? "degraded" : warn ? "partial" : "live"}
      </span>
    </header>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const all = [...WORKSPACE, ...SYSTEM];
  const current = all.find((n) => loc.pathname.startsWith(n.to))
    ?? (loc.pathname.startsWith("/leads") ? all[2] : undefined);
  const title = current?.label ?? "Orbit";
  return (
    <div className="min-h-screen flex" style={{ background: "var(--canvas)" }}>
      <nav
        className="shrink-0 flex flex-col py-4 px-2.5 sticky top-0 h-screen bg-white border-r overflow-y-auto"
        style={{ width: 216, borderColor: "var(--line)" }}
      >
        <div className="flex items-center gap-2.5 px-3 mb-5">
          <div className="w-8 h-8 rounded-lg text-white flex items-center justify-center font-semibold" style={{ background: "var(--ink)" }}>
            ◎
          </div>
          <div>
            <div className="text-[14px] font-semibold leading-tight" style={{ color: "var(--ink)" }}>Orbit</div>
            <div className="mono text-[10px] leading-tight" style={{ color: "var(--ink-3)" }}>GTM OS</div>
          </div>
        </div>
        <NavGroup label="Workspace" items={WORKSPACE} />
        <NavGroup label="System" items={SYSTEM} />
        <div className="mt-auto card p-3 mx-1">
          <div className="flex items-center gap-1.5 text-[12px] font-medium" style={{ color: "var(--ink)" }}>
            <span className="hdot mr-0 hdot-ok" /> orchestrator
          </div>
          <div className="mono text-[10px] mt-0.5" style={{ color: "var(--ink-3)" }}>n8n · live</div>
        </div>
      </nav>
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar title={title} />
        <main className="flex-1 min-w-0 p-6">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/control-center" replace />} />
          <Route path="/control-center" element={<ControlCenter />} />
          <Route path="/explorer" element={<GtmExplorer />} />
          <Route path="/agents" element={<AgentsDashboard />} />
          <Route path="/best-leads" element={<TodayBestLeads />} />
          <Route path="/signals" element={<SignalsDashboard />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/leads/:id" element={<LeadDetail />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/dialer" element={<Dialer />} />
          <Route path="/hiring-intent" element={<HiringIntent />} />
          <Route path="/mailboxes" element={<MailboxManager />} />
          <Route path="/providers" element={<ProviderDashboard />} />
          <Route path="/alerts" element={<AlertsCenter />} />
          <Route path="/audit" element={<AuditHistory />} />
          <Route path="/telegram" element={<TelegramSettings />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/control-center" replace />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}
