import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";

interface LeadItem {
  id: string;
  business_name: string;
  vertical: string | null;
  city: string | null;
  state: string | null;
  lead_score: number | null;
  priority_tier: string | null;
  status: string;
  primary_pain: string | null;
  recommended_offer: string | null;
}

const STATUSES = ["new","enriching","qualified","signal_holding","outreach_ready","contacted",
  "responded","qualified_conversation","meeting_booked","meeting_held","proposal","won",
  "lost","rejected","do_not_call","unreachable","archived"];

export default function Leads() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<LeadItem[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState(searchParams.get("q") ?? "");
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
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Leads</h1>
        <input
          className="input w-64"
          placeholder="Search businesses…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search leads"
        />
        <select className="select" value={status}
                onChange={(e) => setStatus(e.target.value)}
                aria-label="Filter by status">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <span className="mono text-xs text-slate-400 ml-auto">{total} total</span>
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 shadow-sm bg-white">
        <table className="tbl min-w-[900px]">
          <thead>
            <tr>
              <th className="w-[26%]">Business</th>
              <th className="w-[13%]">Location</th>
              <th className="w-[8%] text-center">Score</th>
              <th className="w-[7%] text-center">Tier</th>
              <th className="w-[14%]">Status</th>
              <th className="w-[16%]">Pain</th>
              <th className="w-[16%]">Offer</th>
            </tr>
          </thead>
          <tbody>
            {items.map((l) => (
              <tr key={l.id}>
                <td>
                  <a className="text-blue-600 hover:text-blue-800 hover:underline font-medium transition-colors"
                     href={`/leads/${l.id}`}>
                    {l.business_name}
                  </a>
                  <div className="text-xs text-slate-400">{l.vertical ?? ""}</div>
                </td>
                <td className="whitespace-nowrap text-slate-600">
                  {[l.city, l.state].filter(Boolean).join(", ") || "—"}
                </td>
                <td className="mono text-center">{l.lead_score ?? "—"}</td>
                <td className="mono text-center">{l.priority_tier ?? "—"}</td>
                <td>
                  <span className={`badge badge-${l.status}`}>{l.status}</span>
                </td>
                <td className="text-slate-500">{l.primary_pain ?? "—"}</td>
                <td className="text-slate-500">{l.recommended_offer ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 && (
        <div className="panel text-center text-slate-400 py-10">
          no leads yet — run your first batch from the Agents page
        </div>
      )}
    </div>
  );
}
