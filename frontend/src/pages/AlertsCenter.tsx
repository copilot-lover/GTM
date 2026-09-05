import { useEffect, useState } from "react";
import { api } from "../api";
import type { AlertItem } from "../types";

function SeverityBadge({ severity }: { severity: string }) {
  const cls = severity === "critical" ? "bg-red-100 text-red-700"
    : severity === "warning" ? "bg-amber-100 text-amber-800"
    : "bg-sky-100 text-sky-800";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{severity}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "open" ? "bg-red-50 text-red-700"
    : status === "acknowledged" ? "bg-amber-50 text-amber-700"
    : "bg-emerald-50 text-emerald-700";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export default function AlertsCenter() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const d = await api<AlertItem[]>("/control-plane/alerts");
      setItems(Array.isArray(d) ? d : []);
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { load(); }, []);

  async function resolve(id: string) {
    try {
      await api(`/control-plane/alerts/${id}/resolve`, { method: "POST" });
      load();
    } catch (e: any) { setError(e.message); }
  }

  const filtered = items.filter((a) => {
    if (severityFilter && a.severity !== severityFilter) return false;
    if (statusFilter && a.status !== statusFilter) return false;
    return true;
  });

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Alerts</h1>
        <span className="badge badge-do_not_call">{items.filter((a) => a.status === "open").length} open</span>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="flex flex-wrap gap-2 items-center">
        <select className="select" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}
                aria-label="Filter by severity">
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
        <select className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>
        <span className="mono text-xs text-slate-400">{filtered.length} shown</span>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 shadow-sm bg-white">
        <table className="tbl min-w-[800px]">
          <thead>
            <tr>
              <th className="w-[10%]">Severity</th>
              <th className="w-[12%]">Source</th>
              <th className="w-[30%]">Message</th>
              <th className="w-[15%]">Entity</th>
              <th className="w-[15%]">Created</th>
              <th className="w-[10%]">Status</th>
              <th className="w-[8%]"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((a) => (
              <tr key={a.id}>
                <td><SeverityBadge severity={a.severity} /></td>
                <td className="text-sm text-slate-600">{a.source}</td>
                <td className="text-sm text-slate-700">{a.message}</td>
                <td className="mono text-xs">{a.entity}</td>
                <td className="mono text-xs text-slate-500">{new Date(a.created_at).toLocaleString()}</td>
                <td><StatusBadge status={a.status} /></td>
                <td>
                  {a.status !== "resolved" && (
                    <button className="btn btn-ghost text-xs" style={{ padding: "4px 10px" }} onClick={() => resolve(a.id)}>
                      Resolve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <div className="panel text-center text-slate-400 py-10">no alerts</div>}
    </div>
  );
}
