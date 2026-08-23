import { useEffect, useState } from "react";
import { api } from "../api";

export default function Dashboard() {
  const [data, setData] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api("/dashboard"), api("/system-health")])
      .then(([d, h]) => { setData(d); setHealth(h); })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-400">{error} — <button className="underline" onClick={() => location.reload()}>retry</button></p>;
  if (!data) return <div className="animate-pulse text-zinc-600">loading…</div>;

  const degraded = health && Object.entries(health.checks).some(
    ([k, v]) => k !== "database" && v !== "ok" && v !== "configured"
  );

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Dashboard</h1>
      {degraded && (
        <div className="bg-red-950/60 border border-red-800 rounded px-4 py-2 text-sm text-red-300">
          System degraded: {JSON.stringify(health.checks)}
        </div>
      )}
      <div className="grid grid-cols-5 gap-3">
        {[
          ["New leads today", data.kpis.new_leads_today],
          ["Contacted", data.kpis.contacted_total],
          ["Replies", data.kpis.replies_total],
          ["Upcoming meetings", data.kpis.upcoming_meetings],
          ["Open pipeline $", data.kpis.open_pipeline_mrr],
        ].map(([label, value]) => (
          <div key={label as string} className="bg-[#14161b] border border-zinc-800 rounded p-3">
            <div className="mono text-2xl text-[#22c55e]">{String(value)}</div>
            <div className="text-xs text-zinc-500 mt-1">{label}</div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-6">
        <section>
          <h2 className="text-sm font-medium text-zinc-400 mb-2">Pipeline</h2>
          <div className="bg-[#14161b] border border-zinc-800 rounded p-3 space-y-1">
            {Object.entries(data.funnel).map(([status, n]) => (
              <div key={status} className="flex justify-between mono text-sm">
                <span className="text-zinc-400">{status}</span>
                <span>{String(n)}</span>
              </div>
            ))}
            {Object.keys(data.funnel).length === 0 && (
              <p className="text-zinc-600 text-sm">no leads yet — run your first batch</p>
            )}
          </div>
        </section>
        <section>
          <h2 className="text-sm font-medium text-zinc-400 mb-2">
            Hot leads · {data.pending_approvals} pending approval · ${data.ai_spend_today_usd.toFixed(2)} AI today
          </h2>
          <div className="bg-[#14161b] border border-zinc-800 rounded divide-y divide-zinc-800/70">
            {data.hot_leads.map((l: any) => (
              <a key={l.id} href={`/leads/${l.id}`} className="flex justify-between px-3 py-2 hover:bg-zinc-800/40 text-sm">
                <span>{l.business_name}</span>
                <span className="mono text-[#22c55e]">{l.priority_score ?? "—"}</span>
              </a>
            ))}
            {data.hot_leads.length === 0 && <p className="px-3 py-2 text-zinc-600 text-sm">no hot leads</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
