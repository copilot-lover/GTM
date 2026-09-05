import { useEffect, useState } from "react";
import { api } from "../api";
import type { ControlPlaneOverview } from "../types";
import { Pause, Play, ArrowsClockwise, CheckCircle, Warning } from "@phosphor-icons/react";

const CHECK_LABELS: Record<string, string> = {
  database: "Postgres",
  n8n: "n8n",
  twilio: "Twilio",
  llm_openai: "OpenAI",
  llm_anthropic: "Anthropic",
  smtp: "SMTP",
};

function healthState(v: unknown): "ok" | "warn" | "down" {
  if (v === "ok" || v === "configured") return "ok";
  if (v === "down" || v === "unreachable" || String(v).startsWith("http_")) return "down";
  return "warn";
}

function Dot({ st }: { st: string }) {
  return <span className={`hdot ${st === "ok" ? "hdot-ok" : st === "warn" ? "hdot-warn" : "hdot-down"} mr-0`} />;
}

function Kpi({ label, value, i = 0 }: { label: string; value: React.ReactNode; i?: number }) {
  return (
    <div className="card px-5 py-4 reveal" style={{ "--i": i } as React.CSSProperties}>
      <div className="mono text-[28px] font-semibold leading-none tnum" style={{ color: "var(--ink)" }}>
        {value}
      </div>
      <div className="text-xs mt-1.5" style={{ color: "var(--ink-3)" }}>{label}</div>
    </div>
  );
}

export default function ControlCenter() {
  const [data, setData] = useState<ControlPlaneOverview | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");

  async function load() {
    try {
      const [ov, sh, d, al] = await Promise.all([
        api<ControlPlaneOverview>("/control-plane/overview"),
        api("/system-health"),
        api("/dashboard"),
        api<{ alerts: any[] }>("/control-plane/alerts"),
      ]);
      setData(ov);
      setHealth(sh);
      setDash(d);
      setAlerts(al.alerts ?? []);
      setError("");
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  async function act(path: string, msg: string) {
    try {
      await api(path, { method: "POST" });
      setActionMsg(msg);
      setError("");
      load();
    } catch (e: any) { setError(e.message); }
  }

  const cap = data?.capacity;
  const checks: Record<string, unknown> = health?.checks ?? {};
  const funnels: [string, unknown][] = Object.entries(dash?.funnel ?? {});
  const totalDomains = Object.values(data?.domains ?? {}).reduce((a, b) => a + b, 0);
  const totalMailboxes = Object.values(data?.mailboxes ?? {}).reduce((a, b) => a + b, 0);
  const healthyMailboxes = (data?.mailboxes?.healthy ?? 0) + (data?.mailboxes?.normal ?? 0);
  const score = data?.health_score ?? 0;

  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>Control Center</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>Everything at a glance.</p>
        </div>
        <div className="ml-auto flex gap-2">
          {data?.paused ? (
            <button className="btn btn-green" onClick={() => act("/control-plane/resume", "Sending resumed")}>
              <Play size={14} weight="bold" /> Resume sending
            </button>
          ) : (
            <button className="btn btn-ghost" onClick={() => act("/control-plane/pause", "Sending paused")} disabled={!data}>
              <Pause size={14} weight="bold" /> Pause all
            </button>
          )}
          <button className="btn" onClick={() => act("/control-plane/audit/run", "Audit triggered")}>
            <ArrowsClockwise size={14} weight="bold" /> Run audit
          </button>
        </div>
      </div>

      {error && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--bad-deep)", borderColor: "#f2cfcf", background: "var(--bad-soft)" }}>{error}</div>}
      {actionMsg && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--good-deep)", borderColor: "#d2e9de", background: "var(--good-soft)" }}>{actionMsg}</div>}
      {data?.paused && (
        <div className="card px-4 py-2.5 text-sm flex items-center gap-2" style={{ color: "var(--warn-deep)", borderColor: "#f0e6c8", background: "var(--warn-soft)" }}>
          <Pause size={14} weight="bold" /> Sending paused — resume to continue outreach.
        </div>
      )}

      {/* Health score + systems strip */}
      <div className="card px-5 py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div>
          <div className="mono text-[28px] font-semibold leading-none tnum" style={{ color: "var(--ink)" }}>
            {score}<span className="text-base" style={{ color: "var(--ink-3)" }}>/100</span>
          </div>
          <div className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>Health score</div>
        </div>
        <div className="h-10 w-px" style={{ background: "var(--line)" }} />
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-[13px] flex-1">
          {Object.entries(checks).filter(([k]) => k !== "agent_failures_24h").map(([k, v]) => {
            const st = healthState(v);
            return (
              <span key={k} className="inline-flex items-center" style={{ color: "var(--ink-2)" }} title={String(v)}>
                <Dot st={st} />
                {CHECK_LABELS[k] ?? k}
                {st === "warn" && <span className="ml-1.5 text-[10px] font-medium uppercase rounded px-1.5 py-0.5" style={{ background: "var(--warn-soft)", color: "var(--warn-deep)" }}>not configured</span>}
                {st === "down" && <span className="ml-1.5 text-[10px] font-medium uppercase rounded px-1.5 py-0.5" style={{ background: "var(--bad-soft)", color: "var(--bad-deep)" }}>down</span>}
              </span>
            );
          })}
          {typeof checks.agent_failures_24h === "number" && (checks.agent_failures_24h as number) > 0 && (
            <span className="inline-flex items-center" style={{ color: "var(--ink-2)" }}>
              <Dot st="warn" />
              {checks.agent_failures_24h} agent failures (24h)
            </span>
          )}
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <Kpi label="Sent today" value={`${cap?.sent_today ?? 0}/${cap?.today_limit ?? 0}`} i={0} />
        <Kpi label="Queued" value={cap?.queued ?? 0} i={1} />
        <Kpi label="Follow-ups due" value={cap?.followups_due ?? 0} i={2} />
        <Kpi label="Pending approvals" value={dash?.pending_approvals ?? 0} i={3} />
        <Kpi label="Replies" value={dash?.kpis?.replies_total ?? 0} i={4} />
        <Kpi label="AI spend today" value={`$${Number(dash?.ai_spend_today_usd ?? 0).toFixed(2)}`} i={5} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 items-start">
        {/* Funnel */}
        <section className="panel">
          <div className="flex items-center justify-between">
            <div className="panel-title">Pipeline funnel</div>
            <a href="/leads" className="text-xs" style={{ color: "var(--accent)" }}>all leads</a>
          </div>
          <div className="space-y-1.5">
            {funnels.length === 0 && <p className="text-sm" style={{ color: "var(--ink-3)" }}>no leads yet</p>}
            {funnels.map(([status, n]) => (
              <div key={status} className="flex items-center justify-between">
                <span className={`badge badge-${status}`}>{status}</span>
                <span className="mono text-sm tnum" style={{ color: "var(--ink-2)" }}>{String(n)}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm" style={{ borderColor: "var(--line)" }}>
            <span style={{ color: "var(--ink-3)" }}>New leads today</span>
            <span className="mono text-right tnum" style={{ color: "var(--ink)" }}>{dash?.kpis?.new_leads_today ?? 0}</span>
            <span style={{ color: "var(--ink-3)" }}>Contacted</span>
            <span className="mono text-right tnum" style={{ color: "var(--ink)" }}>{dash?.kpis?.contacted_total ?? 0}</span>
            <span style={{ color: "var(--ink-3)" }}>Meetings upcoming</span>
            <span className="mono text-right tnum" style={{ color: "var(--ink)" }}>{dash?.kpis?.upcoming_meetings ?? 0}</span>
          </div>
        </section>

        {/* Infrastructure */}
        <section className="panel">
          <div className="flex items-center justify-between">
            <div className="panel-title">Infrastructure</div>
            <a href="/providers" className="text-xs" style={{ color: "var(--accent)" }}>providers</a>
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--ink-2)" }}>Domains</span>
              <span className="flex items-center gap-1.5">
                <span className="mono tnum" style={{ color: "var(--ink)" }}>{totalDomains}</span>
                {totalDomains === 0
                  ? <span className="text-xs" style={{ color: "var(--ink-3)" }}>none</span>
                  : Object.entries(data?.domains ?? {}).map(([k, n]) => (
                      <span key={k} className={`badge badge-${k}`}>{k} {n}</span>
                    ))}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--ink-2)" }}>Mailboxes</span>
              <span className="flex items-center gap-1.5">
                <span className="mono tnum" style={{ color: "var(--ink)" }}>{totalMailboxes}</span>
                {totalMailboxes === 0
                  ? <span className="text-xs" style={{ color: "var(--ink-3)" }}>none</span>
                  : healthyMailboxes > 0 && <span className="badge badge-qualified">{healthyMailboxes} healthy</span>}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--ink-2)" }}>LLM / API providers</span>
              <span className="mono tnum" style={{ color: "var(--ink)" }}>{data?.providers?.length ?? 0}</span>
            </div>
            {data?.providers?.map((p) => (
              <div key={p.provider} className="flex items-center justify-between text-xs">
                <span style={{ color: "var(--ink-3)" }}>{p.provider}</span>
                <span className="mono tnum" style={{ color: p.used >= p.quota ? "var(--bad-deep)" : "var(--ink-2)" }}>
                  {p.used}/{p.quota}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Alerts */}
        <section className="panel">
          <div className="flex items-center justify-between">
            <div className="panel-title">Alerts</div>
            <a href="/alerts" className="text-xs" style={{ color: "var(--accent)" }}>all alerts</a>
          </div>
          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--ink-3)" }}>
              <CheckCircle size={16} weight="bold" style={{ color: "var(--good-deep)" }} /> all clear
            </div>
          ) : (
            <div className="space-y-2">
              {alerts.slice(0, 5).map((a) => (
                <div key={a.id} className="flex items-start gap-2 text-sm">
                  <Warning size={14} weight="bold" className="mt-0.5 shrink-0"
                    style={{ color: a.severity === "critical" ? "var(--bad)" : "var(--warn-deep)" }} />
                  <span>
                    <span className="block" style={{ color: "var(--ink)" }}>{a.title ?? a.message ?? a.kind}</span>
                    <span className="block text-xs" style={{ color: "var(--ink-3)" }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}