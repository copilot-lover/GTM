import { useEffect, useState } from "react";
import { api } from "../api";
import type { Mailbox } from "../types";

function HealthBadge({ score, state }: { score: number; state: string }) {
  const cls = score >= 80 ? "bg-emerald-100 text-emerald-800"
    : score >= 50 ? "bg-amber-100 text-amber-800"
    : "bg-red-100 text-red-700";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{state} ({score})</span>;
}

function SendBar({ sent, limit }: { sent: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((sent / limit) * 100)) : 0;
  const color = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <span className="mono text-xs text-slate-600">{sent}/{limit}</span>
      <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function MailboxManager() {
  const [items, setItems] = useState<Mailbox[]>([]);
  const [error, setError] = useState("");
  const [showAddMailbox, setShowAddMailbox] = useState(false);
  const [showAddDomain, setShowAddDomain] = useState(false);

  useEffect(() => {
    api<Mailbox[]>("/control-plane/mailboxes")
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e: any) => setError(e.message));
  }, []);

  const grouped = items.reduce<Record<string, Mailbox[]>>((acc, m) => {
    (acc[m.domain] ??= []).push(m);
    return acc;
  }, {});

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Mailboxes</h1>
        <span className="mono text-xs text-slate-400">{items.length} total</span>
        <div className="ml-auto flex gap-2">
          <button className="btn" onClick={() => setShowAddMailbox(true)}>+ Add Mailbox</button>
          <button className="btn btn-ghost" onClick={() => setShowAddDomain(true)}>+ Add Domain</button>
        </div>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {showAddMailbox && (
        <div className="panel space-y-3">
          <div className="panel-title">Add Mailbox</div>
          <div className="flex gap-2">
            <input className="input flex-1" placeholder="user@domain.com" />
            <button className="btn btn-green" onClick={() => setShowAddMailbox(false)}>Save</button>
            <button className="btn btn-ghost" onClick={() => setShowAddMailbox(false)}>Cancel</button>
          </div>
        </div>
      )}

      {showAddDomain && (
        <div className="panel space-y-3">
          <div className="panel-title">Add Domain</div>
          <div className="flex gap-2">
            <input className="input flex-1" placeholder="example.com" />
            <button className="btn btn-green" onClick={() => setShowAddDomain(false)}>Save</button>
            <button className="btn btn-ghost" onClick={() => setShowAddDomain(false)}>Cancel</button>
          </div>
        </div>
      )}

      {Object.entries(grouped).map(([domain, mailboxes]) => (
        <div key={domain} className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/80">
            <span className="text-sm font-semibold text-slate-900">{domain}</span>
            <span className="ml-2 text-xs text-slate-400">{mailboxes.length} mailbox{mailboxes.length !== 1 ? "es" : ""}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="tbl min-w-[800px]">
              <thead>
                <tr>
                  <th className="w-[25%]">Email</th>
                  <th className="w-[15%]">Health</th>
                  <th className="w-[15%]">Sent / Limit</th>
                  <th className="w-[10%]">Bounce Rate</th>
                  <th className="w-[10%]">Reply Rate</th>
                  <th className="w-[15%]">Last Send</th>
                </tr>
              </thead>
              <tbody>
                {mailboxes.map((m) => (
                  <tr key={m.email}>
                    <td className="font-medium text-slate-900 text-sm">{m.email}</td>
                    <td><HealthBadge score={m.health_score} state={m.health_state} /></td>
                    <td><SendBar sent={m.sent} limit={m.limit} /></td>
                    <td className="mono text-xs">{(m.bounce_rate * 100).toFixed(1)}%</td>
                    <td className="mono text-xs">{(m.reply_rate * 100).toFixed(1)}%</td>
                    <td className="mono text-xs text-slate-500">{m.last_send ? new Date(m.last_send).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {items.length === 0 && <div className="panel text-center text-slate-400 py-10">no mailboxes configured</div>}
    </div>
  );
}
