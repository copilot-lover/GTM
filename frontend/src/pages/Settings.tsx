import { useEffect, useState } from "react";
import { api } from "../api";
import { CheckCircle, Warning } from "@phosphor-icons/react";

interface SettingsData {
  providers: { llm_api_key: string; llm_model_chain: string };
  smtp: { smtp_host: string; smtp_password: string };
  scraper: { scraper_headless: boolean; scraper_stealth_mode: boolean };
}

function ConfiguredBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="badge badge-qualified"><CheckCircle size={12} weight="bold" className="mr-1" /> configured</span>
  ) : (
    <span className="badge badge-enriching"><Warning size={12} weight="bold" className="mr-1" /> not configured</span>
  );
}

function Row({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b text-sm last:border-b-0" style={{ borderColor: "#f2f2f0" }}>
      <span style={{ color: "var(--ink-3)" }}>{label}</span>
      <span className={mono ? "mono" : ""} style={{ color: "var(--ink)" }}>{value}</span>
    </div>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api<SettingsData>("/settings")
      .then((d) => { setSettings(d); setLoaded(true); })
      .catch((e: any) => { setError(e.message); setLoaded(true); });
  }, []);

  if (!loaded) return <div className="w-full max-w-3xl mx-auto text-sm" style={{ color: "var(--ink-3)" }}>loading…</div>;

  return (
    <div className="w-full max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>Settings</h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
          Read-only view. Edit credentials on the <a href="/providers" style={{ color: "var(--accent)" }}>Providers</a> page,
          notifications on <a href="/telegram" style={{ color: "var(--accent)" }}>Telegram</a>.
        </p>
      </div>

      {error && <div className="card px-4 py-2.5 text-sm" style={{ color: "#9f2f2d", borderColor: "#f5d5d4", background: "#fdf6f6" }}>{error}</div>}

      {settings && (
        <>
          <div className="panel">
            <div className="flex items-center justify-between mb-2">
              <div className="panel-title mb-0">LLM</div>
              <ConfiguredBadge ok={settings.providers.llm_api_key === "***set***"} />
            </div>
            <Row label="Model chain" value={settings.providers.llm_model_chain} mono />
          </div>

          <div className="panel">
            <div className="flex items-center justify-between mb-2">
              <div className="panel-title mb-0">Email</div>
              <ConfiguredBadge ok={!!settings.smtp.smtp_host} />
            </div>
            <Row label="SMTP host" value={settings.smtp.smtp_host || "—"} mono />
          </div>

          <div className="panel">
            <div className="panel-title">Scraper</div>
            <Row label="Headless" value={settings.scraper.scraper_headless ? "on" : "off"} />
            <Row label="Stealth mode" value={settings.scraper.scraper_stealth_mode ? "on" : "off"} />
          </div>
        </>
      )}
    </div>
  );
}