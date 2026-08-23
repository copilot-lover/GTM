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

  if (error) return <p className="text-red-400">{error}</p>;
  if (!data) return <p className="text-zinc-600">loading…</p>;

  const l = data.lead;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">{l.business_name}</h1>
        <p className="text-xs text-zinc-500 mono">
          {[l.city, l.state].filter(Boolean).join(", ")} · {l.phone ?? "no phone"} ·{" "}
          <span className="text-[#22c55e]">{l.status}</span> · score{" "}
          {l.lead_score ?? "—"}/10 · priority {l.priority_score ?? "—"}
        </p>
      </div>

      {data.lead.review_reasons?.length > 0 && (
        <div className="bg-amber-950/50 border border-amber-800 rounded px-4 py-2 text-sm text-amber-300">
          Review queue: {(data.lead.review_reasons as string[]).join(" · ")}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-zinc-400">AI Research</h2>
          <div className="bg-[#14161b] border border-zinc-800 rounded p-3 text-sm space-y-2">
            <Row k="Primary pain" v={l.primary_pain} />
            <Row k="Secondary pain" v={l.secondary_pain} />
            <Row k="Offer" v={l.recommended_offer} />
            <Row k="Owner" v={l.owner_name} />
            <Row k="Fit status" v={l.fit_status} />
          </div>
          <h2 className="text-sm font-medium text-zinc-400">Next action</h2>
          <div className="flex gap-2 flex-wrap">
            {data.allowed_transitions.map((t: string) => (
              <button key={t} onClick={() => transition(t)}
                className={`rounded px-3 py-1.5 text-xs ${t === "do_not_call" ? "bg-red-900/60 text-red-200" : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700"}`}>
                → {t}
              </button>
            ))}
          </div>
        </section>
        <section>
          <h2 className="text-sm font-medium text-zinc-400">Activity timeline</h2>
          <div className="bg-[#14161b] border border-zinc-800 rounded divide-y divide-zinc-800/60 max-h-[60vh] overflow-auto">
            {data.activities.map((a: any) => (
              <div key={a.id} className="px-3 py-2 text-sm">
                <span className="mono text-xs text-zinc-500 mr-2">
                  {new Date(a.created_at).toLocaleString()}
                </span>
                <span className={
                  a.actor === "human" ? "text-sky-300"
                    : a.actor === "agent" ? "text-violet-300" : "text-zinc-500"
                }>
                  [{a.actor}]
                </span>{" "}
                {a.summary}
              </div>
            ))}
            {data.activities.length === 0 && (
              <p className="px-3 py-2 text-zinc-600 text-sm">no activity</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div className="flex justify-between">
      <span className="text-zinc-500">{k}</span>
      <span className="mono">{v ?? "—"}</span>
    </div>
  );
}
