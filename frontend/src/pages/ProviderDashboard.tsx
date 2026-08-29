import { useEffect, useState } from "react";
import { api } from "../api";
import type { Provider } from "../types";

function CircuitIndicator({ status }: { status: string }) {
  const cls = status === "closed" ? "bg-emerald-500" : status === "open" ? "bg-red-500" : "bg-amber-400";
  const label = status === "closed" ? "Operational" : status === "open" ? "Tripped" : "Recovering";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full ${cls}`} />
      <span className="text-xs text-slate-600">{label}</span>
    </span>
  );
}

function ProgressBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const color = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-xs text-slate-500">{pct}%</span>
    </div>
  );
}

export default function ProviderDashboard() {
  const [items, setItems] = useState<Provider[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Provider[]>("/control-plane/providers")
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e: any) => setError(e.message));
  }, []);

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Providers</h1>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 shadow-sm bg-white">
        <table className="tbl min-w-[800px]">
          <thead>
            <tr>
              <th className="w-[20%]">Provider</th>
              <th className="w-[12%] text-center">Quota</th>
              <th className="w-[10%] text-center">Used</th>
              <th className="w-[15%]">Remaining</th>
              <th className="w-[13%]">Reset Date</th>
              <th className="w-[12%] text-center">Success Rate</th>
              <th className="w-[18%]">Circuit Breaker</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.name}>
                <td className="font-medium text-slate-900">{p.name}</td>
                <td className="mono text-center">{p.quota}</td>
                <td className="mono text-center">{p.used}</td>
                <td><ProgressBar used={p.used} total={p.quota} /></td>
                <td className="mono text-xs">{p.reset_date}</td>
                <td className="mono text-center">{Math.round(p.success_rate * 100)}%</td>
                <td><CircuitIndicator status={p.circuit_breaker} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 && <div className="panel text-center text-slate-400 py-10">no providers configured</div>}
    </div>
  );
}
