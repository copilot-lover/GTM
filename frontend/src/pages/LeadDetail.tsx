import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

export default function LeadDetail() {
  const { id } = useParams();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  async function load() {
    try { setData(await api(`/leads/${id}`)); }
    catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, [id]);

  async function transition(to: string) {
    await api(`/leads/${id}/transition`, {
      method: "POST", body: JSON.stringify({ to_status: to }),
    });
    load();
  }

  if (error) return <div className="w-full max-w-7xl mx-auto space-y-5"><div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div></div>;
  if (!data) return <div className="w-full max-w-7xl mx-auto text-slate-400">loading…</div>;

  const l = data.lead;
  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <div className="flex flex-wrap gap-3 items-center">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{l.business_name}</h1>
          <span className="text-slate-500" style={{ fontSize: 13 }}>
            {[l.city, l.state].filter(Boolean).join(", ")} · {l.phone ?? "no phone"}
          </span>
        </div>
        <span className={`badge badge-${l.status} ml-auto`}>{l.status}</span>
        <span className="badge badge-new mono">{l.lead_score ?? "—"}/10 · {l.priority_score ?? "—"}</span>
      </div>

      {data.lead.review_reasons?.length > 0 && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-2.5 text-sm text-amber-800">
          Review queue: {(data.lead.review_reasons as string[]).join(" · ")}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
        <section className="space-y-4">
          <div className="panel">
            <h2>AI Research</h2>
            <div className="gtm-kv"><span>Primary pain</span><span>{l.primary_pain ?? "—"}</span></div>
            <div className="gtm-kv"><span>Secondary pain</span><span>{l.secondary_pain ?? "—"}</span></div>
            <div className="gtm-kv"><span>Recommended offer</span><span>{l.recommended_offer ?? "—"}</span></div>
            <div className="gtm-kv"><span>Owner</span><span>{l.owner_name ?? "—"}</span></div>
            <div className="gtm-kv"><span>Fit status</span><span>{l.fit_status}</span></div>
          </div>
          <div className="panel">
            <h2>Next action</h2>
            <div className="flex gap-2 flex-wrap">
              {data.allowed_transitions.map((t: string) => (
                <button key={t} onClick={() => transition(t)}
                  className={`gtm-btn ${t === "do_not_call" ? "gtm-btn-red" : "gtm-btn-ghost"}`}>
                  → {t}
                </button>
              ))}
              {data.allowed_transitions.length === 0 && (
                <span className="text-slate-400">terminal state</span>
              )}
            </div>
          </div>
        </section>

        <section>
          <div className="panel">
            <h2>Activity timeline</h2>
            <div className="divide-y divide-slate-100" style={{ maxHeight: "60vh", overflow: "auto" }}>
              {data.activities.map((a: any) => (
                <div key={a.id} className="py-2.5 border-b border-slate-100 text-sm last:border-b-0">
                  <span className="mono text-[11px] text-slate-400 mr-2">
                    {new Date(a.created_at).toLocaleString()}
                  </span>
                  <span style={{
                    color: a.actor === "human" ? "#2563eb"
                      : a.actor === "agent" ? "#7c3aed" : "#94a3b8",
                  }}>
                    [{a.actor}]
                  </span>{" "}
                  {a.summary}
                </div>
              ))}
              {data.activities.length === 0 && <div className="gtm-empty">no activity</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
