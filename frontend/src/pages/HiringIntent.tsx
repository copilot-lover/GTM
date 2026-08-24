import { useEffect, useState } from "react";
import { api } from "../api";

export default function HiringIntent() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/hiring-intent/queue").then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1>Hiring Intent</h1>
        <span className="badge badge-pending_approval">email only</span>
        <span className="gtm-count">{items.length} in queue</span>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <table className="gtm-table">
        <thead>
          <tr>
            <th>Company</th><th>Role</th><th>Posted</th><th>Score</th>
            <th>Status</th><th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map((q) => (
            <tr key={q.id}>
              <td>{q.business_name ?? "—"}</td>
              <td>{q.title}</td>
              <td className="mono" style={{ fontSize: 12.5 }}>
                {q.posted_at
                  ? `${Math.round((Date.now() - new Date(q.posted_at).getTime()) / 86400000)}d ago`
                  : "—"}
              </td>
              <td>
                <span className={`gtm-chip ${q.intent_score >= 90 ? "gtm-chip-green" : "gtm-chip-gray"}`}>
                  {q.intent_score} {q.intent_category}
                </span>
              </td>
              <td>{q.status}</td>
              <td style={{ maxWidth: 380, fontSize: 12.5 }} className="gtm-muted">
                <a className="gtm-link" href={q.source_url} target="_blank" rel="noreferrer">
                  posting
                </a>
                {" — "}
                {(q.qualification_rationale ?? "").slice(0, 140)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && (
        <div className="gtm-panel gtm-empty">queue empty — ingest a posting to start</div>
      )}
    </div>
  );
}
