import { useEffect, useState } from "react";
import { api } from "../api";

export default function Approvals() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try { setItems((await api("/outreach/approvals")).items); }
    catch (e: any) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function act(messageId: string, action: "approve" | "reject") {
    await api("/outreach/approvals", {
      method: "POST",
      body: JSON.stringify({
        message_ids: [messageId], action,
        reason: action === "reject" ? "operator rejected" : null,
      }),
    });
    load();
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
              <span className="text-slate-500 text-xs">
                {m.city}, {m.state} · {m.primary_pain ?? "—"} → {m.recommended_offer ?? "—"}
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
