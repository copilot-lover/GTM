import { useEffect, useState } from "react";
import { api } from "../api";

const STATUSES = ["new","enriching","qualified","outreach_ready","contacted","responded",
  "meeting_booked","proposal","won","lost","rejected","do_not_call"];

export default function Leads() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      const data = await api(`/leads?${params}`);
      setItems(data.items);
      setTotal(data.total);
    } catch (e: any) { setError(e.message); }
  }

  useEffect(() => { load(); }, [q, status]);

  return (
    <div className="gtm-page">
      <div className="gtm-toolbar">
        <h1>Leads</h1>
        <input className="gtm-input" placeholder="search…" value={q}
               onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
        <select className="gtm-select" value={status}
                onChange={(e) => setStatus(e.target.value)}>
          <option value="">all statuses</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <span className="gtm-count">{total} total</span>
      </div>

      {error && <div className="gtm-alert gtm-alert-red">{error}</div>}

      <table className="gtm-table">
        <thead>
          <tr>
            <th>Business</th><th>City</th><th>Score</th><th>Tier</th>
            <th>Status</th><th>Pain</th><th>Offer</th>
          </tr>
        </thead>
        <tbody>
          {items.map((l) => (
            <tr key={l.id}>
              <td>
                <a className="gtm-link" href={`/leads/${l.id}`}>{l.business_name}</a>
              </td>
              <td>{[l.city, l.state].filter(Boolean).join(", ")}</td>
              <td className="mono">{l.lead_score ?? "—"}</td>
              <td className="mono">{l.priority_tier ?? "—"}</td>
              <td>
                <span className={`gtm-chip gtm-chip-${
                  l.status === "responded" || l.status === "meeting_booked" ? "green"
                  : l.status === "rejected" || l.status === "do_not_call" ? "gray"
                  : "amber"}`}>
                  {l.status}
                </span>
              </td>
              <td className="gtm-muted">{l.primary_pain ?? "—"}</td>
              <td className="gtm-muted">{l.recommended_offer ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && (
        <div className="gtm-panel gtm-empty">no leads yet — run your first batch</div>
      )}
    </div>
  );
}
