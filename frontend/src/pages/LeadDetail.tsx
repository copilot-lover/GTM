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

  if (error) return <div className="gtm-page"><div className="gtm-alert gtm-alert-red">{error}</div></div>;
  if (!data) return <div className="gtm-page gtm-muted">loading…</div>;

  const l = data.lead;
  return (
    <div className="gtm-page">
      <div className="gtm-toolbar">
        <div>
          <h1>{l.business_name}</h1>
          <span className="gtm-muted" style={{ fontSize: 13 }}>
            {[l.city, l.state].filter(Boolean).join(", ")} · {l.phone ?? "no phone"}
          </span>
        </div>
        <span className="gtm-pill" style={{ marginLeft: "auto" }}>
          <span className="gtm-dot" /> {l.status}
        </span>
        <span className="gtm-pill">{l.lead_score ?? "—"}/10 · P{l.priority_score ?? "—"}</span>
      </div>

      {data.lead.review_reasons?.length > 0 && (
        <div className="gtm-alert gtm-alert-amber">
          Review queue: {(data.lead.review_reasons as string[]).join(" · ")}
        </div>
      )}

      <div className="grid grid-cols-2 gap-5">
        <section className="space-y-4">
          <div className="gtm-panel">
            <h2>AI Research</h2>
            <div className="gtm-kv"><span>Primary pain</span><span>{l.primary_pain ?? "—"}</span></div>
            <div className="gtm-kv"><span>Secondary pain</span><span>{l.secondary_pain ?? "—"}</span></div>
            <div className="gtm-kv"><span>Recommended offer</span><span>{l.recommended_offer ?? "—"}</span></div>
            <div className="gtm-kv"><span>Owner</span><span>{l.owner_name ?? "—"}</span></div>
            <div className="gtm-kv"><span>Fit status</span><span>{l.fit_status}</span></div>
          </div>
          <div className="gtm-panel">
            <h2>Next action</h2>
            <div className="flex gap-2 flex-wrap">
              {data.allowed_transitions.map((t: string) => (
                <button key={t} onClick={() => transition(t)}
                  className={`gtm-btn ${t === "do_not_call" ? "gtm-btn-red" : "gtm-btn-ghost"}`}>
                  → {t}
                </button>
              ))}
              {data.allowed_transitions.length === 0 && (
                <span className="gtm-muted">terminal state</span>
              )}
            </div>
          </div>
        </section>

        <section>
          <div className="gtm-panel">
            <h2>Activity timeline</h2>
            <div className="gtm-timeline" style={{ maxHeight: "60vh", overflow: "auto" }}>
              {data.activities.map((a: any) => (
                <div key={a.id} className="gtm-tl-row">
                  <span className="gtm-tl-time mono">
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
