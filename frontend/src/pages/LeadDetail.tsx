import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { LeadWhy, LeadWhyContribution } from "../types";

interface LeadDetailLead {
  id: string;
  business_name: string;
  city: string | null;
  state: string | null;
  phone: string | null;
  status: string;
  lead_score: number | null;
  priority_score: number | null;
  primary_pain: string | null;
  secondary_pain: string | null;
  recommended_offer: string | null;
  owner_name: string | null;
  fit_status: string;
  review_reasons?: string[];
}

interface LeadDetailActivity {
  id: string;
  created_at: string;
  actor: string;
  summary: string;
}

interface LeadDetailMessage {
  id: string;
  status: string;
  gtm_stage: string | null;
  sequence_step: number | null;
  created_at: string;
}

interface LeadDetailData {
  lead: LeadDetailLead;
  contact: Record<string, unknown>;
  activities: LeadDetailActivity[];
  messages: LeadDetailMessage[];
  calls: unknown[];
  allowed_transitions: string[];
}

function contribLabel(c: LeadWhyContribution): string {
  if (typeof c.value === "string" && c.value) return c.value;
  return c.label ?? c.component ?? "signal";
}

function contribPoints(c: LeadWhyContribution): number | null {
  if (typeof c.points === "number") return c.points;
  if (typeof c.signal_score === "number") return c.signal_score;
  return null;
}

function whyTier(why: LeadWhy): string | null {
  const score = typeof why.score === "number" ? why.score : why.priority;
  if (typeof score !== "number") return null;
  const contributions = why.contributions ?? why.components?.contributions ?? [];
  const recent = contributions.some(
    (c) => typeof c.age_days === "number" && c.age_days <= 7,
  );
  if (score >= 70 && recent) return "P1";
  if (score >= 50) return "P2";
  return "P3";
}

function WhyPanel({ leadId }: { leadId: string }) {
  const [why, setWhy] = useState<LeadWhy | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<LeadWhy>(`/gtm/leads/${leadId}/why`)
      .then(setWhy)
      .catch((e: any) => setError(e.message));
  }, [leadId]);

  if (error) return null;
  if (!why) return <div className="panel text-slate-400 text-sm">loading why…</div>;

  const contributions = why.contributions ?? why.components?.contributions ?? [];
  if (why.score == null && contributions.length === 0) {
    return (
      <div className="panel">
        <h2>Why</h2>
        <div className="gtm-empty">no scores computed yet</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="flex flex-wrap gap-2 items-center mb-3">
        <h2 style={{ marginBottom: 0 }}>Why</h2>
        <span className="badge badge-new mono ml-auto">{why.score ?? "—"}</span>
        {whyTier(why) && (
          <span className="badge badge-qualified mono">{whyTier(why)}</span>
        )}
      </div>
      <div className="space-y-1.5">
        {contributions.map((c, i) => {
          const pts = contribPoints(c);
          return (
            <div key={i} className="text-sm text-slate-700 flex gap-2">
              <span className="mono text-emerald-600">{pts != null ? `+${pts}` : "+"}</span>
              <span>{contribLabel(c)}</span>
              {typeof c.age_days === "number" && (
                <span className="text-xs text-slate-400">{c.age_days}d old</span>
              )}
            </div>
          );
        })}
        {contributions.length === 0 && <div className="gtm-empty">no contribution breakdown</div>}
      </div>
    </div>
  );
}

export default function LeadDetail() {
  const { id } = useParams();
  const [data, setData] = useState<LeadDetailData | null>(null);
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

  const l = data?.lead;
  if (!l) return <div className="w-full max-w-7xl mx-auto space-y-5"><div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">Lead not found</div></div>;
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

      {(data.lead.review_reasons as string[] | undefined)?.length && (
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
          <WhyPanel leadId={id ?? ""} />
          <div className="panel">
            <h2>Outbound messages</h2>
            <div className="space-y-1.5">
              {(data.messages ?? []).map((m) => (
                <div key={m.id} className="flex items-center gap-2 text-sm">
                  <span className={`badge badge-${m.status}`}>{m.gtm_stage ?? m.status}</span>
                  <span className="text-slate-500 text-xs">
                    step {m.sequence_step ?? "—"} · {new Date(m.created_at).toLocaleString()}
                  </span>
                </div>
              ))}
              {(data.messages ?? []).length === 0 && <div className="gtm-empty">no messages</div>}
            </div>
          </div>
          <div className="panel">
            <h2>Next action</h2>
            <div className="flex gap-2 flex-wrap">
              {(data.allowed_transitions ?? []).map((t: string) => (
                <button key={t} onClick={() => transition(t)}
                  className={`gtm-btn ${t === "do_not_call" ? "gtm-btn-red" : "gtm-btn-ghost"}`}>
                  → {t}
                </button>
              ))}
              {(data.allowed_transitions ?? []).length === 0 && (
                <span className="text-slate-400">terminal state</span>
              )}
            </div>
          </div>
        </section>

        <section>
          <div className="panel">
            <h2>Activity timeline</h2>
            <div className="divide-y divide-slate-100" style={{ maxHeight: "60vh", overflow: "auto" }}>
              {(data.activities ?? []).map((a) => (
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
              {(data.activities ?? []).length === 0 && <div className="gtm-empty">no activity</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
