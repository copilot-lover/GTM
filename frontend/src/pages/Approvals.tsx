import { useEffect, useState } from "react";
import { api } from "../api";
import type { SendDecision } from "../types";

interface ApprovalMessage {
  id: string;
  business_name: string;
  city: string;
  state: string;
  primary_pain: string;
  recommended_offer: string;
  subject: string;
  body_text: string;
  status: string;
  gtm_stage: string;
  sequence_step: number;
  created_at: string;
}

function SendReadiness({ messageId }: { messageId: string }) {
  const [decision, setDecision] = useState<SendDecision | null>(null);

  useEffect(() => {
    let live = true;
    api<SendDecision>(`/outreach/messages/${messageId}/send-decision`)
      .then((d) => { if (live) setDecision(d); })
      .catch(() => { if (live) setDecision({ allowed: false, reasons: ["could not check"] } as SendDecision); });
    return () => { live = false; };
  }, [messageId]);

  if (!decision) return <span className="text-slate-400 text-xs">checking…</span>;
  const reasons = decision.reasons
    ?? (decision.checks ?? []).filter((c) => !c.passed).map((c) => `${c.name}: ${c.detail}`);
  return (
    <span title={reasons.join("\n") || "all checks passed"}
          className={`badge ${decision.allowed ? "badge-ready" : "badge-do_not_call"}`}>
      {decision.allowed ? "✅ CAN_SEND" : "⛔ CANNOT_SEND"}
    </span>
  );
}

export default function Approvals() {
  const [items, setItems] = useState<ApprovalMessage[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try { setItems((await api("/outreach/approvals")).items); }
    catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function act(messageId: string, action: "approve" | "reject") {
    try {
      await api("/outreach/approvals", {
        method: "POST",
        body: JSON.stringify({
          message_ids: [messageId], action,
          reason: action === "reject" ? "operator rejected" : null,
        }),
      });
      load();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1>Approvals</h1>
        <span className="badge badge-pending_approval">{items.length} waiting</span>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {items.length === 0 && (
        <div className="panel text-center text-slate-400 py-10">nothing awaiting approval</div>
      )}

      <div className="space-y-4 max-w-3xl">
        {items.map((m) => (
          <div key={m.id} className="panel space-y-3">
            <div className="flex justify-between items-center">
              <span className="font-semibold text-slate-900 text-[15.5px]">{m.business_name}</span>
              <span className="flex items-center gap-2">
                <SendReadiness messageId={m.id} />
                <span className="text-slate-500 text-xs">
                  {m.city}, {m.state} · {m.primary_pain ?? "—"} → {m.recommended_offer ?? "—"}
                </span>
              </span>
            </div>
            <div className="bg-slate-50 rounded-xl px-4 py-3.5 text-sm whitespace-pre-wrap text-slate-700 border border-slate-100">
              <span className="text-emerald-600 font-semibold">{m.subject}</span>
              {"\n"}{m.body_text}
            </div>
            <div className="flex gap-2">
              <button className="btn btn-green"
                      onClick={() => act(m.id, "approve")}>
                Approve
              </button>
              <button className="btn btn-red"
                      onClick={() => act(m.id, "reject")}>
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
