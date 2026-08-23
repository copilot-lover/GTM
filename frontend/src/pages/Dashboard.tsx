import { useEffect, useState } from "react";
import { api } from "../api";

const STAGE_ICONS: Record<string, string> = {
  sourcing: "◎",
  qualifying: "◎",
  writing: "◎",
  waiting: "◎",
  meeting: "◎",
  draft: "◎",
  cadence: "◎",
  rejected: "○",
  default: "◎",
};

function stageMeta(a: any): { label: string; chip?: string; tone?: string } {
  const s: string = a.summary || "";
  if (s.startsWith("Sourcing")) return { label: "Sourcing leads" };
  if (s.startsWith("Qualifying")) return { label: "Scoring ICP fit" };
  if (s.startsWith("Writing")) return { label: "Writing the opener" };
  if (s.startsWith("Draft awaiting")) return { label: "One-preview approval", chip: "Needs you", tone: "amber" };
  if (s.startsWith("Waiting on reply")) return { label: "Waiting on reply · last send 6h ago" };
  if (s.startsWith("Meeting")) return { label: s, chip: "Booked", tone: "green" };
  if (s.startsWith("Cadence")) return { label: "Cadence running" };
  if (s.startsWith("Rejected")) return { label: s, chip: "Skipped", tone: "gray" };
  return { label: s };
}

export default function Dashboard() {
  const [feed, setFeed] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [kpis, setKpis] = useState<any>(null);
  const [error, setError] = useState("");
  const [seeding, setSeeding] = useState(false);

  async function poll() {
    try {
      const [f, h, d] = await Promise.all([
        api("/feed"),
        api("/system-health"),
        api("/dashboard"),
      ]);
      setFeed(f); setHealth(h); setKpis(d); setError("");
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => {
    poll();
    const t = setInterval(poll, 30000);
    return () => clearInterval(t);
  }, []);

  async function seedDemo() {
    setSeeding(true);
    try { await api("/feed/seed-demo", { method: "POST" }); await poll(); }
    catch (e: any) { setError(e.message); }
    setSeeding(false);
  }

  const degraded =
    health &&
    Object.entries(health.checks).some(
      ([k, v]) =>
        k !== "database" && k !== "agent_failures_24h" && v !== "ok" && v !== "configured"
    );

  const items = feed?.items ?? [];
  const isEmpty = feed && items.length === 0;

  return (
    <div className="gtm-page">
      {degraded && (
        <div className="gtm-banner">
          System degraded: {JSON.stringify(health?.checks)}
        </div>
      )}

      <div className="gtm-card">
        <div className="gtm-header">
          <div className="gtm-logo">◎</div>
          <h1 className="gtm-title">Agents</h1>
          <span className="gtm-pill">
            <span className="gtm-dot" /> {feed?.total_plays ?? 0}
          </span>
        </div>

        <div className="gtm-kpis">
          <span><b>{kpis?.kpis?.new_leads_today ?? 0}</b> new today</span>
          <span><b>{kpis?.kpis?.contacted_total ?? 0}</b> contacted</span>
          <span><b>{kpis?.kpis?.replies_total ?? 0}</b> replies</span>
          <span><b>{kpis?.kpis?.upcoming_meetings ?? 0}</b> meetings</span>
          <span><b>${Number(kpis?.ai_spend_today_usd ?? 0).toFixed(2)}</b> AI today</span>
        </div>

        {error && <p className="gtm-error">{error} — retrying on next poll</p>}

        {isEmpty && (
          <div className="gtm-empty">
            <p>No plays yet — your workspace is brand new.</p>
            <button className="gtm-cta" onClick={seedDemo} disabled={seeding}>
              {seeding ? "Loading…" : "Load demo batch"}
            </button>
          </div>
        )}

        <div className="gtm-feed">
          {items.map((a: any) => {
            const meta = stageMeta(a);
            return (
              <a key={a.lead_id + a.created_at} className="gtm-row"
                 href={`/leads/${a.lead_id}`}>
                <span className="gtm-row-icon">{STAGE_ICONS.default}</span>
                <span className="gtm-row-main">
                  <span className="gtm-row-title">{a.business_name}</span>
                  <span className="gtm-row-sub">{meta.label}</span>
                  <span className="gtm-row-contact">
                    {[a.business_name, [a.city, a.state].filter(Boolean).join(", ")]
                      .filter(Boolean).join(" · ")}
                  </span>
                  {meta.chip && (
                    <span className={`gtm-chip gtm-chip-${meta.tone}`}>
                      {meta.chip}
                    </span>
                  )}
                </span>
                <span className="gtm-row-cost">
                  {a.priority_score != null ? `${a.priority_score}` : "—"}
                </span>
              </a>
            );
          })}
        </div>

        <div className="gtm-footer">One preview. Then the loop runs.</div>
      </div>
    </div>
  );
}
