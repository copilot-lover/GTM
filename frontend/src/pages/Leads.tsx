import { useEffect, useState } from "react";
import { api } from "../api";

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

  if (error) return <p className="text-red-400">{error}</p>;

  return (
    <div className="space-y-4">
      <div className="flex gap-3 items-center">
        <h1 className="text-lg font-semibold">Leads</h1>
        <input
          placeholder="search…" value={q} onChange={(e) => setQ(e.target.value)}
          className="bg-black/40 border border-zinc-700 rounded px-3 py-1.5 text-sm w-64"
        />
        <select value={status} onChange={(e) => setStatus(e.target.value)}
                className="bg-black/40 border border-zinc-700 rounded px-2 py-1.5 text-sm">
          <option value="">all statuses</option>
          {["new","enriching","qualified","outreach_ready","contacted","responded",
            "meeting_booked","proposal","won","lost","rejected","do_not_call"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <span className="mono text-xs text-zinc-500">{total} total</span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-zinc-500 border-b border-zinc-800">
          <tr>
            <th className="py-2">Business</th><th>City</th><th>Score</th>
            <th>Tier</th><th>Status</th><th>Pain</th><th>Offer</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {items.map((l) => (
            <tr key={l.id} className="hover:bg-zinc-800/30">
              <td className="py-2">
                <a href={`/leads/${l.id}`} className="text-[#22c55e] hover:underline">
                  {l.business_name}
                </a>
              </td>
              <td>{[l.city, l.state].filter(Boolean).join(", ")}</td>
              <td className="mono">{l.lead_score ?? "—"}</td>
              <td className="mono">{l.priority_tier ?? "—"}</td>
              <td>{l.status}</td>
              <td className="text-zinc-500">{l.primary_pain ?? "—"}</td>
              <td className="text-zinc-500">{l.recommended_offer ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p className="text-zinc-600">no results</p>}
    </div>
  );
}
