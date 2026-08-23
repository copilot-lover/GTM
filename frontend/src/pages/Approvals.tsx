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
      body: JSON.stringify({ message_ids: [messageId], action, reason: action === "reject" ? "operator rejected" : null }),
    });
    load();
  }

  if (error) return <p className="text-red-400">{error}</p>;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Approval queue</h1>
      {items.length === 0 && <p className="text-zinc-600 text-sm">nothing awaiting approval</p>}
      <div className="space-y-3 max-w-3xl">
        {items.map((m) => (
          <div key={m.id} className="bg-[#14161b] border border-zinc-800 rounded p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="font-medium">{m.business_name}</span>
              <span className="mono text-xs text-zinc-500">
                {m.city}, {m.state} · pain: {m.primary_pain ?? "—"} · offer: {m.recommended_offer ?? "—"}
              </span>
            </div>
            <div className="bg-black/40 rounded p-3 mono text-sm whitespace-pre-wrap">
              <span className="text-[#22c55e]">{m.subject}</span>
              {"\n"}{m.body_text}
            </div>
            <div className="flex gap-2">
              <button onClick={() => act(m.id, "approve")}
                className="bg-[#22c55e] text-black rounded px-3 py-1.5 text-xs font-medium hover:brightness-110">
                Approve
              </button>
              <button onClick={() => act(m.id, "reject")}
                className="bg-zinc-800 rounded px-3 py-1.5 text-xs hover:bg-red-900/60">
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
