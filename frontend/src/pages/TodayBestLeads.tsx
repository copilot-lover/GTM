import { useEffect, useState } from "react";
import { api } from "../api";
import type { LeadQueueItem } from "../types";

function ScoreBadge({ score, tier }: { score: number; tier: string }) {
  const color =
    tier === "A+" ? "bg-emerald-100 text-emerald-800"
    : tier === "A" ? "bg-sky-100 text-sky-800"
    : tier === "B" ? "bg-amber-100 text-amber-800"
    : tier === "C" ? "bg-slate-100 text-slate-600"
    : "bg-zinc-100 text-zinc-500";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${color}`}>
      {score} · {tier}
    </span>
  );
}

export default function TodayBestLeads() {
  const [items, setItems] = useState<LeadQueueItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<LeadQueueItem[]>("/control-plane/leads-queue?sort=opportunity_score&limit=10")
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e: any) => setError(e.message));
  }, []);

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Today's Best Leads</h1>
        <span className="badge badge-qualified">{items.length} scored</span>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {items.map((l) => (
          <div key={l.id} className="card px-5 py-4 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <a href={`/leads/${l.id}`} className="text-[15.5px] font-semibold text-slate-900 hover:text-blue-600 hover:underline truncate block">
                  {l.business_name}
                </a>
                <div className="text-xs text-slate-400">{[l.city, l.state].filter(Boolean).join(", ")}</div>
              </div>
              <ScoreBadge score={l.opportunity_score} tier={l.priority_tier} />
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span>{l.signal_type}</span>
              {l.signal_age_days != null && <span>{l.signal_age_days}d old</span>}
              {l.decision_maker && <span>· {l.decision_maker}</span>}
              <span>· email: {l.email_status}</span>
            </div>
            <div className="text-xs text-slate-600">{l.recommended_action}</div>
            <div className="flex gap-2 pt-1">
              <a href={`/leads/${l.id}`} className="btn btn-green text-xs" style={{ padding: "5px 14px" }}>
                Call + email now
              </a>
            </div>
          </div>
        ))}
      </div>

      {items.length === 0 && (
        <div className="panel text-center text-slate-400 py-10">no leads scored yet</div>
      )}
    </div>
  );
}
