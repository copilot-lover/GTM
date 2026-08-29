import { useEffect, useState } from "react";
import { api } from "../api";
import type { Signal } from "../types";

function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 90 ? "bg-emerald-100 text-emerald-800"
    : score >= 70 ? "bg-sky-100 text-sky-800"
    : score >= 50 ? "bg-amber-100 text-amber-800"
    : "bg-slate-100 text-slate-600";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{score}</span>;
}

export default function SignalsDashboard() {
  const [items, setItems] = useState<Signal[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Signal[]>("/control-plane/signals")
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e: any) => setError(e.message));
  }, []);

  const filtered = filter ? items.filter((s) => s.role_category === filter) : items;
  const categories = [...new Set(items.map((s) => s.role_category))].sort();
  const newToday = items.filter((s) => s.freshness === "today").length;
  const avgScore = items.length ? Math.round(items.reduce((a, b) => a + b.score, 0) / items.length) : 0;

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Signals</h1>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="card px-4 py-3.5">
          <div className="mono text-2xl font-semibold text-slate-900">{items.length}</div>
          <div className="text-xs text-slate-500">Total signals</div>
        </div>
        <div className="card px-4 py-3.5">
          <div className="mono text-2xl font-semibold text-emerald-600">{newToday}</div>
          <div className="text-xs text-slate-500">New today</div>
        </div>
        <div className="card px-4 py-3.5">
          <div className="mono text-2xl font-semibold text-sky-600">{avgScore}</div>
          <div className="text-xs text-slate-500">Avg score</div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="mono text-xs text-slate-400">{filtered.length} shown</span>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 shadow-sm bg-white">
        <table className="tbl min-w-[800px]">
          <thead>
            <tr>
              <th className="w-[22%]">Company</th>
              <th className="w-[16%]">Role Category</th>
              <th className="w-[8%] text-center">Score</th>
              <th className="w-[12%]">Freshness</th>
              <th className="w-[12%]">Posted Age</th>
              <th className="w-[14%]">Status</th>
              <th className="w-[16%]">Job Link</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.id}>
                <td className="font-medium text-slate-900">{s.business_name}</td>
                <td>{s.role_category}</td>
                <td className="text-center"><ScoreBadge score={s.score} /></td>
                <td>{s.freshness}</td>
                <td className="mono text-xs">{s.posted_age}</td>
                <td><span className={`badge badge-${s.status === "new" ? "new" : s.status === "qualified" ? "qualified" : "contacted"}`}>{s.status}</span></td>
                <td>
                  {s.source_url ? (
                    <a className="text-blue-600 hover:underline text-xs" href={s.source_url} target="_blank" rel="noreferrer">view posting</a>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <div className="panel text-center text-slate-400 py-10">no signals found</div>}
    </div>
  );
}
