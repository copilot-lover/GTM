import { useEffect, useState } from "react";
import { api } from "../api";
import type { AgentRun, GtmAgent } from "../types";

function relTime(iso?: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return "—";
  const mins = Math.round(diff / 60000);
  if (mins === 0) return "just now";
  if (Math.abs(mins) < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function humanCadence(seconds?: number | null): string {
  if (!seconds) return "—";
  if (seconds % 86400 === 0) return seconds / 86400 >= 2 ? `${seconds / 86400} days` : "Daily";
  if (seconds % 3600 === 0) return seconds === 3600 ? "Hourly" : `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds}s`;
}

const OK_STATUSES = new Set(["success", "succeeded", "ok", "completed"]);

function healthOf(a: GtmAgent): "ok" | "warn" | "down" {
  if (a.enabled === false) return "down";
  const status = (a.last_status ?? "").toLowerCase();
  if (status && !OK_STATUSES.has(status) && status !== "skipped") return "down";
  const cadence = a.schedule_seconds ?? 0;
  if (a.last_run) {
    const age = (Date.now() - new Date(a.last_run).getTime()) / 1000;
    if (!Number.isNaN(age) && cadence > 0 && age > cadence * 2) return "warn";
  }
  if (status) return "ok";
  return a.last_run ? "warn" : "down";
}

const DOT: Record<"ok" | "warn" | "down", string> = {
  ok: "hdot hdot-ok",
  warn: "hdot hdot-warn",
  down: "hdot hdot-down",
};

export default function AgentsDashboard() {
  const [agents, setAgents] = useState<GtmAgent[]>([]);
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, AgentRun[]>>({});
  const [ticking, setTicking] = useState(false);

  async function load() {
    try {
      const d = await api<{ agents: GtmAgent[] }>("/gtm/agents");
      setAgents(d.agents ?? []);
      setError("");
    } catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!selected || runs[selected]) return;
    api<{ runs: AgentRun[] }>(`/gtm/agents/${selected}/runs?limit=20`)
      .then((d) => setRuns((r) => ({ ...r, [selected]: d.runs ?? [] })))
      .catch((e: any) => setError(e.message));
  }, [selected, runs]);

  async function tick() {
    setTicking(true);
    try {
      await api("/gtm/scheduler/tick", { method: "POST" });
      setActionMsg("Scheduler tick complete");
      await load();
    } catch (e: any) { setError(e.message); }
    setTicking(false);
  }

  const sel = agents.find((a) => a.agent === selected) ?? null;
  const selRuns = selected ? runs[selected] : undefined;

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Agents</h1>
        <span className="badge badge-new">{agents.length} registered</span>
        <button className="btn ml-auto" onClick={tick} disabled={ticking}>
          {ticking ? "Running…" : "▶ Run scheduler tick"}
        </button>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {actionMsg && <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2.5 text-sm text-emerald-700">{actionMsg}</div>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 shadow-sm bg-white">
        <table className="tbl min-w-[900px]">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Health</th>
              <th>Cadence</th>
              <th>Last run</th>
              <th>Next run</th>
              <th className="text-center">Tokens 24h</th>
              <th className="text-center">Runs 24h</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent} className="cursor-pointer" onClick={() => setSelected(selected === a.agent ? null : a.agent)}>
                <td className="font-medium text-slate-900">{a.agent}</td>
                <td><span className={DOT[healthOf(a)]} />{a.enabled === false ? "disabled" : a.last_status ?? "never run"}</td>
                <td className="mono text-xs">{humanCadence(a.schedule_seconds)}</td>
                <td className="mono text-xs">{relTime(a.last_run)}</td>
                <td className="mono text-xs">{a.next_run ? new Date(a.next_run).toLocaleString() : "—"}</td>
                <td className="mono text-center">{a.tokens_24h ?? "—"}</td>
                <td className="mono text-center">
                  {(a.successes_24h ?? a.runs_24h ?? 0)}
                  {a.failures_24h ? <span className="text-red-600"> / {a.failures_24h} fail</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {agents.length === 0 && !error && (
        <div className="panel text-center text-slate-400 py-10">no agents registered</div>
      )}

      {sel && (
        <div className="panel space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-semibold text-slate-900">{sel.agent}</div>
            <div className="flex flex-wrap gap-2">
              {sel.avg_latency_ms != null && <span className="badge badge-new mono">avg {(sel.avg_latency_ms / 1000).toFixed(1)}s</span>}
              {sel.task_type && <span className="badge badge-enriching">{sel.task_type}</span>}
              {sel.pool && <span className="badge badge-outreach_ready">pool: {sel.pool}</span>}
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[13px]">
            <div><span className="text-slate-400 block text-xs">Schedule</span>{humanCadence(sel.schedule_seconds)}</div>
            <div><span className="text-slate-400 block text-xs">Enabled</span>{String(sel.enabled)}</div>
            <div><span className="text-slate-400 block text-xs">Capabilities</span>{(sel.capabilities ?? []).join(", ") || "—"}</div>
            <div><span className="text-slate-400 block text-xs">Cannot send</span>{String(sel.cannot_send)}</div>
          </div>
          {sel.last_error && (
            <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700 break-all">
              Last error: {sel.last_error}
            </div>
          )}
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="tbl min-w-[700px]" style={{ boxShadow: "none", border: "none" }}>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Trigger</th>
                  <th>Started</th>
                  <th className="text-center">Latency</th>
                  <th className="text-center">Tokens</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {(selRuns ?? []).map((r) => (
                  <tr key={r.id}>
                    <td><span className={`badge badge-${r.status === "success" ? "ready" : r.status === "running" ? "enriching" : "failed"}`}>{r.status ?? "—"}</span></td>
                    <td>{r.trigger ?? "—"}</td>
                    <td className="mono text-xs">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                    <td className="mono text-center text-xs">{r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(1)}s` : "—"}</td>
                    <td className="mono text-center text-xs">{(r.tokens_in ?? 0) + (r.tokens_out ?? 0)}</td>
                    <td className="text-xs text-red-600 break-all max-w-[280px]">{r.error ?? ""}</td>
                  </tr>
                ))}
                {selRuns?.length === 0 && (
                  <tr><td colSpan={6} className="text-slate-400 text-sm">no runs recorded</td></tr>
                )}
                {!selRuns && <tr><td colSpan={6} className="text-slate-400 text-sm">loading…</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
