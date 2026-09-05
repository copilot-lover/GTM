import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import {
  SquaresFour, Compass, GearSix, Star, Broadcast, ListDashes,
  Lightning, CheckSquare, Phone, EnvelopeSimple, Cloud, Warning,
  ClockCounterClockwise, PaperPlaneTilt, SlidersHorizontal,
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

const NAV = [
  [<SquaresFour size={18} weight="bold" />, "Control Center", "/control-center"],
  [<Compass size={18} weight="bold" />, "GTM Explorer", "/explorer"],
  [<GearSix size={18} weight="bold" />, "Agents", "/agents"],
  [<Star size={18} weight="bold" />, "Best Leads", "/best-leads"],
  [<Broadcast size={18} weight="bold" />, "Signals", "/signals"],
  [<ListDashes size={18} weight="bold" />, "Leads", "/leads"],
  [<Lightning size={18} weight="bold" />, "Hiring Intent", "/hiring-intent"],
  [<CheckSquare size={18} weight="bold" />, "Approvals", "/approvals"],
  [<Phone size={18} weight="bold" />, "Dialer", "/dialer"],
  [<EnvelopeSimple size={18} weight="bold" />, "Mailboxes", "/mailboxes"],
  [<Cloud size={18} weight="bold" />, "Providers", "/providers"],
  [<Warning size={18} weight="bold" />, "Alerts", "/alerts"],
  [<ClockCounterClockwise size={18} weight="bold" />, "Audit", "/audit"],
  [<PaperPlaneTilt size={18} weight="bold" />, "Telegram", "/telegram"],
  [<SlidersHorizontal size={18} weight="bold" />, "Settings", "/settings"],
] as const;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex" style={{ background: "var(--canvas)" }}>
      <nav
        className="shrink-0 flex flex-col items-center py-4 gap-0.5 sticky top-0 h-screen bg-white border-r"
        style={{ width: 60, borderColor: "var(--line)" }}
      >
        <div
          className="w-9 h-9 rounded-lg text-white flex items-center justify-center font-semibold mb-4"
          style={{ background: "var(--ink)" }}
        >
          ◎
        </div>
        {NAV.map(([icon, label, to]) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              "flex items-center justify-center rounded-lg transition-colors "
              + (isActive
                ? "text-white"
                : "text-slate-400 hover:bg-slate-100 hover:text-slate-900")
            }
            style={({ isActive }) => ({
              width: 40, height: 40,
              background: isActive ? "var(--ink)" : undefined,
            })}
          >
            {icon}
          </NavLink>
        ))}
      </nav>
      <main className="flex-1 min-w-0 p-6">{children}</main>
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