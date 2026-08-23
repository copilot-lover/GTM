import { useEffect, useState } from "react";
import { api } from "../api";

export default function HiringIntent() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/hiring-intent/queue").then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-400">{error}</p>;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">
        Hiring Intent <span className="text-xs text-zinc-500">(email only)</span>
      </h1>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-zinc-500 border-b border-zinc-800">
          <tr>
            <th className="py-2">Company</th><th>Role</th><th>Posted</th>
            <th>Score</th><th>Status</th><th>Evidence</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {items.map((q) => (
            <tr key={q.id} className="hover:bg-zinc-800/30 align-top">
              <td className="py-2">{q.business_name ?? "—"}</td>
              <td>{q.title}</td>
              <td className="mono text-xs">
                {q.posted_at ? `${Math.round((Date.now() - new Date(q.posted_at).getTime()) / 86400000)}d ago` : "—"}
              </td>
              <td className={`mono ${q.intent_score >= 90 ? "text-[#22c55e]" : ""}`}>
                {q.intent_score} {q.intent_category}
              </td>
              <td>{q.status}</td>
              <td className="max-w-md text-xs text-zinc-500">
                <a href={q.source_url} className="underline" target="_blank" rel="noreferrer">
                  posting
                </a>
                {" — "}
                {(q.qualification_rationale ?? "").slice(0, 140)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p className="text-zinc-600 text-sm">queue empty</p>}
    </div>
  );
}
