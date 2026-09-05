import { useEffect, useState } from "react";
import { api } from "../api";
import { Lightning, ArrowsClockwise, PlayCircle } from "@phosphor-icons/react";

interface HiringIntentItem {
  id: string;
  business_name: string | null;
  title: string;
  posted_at: string | null;
  intent_score: number;
  intent_category: string;
  status: string;
  source_url: string;
  qualification_rationale: string | null;
  website: string | null;
}

function scoreBadge(score: number, category: string) {
  if (score >= 90) return <span className="badge badge-qualified">{score} · {category}</span>;
  if (score >= 70) return <span className="badge badge-enriching">{score} · {category}</span>;
  return <span className="badge badge-new">{score} · {category}</span>;
}

export default function HiringIntent() {
  const [items, setItems] = useState<HiringIntentItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  async function load() {
    try {
      const d = await api<{ items: HiringIntentItem[] }>("/hiring-intent/queue");
      setItems(d.items);
      setError("");
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function syncProviders() {
    setSyncing(true);
    try {
      await api("/hiring-intent/ingest-from-providers", { method: "POST", body: JSON.stringify({}) });
      await load();
    } catch (e: any) { setError(e.message); }
    setSyncing(false);
  }

  return (
    <div className="w-full max-w-7xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>Hiring Intent</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
            Contractors hiring receptionists and dispatchers — scored, email-only queue.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="mono text-sm tnum" style={{ color: "var(--ink-2)" }}>{items.length} in queue</span>
          <button className="btn btn-ghost" onClick={syncProviders} disabled={syncing}>
            <ArrowsClockwise size={14} weight="bold" className={syncing ? "animate-spin" : undefined} />
            {syncing ? "Syncing…" : "Sync job boards"}
          </button>
        </div>
      </div>

      {error && <div className="card px-4 py-2.5 text-sm" style={{ color: "#9f2f2d", borderColor: "#f5d5d4", background: "#fdf6f6" }}>{error}</div>}

      {loading ? (
        <div className="card py-16 text-center text-sm" style={{ color: "var(--ink-3)" }}>loading…</div>
      ) : items.length === 0 ? (
        <div className="card px-6 py-16 text-center">
          <Lightning size={32} className="mx-auto mb-3" style={{ color: "var(--ink-3)" }} />
          <p className="text-sm" style={{ color: "var(--ink-2)" }}>Queue empty — no hiring signals matched yet.</p>
          <button className="btn mt-4" onClick={syncProviders} disabled={syncing}>
            <PlayCircle size={14} weight="bold" /> {syncing ? "Syncing…" : "Sync job boards now"}
          </button>
        </div>
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>Company</th><th>Role</th><th>Posted</th><th>Score</th>
              <th>Status</th><th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {items.map((q) => (
              <tr key={q.id}>
                <td className="font-medium" style={{ color: "var(--ink)" }}>{q.business_name ?? "—"}</td>
                <td>{q.title}</td>
                <td className="mono text-xs">
                  {q.posted_at
                    ? `${Math.round((Date.now() - new Date(q.posted_at).getTime()) / 86400000)}d ago`
                    : "—"}
                </td>
                <td>{scoreBadge(q.intent_score, q.intent_category)}</td>
                <td><span className={`badge badge-${q.status}`}>{q.status}</span></td>
                <td style={{ maxWidth: 380 }}>
                  <a
                    className="text-xs font-medium underline-offset-2 hover:underline"
                    style={{ color: "var(--accent)" }}
                    href={q.source_url} target="_blank" rel="noreferrer"
                  >
                    posting
                  </a>
                  <span className="block text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
                    {(q.qualification_rationale ?? "").slice(0, 140)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}