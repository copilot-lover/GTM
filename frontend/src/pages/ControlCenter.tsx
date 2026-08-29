import { useEffect, useState } from "react";
import { api } from "../api";
import type { ControlPlaneOverview } from "../types";

function HealthDot({ status }: { status: string }) {
  const cls = status === "healthy" ? "hdot-ok" : status === "degraded" ? "hdot-warn" : "hdot-down";
  return <span className={`hdot ${cls}`} />;
}

export default function ControlCenter() {
  const [data, setData] = useState<ControlPlaneOverview | null>(null);
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");

  async function load() {
    try {
      const d = await api<ControlPlaneOverview>("/control-plane/overview");
      setData(d);
      setError("");
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  async function pauseAll() {
    try { await api("/control-plane/pause", { method: "POST" }); setActionMsg("All pipelines paused"); load(); }
    catch (e: any) { setError(e.message); }
  }
  async function resumeAll() {
    try { await api("/control-plane/resume", { method: "POST" }); setActionMsg("All pipelines resumed"); load(); }
    catch (e: any) { setError(e.message); }
  }
  async function runAudit() {
    try { await api("/control-plane/audit/run", { method: "POST" }); setActionMsg("Audit triggered"); }
    catch (e: any) { setError(e.message); }
  }

  const sys = data?.systems ?? {};
  const today = data?.today;
  const pipeline = data?.pipeline ?? [];

  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <h1 className="text-xl font-semibold text-slate-900">Control Center</h1>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {actionMsg && <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2.5 text-sm text-emerald-700">{actionMsg}</div>}

      {/* System Health */}
      <div className="card px-4 py-3">
        <div className="panel-title">System Health</div>
        <div className="flex flex-wrap gap-4 text-[13px]">
          {Object.entries(sys).map(([k, v]) => (
            <span key={k} className="inline-flex items-center text-slate-600">
              <HealthDot status={v.status} />
              {v.label}
            </span>
          ))}
          {Object.keys(sys).length === 0 && <span className="text-slate-400">loading…</span>}
        </div>
      </div>

      {/* Today's Panel */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Capacity", value: today?.capacity ?? 0 },
          { label: "Sent today", value: today?.sent ?? 0, accent: "text-sky-600" },
          { label: "Queued", value: today?.queued ?? 0, accent: "text-amber-600" },
          { label: "Follow-ups due", value: today?.followups_due ?? 0, accent: "text-red-600" },
        ].map((kpi) => (
          <div key={kpi.label} className="card px-4 py-3.5">
            <div className={`mono text-2xl font-semibold ${kpi.accent ?? "text-slate-900"}`}>{String(kpi.value)}</div>
            <div className="text-xs text-slate-500 mt-0.5">{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="panel">
        <div className="panel-title">Quick Actions</div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-ghost" onClick={pauseAll}>⏸ Pause all</button>
          <button className="btn btn-green" onClick={resumeAll}>▶ Resume all</button>
          <button className="btn" onClick={runAudit}>⟲ Run audit</button>
        </div>
      </div>

      {/* Pipeline Map */}
      <div className="card overflow-hidden">
        <div className="px-5 pt-4 pb-3 border-b border-slate-100">
          <div className="panel-title mb-0">Pipeline Stages</div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 p-4">
          {pipeline.map((s) => (
            <div key={s.name} className={`border rounded-xl p-4 ${s.health === "healthy" ? "border-emerald-200 bg-emerald-50/40" : s.health === "degraded" ? "border-amber-200 bg-amber-50/40" : "border-red-200 bg-red-50/40"}`}>
              <div className="flex items-center gap-2 mb-2">
                <HealthDot status={s.health} />
                <span className="text-sm font-medium text-slate-900">{s.name}</span>
              </div>
              <div className="mono text-2xl font-semibold text-slate-900">{s.count}</div>
            </div>
          ))}
          {pipeline.length === 0 && <div className="text-slate-400 text-sm col-span-full">no pipeline data</div>}
        </div>
      </div>
    </div>
  );
}
