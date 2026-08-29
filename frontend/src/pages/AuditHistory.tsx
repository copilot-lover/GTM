import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuditReport } from "../types";

export default function AuditHistory() {
  const [data, setData] = useState<AuditReport | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      const d = await api<AuditReport>("/control-plane/audit/history");
      setData(d);
      setError("");
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { load(); }, []);

  async function runAudit() {
    setRunning(true);
    try {
      await api("/control-plane/audit/run", { method: "POST" });
      setMsg("Audit completed");
      await load();
    } catch (e: any) { setError(e.message); }
    setRunning(false);
  }

  const history = data?.history ?? [];
  const latest = data?.latest;

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Audit History</h1>
        <button className="btn ml-auto" onClick={runAudit} disabled={running}>
          {running ? "Running…" : "⟲ Run Audit Now"}
        </button>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {msg && <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2.5 text-sm text-emerald-700">{msg}</div>}

      {latest && (
        <div className="card p-5 space-y-3">
          <div className="panel-title">Latest Audit</div>
          <div className="flex items-center gap-4">
            <div className="mono text-3xl font-semibold text-slate-900">{latest.score}</div>
            <div className="text-xs text-slate-500">{latest.date}</div>
          </div>
          <div className="text-sm text-slate-700 whitespace-pre-wrap">{latest.summary}</div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/80">
          <div className="panel-title mb-0">Score History</div>
        </div>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th className="w-[25%]">Date</th>
                <th className="w-[15%] text-center">Score</th>
                <th className="w-[60%]">Summary</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.date}>
                  <td className="mono text-xs">{h.date}</td>
                  <td className="mono text-center font-semibold">{h.score}</td>
                  <td className="text-sm text-slate-600">{h.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {history.length === 0 && !latest && <div className="panel text-center text-slate-400 py-10">no audit history — run your first audit</div>}
    </div>
  );
}
