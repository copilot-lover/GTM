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
    <div className="gtm-page">
      <div className="gtm-toolbar">
        <h1>Approvals</h1>
        <span className="gtm-pill">
          <span className="gtm-dot" /> {items.length} waiting
        </span>
      </div>

      {error && <div className="gtm-alert gtm-alert-red">{error}</div>}
      {items.length === 0 && (
        <div className="gtm-panel gtm-empty">nothing awaiting approval</div>
      )}

      <div className="space-y-4" style={{ maxWidth: 680 }}>
        {items.map((m) => (
          <div key={m.id} className="gtm-panel space-y-3">
            <div className="flex justify-between items-center">
              <span style={{ fontWeight: 600, fontSize: 15.5 }}>{m.business_name}</span>
              <span className="gtm-muted" style={{ fontSize: 12.5 }}>
                {m.city}, {m.state} · {m.primary_pain ?? "—"} → {m.recommended_offer ?? "—"}
              </span>
            </div>
            <div className="gtm-row-sub" style={{
              background: "#f8fafc", borderRadius: 12, padding: "14px 16px",
              fontSize: 14, whiteSpace: "pre-wrap", color: "#334155",
            }}>
              <span style={{ color: "#16a34a", fontWeight: 600 }}>{m.subject}</span>
              {"\n"}{m.body_text}
            </div>
            <div className="flex gap-2">
              <button className="gtm-btn gtm-btn-green"
                      onClick={() => act(m.id, "approve")}>
                Approve
              </button>
              <button className="gtm-btn gtm-btn-red"
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
