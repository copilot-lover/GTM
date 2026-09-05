import { useEffect, useState } from "react";
import { api } from "../api";
import { CheckCircle, Warning } from "@phosphor-icons/react";

interface ProviderRow {
  provider: string;
  operation: string | null;
  quota: number;
  used: number;
  remaining: number | null;
  reset_date: string | null;
  success_rate: number | null;
}

interface SettingsData {
  providers: {
    llm_api_key: string;
    llm_model_chain: string;
    ai_daily_budget_usd: number;
  };
  smtp: {
    smtp_host: string;
    smtp_port: number;
    smtp_user: string;
    smtp_from_email: string;
    smtp_from_name: string;
    orbit_physical_address: string;
    smtp_password: string;
  };
  scraper: {
    scraper_headless: boolean;
    scraper_stealth_mode: boolean;
  };
}

function ConfiguredBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="badge badge-qualified"><CheckCircle size={12} weight="bold" className="mr-1" /> configured</span>
  ) : (
    <span className="badge badge-enriching"><Warning size={12} weight="bold" className="mr-1" /> not configured</span>
  );
}

function ProgressBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const bg = pct > 80 ? "var(--bad)" : pct > 50 ? "var(--warn-deep)" : "var(--good-deep)";
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--line-soft)" }}>
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: bg }} />
      </div>
      <span className="mono text-xs" style={{ color: "var(--ink-3)" }}>{pct}%</span>
    </div>
  );
}

export default function ProviderDashboard() {
  const [rows, setRows] = useState<ProviderRow[]>([]);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  // provider config forms
  const [apiKey, setApiKey] = useState("");
  const [modelChain, setModelChain] = useState("");
  const [budget, setBudget] = useState("");
  const [smtpForm, setSmtpForm] = useState({
    smtp_host: "", smtp_port: "", smtp_user: "", smtp_password: "",
    smtp_from_email: "", smtp_from_name: "", orbit_physical_address: "",
  });
  const [scraperForm, setScraperForm] = useState({ scraper_headless: true, scraper_stealth_mode: true });

  async function load() {
    try {
      const [p, s] = await Promise.all([
        api<{ providers: ProviderRow[] }>("/control-plane/providers"),
        api<SettingsData>("/settings"),
      ]);
      setRows(Array.isArray(p.providers) ? p.providers : []);
      setSettings(s);
      setModelChain(s.providers.llm_model_chain);
      setBudget(String(s.providers.ai_daily_budget_usd));
      setSmtpForm({
        smtp_host: s.smtp.smtp_host,
        smtp_port: String(s.smtp.smtp_port),
        smtp_user: s.smtp.smtp_user,
        smtp_password: "",
        smtp_from_email: s.smtp.smtp_from_email,
        smtp_from_name: s.smtp.smtp_from_name,
        orbit_physical_address: s.smtp.orbit_physical_address,
      });
      setScraperForm({
        scraper_headless: s.scraper.scraper_headless,
        scraper_stealth_mode: s.scraper.scraper_stealth_mode,
      });
      setError("");
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { load(); }, []);

  async function saveProviders() {
    setSaving("providers");
    try {
      const body: Record<string, unknown> = {};
      if (apiKey) body.llm_api_key = apiKey;
      if (modelChain) body.llm_model_chain = modelChain;
      if (budget !== "") body.ai_daily_budget_usd = Number(budget);
      if (Object.keys(body).length === 0) { setMsg("Nothing to update"); setSaving(null); return; }
      await api("/settings/providers", { method: "PUT", body: JSON.stringify(body) });
      setMsg("LLM provider settings saved");
      setApiKey("");
      await load();
    } catch (e: any) { setError(e.message); }
    setSaving(null);
  }

  async function saveSmtp() {
    setSaving("smtp");
    try {
      const body: Record<string, unknown> = {};
      if (smtpForm.smtp_host) body.smtp_host = smtpForm.smtp_host;
      if (smtpForm.smtp_port) body.smtp_port = Number(smtpForm.smtp_port);
      if (smtpForm.smtp_user) body.smtp_user = smtpForm.smtp_user;
      if (smtpForm.smtp_password) body.smtp_password = smtpForm.smtp_password;
      if (smtpForm.smtp_from_email) body.smtp_from_email = smtpForm.smtp_from_email;
      if (smtpForm.smtp_from_name) body.smtp_from_name = smtpForm.smtp_from_name;
      if (smtpForm.orbit_physical_address) body.orbit_physical_address = smtpForm.orbit_physical_address;
      if (Object.keys(body).length === 0) { setMsg("Nothing to update"); setSaving(null); return; }
      await api("/settings/smtp", { method: "PUT", body: JSON.stringify(body) });
      setMsg("SMTP settings saved");
      setSmtpForm((f) => ({ ...f, smtp_password: "" }));
      await load();
    } catch (e: any) { setError(e.message); }
    setSaving(null);
  }

  async function saveScraper() {
    setSaving("scraper");
    try {
      await api("/settings/scraper", {
        method: "PUT",
        body: JSON.stringify({
          scraper_headless: scraperForm.scraper_headless,
          scraper_stealth_mode: scraperForm.scraper_stealth_mode,
        }),
      });
      setMsg("Scraper settings saved");
      await load();
    } catch (e: any) { setError(e.message); }
    setSaving(null);
  }

  const clearFeedback = () => { setError(""); setMsg(""); };

  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>Providers</h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
          API usage, quotas, and every external credential in one place.
        </p>
      </div>

      {error && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--bad-deep)", borderColor: "#f2cfcf", background: "var(--bad-soft)" }}>{error}</div>}
      {msg && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--good-deep)", borderColor: "#d2e9de", background: "var(--good-soft)" }}>{msg}</div>}

      {/* Usage table */}
      <table className="tbl">
        <thead>
          <tr>
            <th>Provider</th><th>Operation</th><th>Used / Quota</th>
            <th>Remaining</th><th>Reset</th><th>Success</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={`${p.provider}-${p.operation}-${i}`}>
              <td className="font-medium" style={{ color: "var(--ink)" }}>{p.provider}</td>
              <td className="mono text-xs">{p.operation ?? "—"}</td>
              <td className="mono">{p.used} / {p.quota}</td>
              <td><ProgressBar used={p.used} total={p.quota} /></td>
              <td className="mono text-xs">{p.reset_date ?? "—"}</td>
              <td className="mono">
                {p.success_rate != null ? `${Math.round(p.success_rate * 100)}%` : "—"}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="text-center py-8" style={{ color: "var(--ink-3)" }}>
              no provider usage recorded yet
            </td></tr>
          )}
        </tbody>
      </table>

      {/* ── LLM config ──────────────────────────────────────────── */}
      {settings && (
        <div className="panel space-y-4">
          <div className="flex items-center justify-between">
            <div className="panel-title mb-0">LLM</div>
            <ConfiguredBadge ok={settings.providers.llm_api_key === "***set***"} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="sm:col-span-2">
              <label className="panel-title mb-1">API key</label>
              <input
                className="input w-full" type="password" placeholder="sk-or-..."
                value={apiKey}
                onChange={(e) => { clearFeedback(); setApiKey(e.target.value); }}
              />
              <p className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>Leave blank to keep current key</p>
            </div>
            <div className="sm:col-span-2">
              <label className="panel-title mb-1">Model chain</label>
              <input
                className="input w-full" placeholder="nvidia/nemotron-3-super-120b-a12b:free,..."
                value={modelChain}
                onChange={(e) => { clearFeedback(); setModelChain(e.target.value); }}
              />
              <p className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>
                Fallback order, first to last, comma-separated
              </p>
            </div>
            <div>
              <label className="panel-title mb-1">Daily budget (USD)</label>
              <input
                className="input w-full" type="number" step="0.5" min="0"
                value={budget}
                onChange={(e) => { clearFeedback(); setBudget(e.target.value); }}
              />
            </div>
          </div>
          <button className="btn" onClick={saveProviders} disabled={saving === "providers"}>
            {saving === "providers" ? "Saving…" : "Save LLM settings"}
          </button>
        </div>
      )}

      {/* ── SMTP ────────────────────────────────────────────────── */}
      {settings && (
        <div className="panel space-y-4">
          <div className="flex items-center justify-between">
            <div className="panel-title mb-0">SMTP (email sending)</div>
            <ConfiguredBadge ok={!!settings.smtp.smtp_host} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="panel-title mb-1">Host</label>
              <input className="input w-full" placeholder="smtp.gmail.com"
                value={smtpForm.smtp_host}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_host: e.target.value })); }} />
            </div>
            <div>
              <label className="panel-title mb-1">Port</label>
              <input className="input w-full" type="number" placeholder="587"
                value={smtpForm.smtp_port}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_port: e.target.value })); }} />
            </div>
            <div>
              <label className="panel-title mb-1">Username</label>
              <input className="input w-full" placeholder="user@example.com"
                value={smtpForm.smtp_user}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_user: e.target.value })); }} />
            </div>
            <div>
              <label className="panel-title mb-1">Password</label>
              <input className="input w-full" type="password" placeholder="••••••••"
                value={smtpForm.smtp_password}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_password: e.target.value })); }} />
              <p className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>Leave blank to keep current password</p>
            </div>
            <div>
              <label className="panel-title mb-1">From email</label>
              <input className="input w-full" placeholder="noreply@yourdomain.com"
                value={smtpForm.smtp_from_email}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_from_email: e.target.value })); }} />
            </div>
            <div>
              <label className="panel-title mb-1">From name</label>
              <input className="input w-full" placeholder="Orbit"
                value={smtpForm.smtp_from_name}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, smtp_from_name: e.target.value })); }} />
            </div>
            <div className="sm:col-span-2">
              <label className="panel-title mb-1">Physical address (CAN-SPAM)</label>
              <input className="input w-full" placeholder="123 Main St, City, State ZIP"
                value={smtpForm.orbit_physical_address}
                onChange={(e) => { clearFeedback(); setSmtpForm((f) => ({ ...f, orbit_physical_address: e.target.value })); }} />
            </div>
          </div>
          <button className="btn" onClick={saveSmtp} disabled={saving === "smtp"}>
            {saving === "smtp" ? "Saving…" : "Save SMTP"}
          </button>
        </div>
      )}

      {/* ── Scraper ─────────────────────────────────────────────── */}
      {settings && (
        <div className="panel space-y-3">
          <div className="panel-title mb-0">Scraper</div>
          {([["Headless", "scraper_headless"], ["Stealth mode", "scraper_stealth_mode"]] as const).map(([label, key]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-sm flex-1" style={{ color: "var(--ink-2)" }}>{label}</span>
              <button
                aria-label={`Toggle ${label}`}
                className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${scraperForm[key] ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
                onClick={() => { clearFeedback(); setScraperForm((f) => ({ ...f, [key]: !f[key] })); }}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${scraperForm[key] ? "left-5" : "left-0.5"}`} />
              </button>
            </div>
          ))}
          <button className="btn mt-2" onClick={saveScraper} disabled={saving === "scraper"}>
            {saving === "scraper" ? "Saving…" : "Save scraper"}
          </button>
        </div>
      )}
    </div>
  );
}