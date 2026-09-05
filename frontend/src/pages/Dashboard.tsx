import { useEffect, useState } from "react";
import { api } from "../api";
import { Phone, CheckSquare, Lightning, ListDashes, PlayCircle } from "@phosphor-icons/react";

const HEALTH_META: Record<string, { label: string }> = {
  database: { label: "Postgres" },
  n8n: { label: "n8n orchestration" },
  twilio: { label: "Twilio telephony" },
  llm_openai: { label: "OpenAI" },
  llm_anthropic: { label: "Anthropic" },
  smtp: { label: "SMTP email" },
};

function healthState(k: string, v: any): "ok" | "warn" | "down" {
  if (k === "agent_failures_24h") return "ok";
  if (v === "ok" || v === "configured") return "ok";
  if (v === "down" || String(v).startsWith("http_")) return "down";
  return "warn"; // missing / not_configured
}

function HealthBar({ health }: { health: any }) {
  if (!health) return null;
  const entries = Object.entries(health.checks).filter(
    ([k]) => k !== "agent_failures_24h"
  );
  const down = entries.some(([, v]) => healthState("", v) === "down");
  return (
    <div
      className="card px-4 py-2.5 flex items-center gap-4 flex-wrap text-[13px]"
      style={down ? { borderColor: "#f2cfcf", background: "var(--bad-soft)" } : undefined}
    >
      <span className="panel-title mb-0 mr-1">System</span>
      {entries.map(([k, v]) => {
        const st = healthState(k, v);
        return (
          <span key={k} className="inline-flex items-center" style={{ color: "var(--ink-2)" }} title={String(v)}>
            <span className={`hdot hdot-${st}`} />
            {HEALTH_META[k]?.label ?? k}
            {st === "warn" && (
              <span className="ml-1.5 text-[10px] font-medium uppercase rounded px-1.5 py-0.5"
                style={{ background: "var(--warn-soft)", color: "var(--warn-deep)" }}>
                not configured
              </span>
            )}
            {st === "down" && (
              <span className="ml-1.5 text-[10px] font-medium uppercase rounded px-1.5 py-0.5"
                style={{ background: "var(--bad-soft)", color: "var(--bad-deep)" }}>
                down
              </span>
            )}
          </span>
        );
      })}
      {typeof health.checks.agent_failures_24h === "number" &&
        health.checks.agent_failures_24h > 0 && (
          <span className="inline-flex items-center" style={{ color: "var(--ink-2)" }}>
            <span className="hdot hdot-warn" />
            {health.checks.agent_failures_24h} agent failures (24h)
          </span>
        )}
    </div>
  );
}

function Kpi({ label, value, i = 0 }: { label: string; value: any; i?: number }) {
  return (
    <div className="card px-5 py-4 reveal" style={{ "--i": i } as React.CSSProperties}>
      <div className="mono text-[28px] font-semibold leading-none" style={{ color: "var(--ink)" }}>
        {String(value)}
      </div>
      <div className="text-xs mt-1.5" style={{ color: "var(--ink-3)" }}>{label}</div>
    </div>
  );
}

function stageLabel(s: string): { label: string; chip?: string } {
  if (s.startsWith("Sourcing")) return { label: "Sourcing leads" };
  if (s.startsWith("Qualifying")) return { label: "Scoring ICP fit" };
  if (s.startsWith("Writing")) return { label: "Writing the opener" };
  if (s.startsWith("Draft awaiting")) return { label: "One-preview approval", chip: "Needs you" };
  if (s.startsWith("Waiting on reply")) return { label: "Waiting on reply, last send 6h ago" };
  if (s.startsWith("Meeting")) return { label: s, chip: "Booked" };
  if (s.startsWith("Cadence")) return { label: "Cadence running" };
  if (s.startsWith("Rejected")) return { label: s, chip: "Skipped" };
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

  const items = feed?.items ?? [];
  const isEmpty = feed && items.length === 0;

  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <HealthBar health={health} />

      {/* KPI stat tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        <Kpi label="New leads today" value={kpis?.kpis?.new_leads_today ?? 0} i={0} />
        <Kpi label="Contacted" value={kpis?.kpis?.contacted_total ?? 0} i={1} />
        <Kpi label="Replies" value={kpis?.kpis?.replies_total ?? 0} i={2} />
        <Kpi label="Upcoming meetings" value={kpis?.kpis?.upcoming_meetings ?? 0} i={3} />
        <Kpi label="AI spend today" value={`$${Number(kpis?.ai_spend_today_usd ?? 0).toFixed(2)}`} i={4} />
      </div>

      {error && (
        <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--bad-deep)", borderColor: "#f2cfcf", background: "var(--bad-soft)" }}>
          {error} — retrying on next poll
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 items-start">
        {/* Agent feed — 2/3 width */}
        <section className="xl:col-span-2 card overflow-hidden">
          <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b" style={{ borderColor: "var(--line)" }}>
            <div className="w-8 h-8 rounded-lg text-white flex items-center justify-center text-sm" style={{ background: "var(--ink)" }}>
              ◎
            </div>
            <h2 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>Agents</h2>
            <span className="ml-auto inline-flex items-center gap-2 border rounded-full px-3 py-1 text-[13px]"
              style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}>
              <span className="hdot hdot-ok mr-0" />
              {feed?.total_plays ?? 0} active plays
            </span>
          </div>

          {isEmpty && (
            <div className="px-6 py-12 text-center" style={{ color: "var(--ink-3)" }}>
              <PlayCircle size={32} className="mx-auto mb-3" />
              <p className="text-sm">No plays yet — your workspace is brand new.</p>
              <button className="btn mt-4" onClick={seedDemo} disabled={seeding}>
                {seeding ? "Loading…" : "Load demo batch"}
              </button>
            </div>
          )}

          <div className="divide-y" style={{ borderColor: "var(--line-soft)" }}>
            {items.map((a: any) => {
              const meta = stageLabel(a.summary || "");
              return (
                <a key={a.lead_id + a.created_at}
                   href={`/leads/${a.lead_id}`}
                   className="flex items-start gap-3.5 px-5 py-4 transition-colors hover:bg-[#fbfbfa]"
                   style={{ borderColor: "var(--line-soft)" } as React.CSSProperties}>
                  <span className="mt-0.5 w-7 h-7 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: "var(--line-soft)", color: "var(--ink-2)" }}>
                    <PlayCircle size={14} weight="bold" />
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[15px] font-semibold truncate" style={{ color: "var(--ink)" }}>
                      {a.business_name}
                    </span>
                    <span className="block text-sm truncate" style={{ color: "var(--ink-3)" }}>{meta.label}</span>
                    <span className="block text-sm truncate" style={{ color: "var(--ink-2)" }}>
                      {[a.business_name, [a.city, a.state].filter(Boolean).join(", ")]
                        .filter(Boolean).join(", ")}
                    </span>
                    {meta.chip && (
                      <span className={`badge mt-1.5 ${
                        meta.chip === "Needs you" ? "badge-pending_approval"
                        : meta.chip === "Booked" ? "badge-meeting_booked"
                        : "badge-rejected"}`}>
                        {meta.chip}
                      </span>
                    )}
                  </span>
                  <span className="mono text-xs tnum mt-1" style={{ color: "var(--ink-3)" }}>
                    {a.priority_score != null ? a.priority_score : "-"}
                  </span>
                </a>
              );
            })}
          </div>
          <div className="px-5 py-3.5 text-center text-sm border-t" style={{ color: "var(--ink-3)", borderColor: "var(--line)" }}>
            One preview. Then the loop runs.
          </div>
        </section>

        {/* Quick actions + pipeline — right rail */}
        <section className="space-y-5">
          <div className="panel">
            <div className="panel-title">Quick actions</div>
            <div className="flex flex-col gap-2">
              <a href="/dialer" className="btn btn-green justify-center">
                <Phone size={14} weight="bold" /> Start call session
              </a>
              <a href="/approvals" className="btn justify-center">
                <CheckSquare size={14} weight="bold" /> Review approvals
                {kpis?.pending_approvals > 0 && (
                  <span className="ml-1 rounded-full px-1.5 text-xs font-semibold tnum"
                    style={{ background: "var(--warn-soft)", color: "var(--warn-deep)" }}>
                    {kpis.pending_approvals}
                  </span>
                )}
              </a>
              <a href="/hiring-intent" className="btn btn-ghost justify-center">
                <Lightning size={14} weight="bold" /> Hiring-intent queue
              </a>
              <a href="/leads" className="btn btn-ghost justify-center">
                <ListDashes size={14} weight="bold" /> Browse all leads
              </a>
              {isEmpty && (
                <button className="btn btn-ghost justify-center" onClick={seedDemo} disabled={seeding}>
                  {seeding ? "Loading…" : "Load demo batch"}
                </button>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">Pipeline</div>
            <div className="space-y-1">
              {Object.entries(kpis?.funnel ?? {}).map(([status, n]) => (
                <div key={status} className="flex items-center justify-between">
                  <span className={`badge badge-${status}`}>{status}</span>
                  <span className="mono text-sm tnum" style={{ color: "var(--ink-2)" }}>{String(n)}</span>
                </div>
              ))}
              {Object.keys(kpis?.funnel ?? {}).length === 0 && (
                <p className="text-sm" style={{ color: "var(--ink-3)" }}>empty</p>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
