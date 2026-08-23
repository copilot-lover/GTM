import { useEffect, useRef, useState } from "react";
import { Device } from "@twilio/voice-sdk";
import { api } from "../api";

const DISPOSITIONS = [
  "connected_dm", "connected_gk", "connected_other", "voicemail", "busy",
  "no_answer", "bad_number", "not_interested", "do_not_call",
  "callback_requested", "appointment_set",
];

export default function Dialer() {
  const [queue, setQueue] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [callState, setCallState] = useState<"idle" | "connecting" | "live">("idle");
  const [kpis, setKpis] = useState<any>(null);
  const [activeLead, setActiveLead] = useState<any>(null);
  const [activeCallId, setActiveCallId] = useState<string>("");
  const deviceRef = useRef<Device | null>(null);
  const activeCallRef = useRef<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/dialer/sessions").then((d) => setSessions(d.items)).catch(() => {});
    api("/dialer/kpis").then(setKpis).catch(() => {});
  }, []);

  async function openSession(id: string) {
    setSessionId(id);
    const d = await api(`/dialer/sessions/${id}/queue`);
    setQueue(d.items);
  }

  async function connectBrowser() {
    try {
      setError("");
      const { token } = await api("/dialer/token");
      const device = new Device(token);
      device.on("error", (e: any) => {
        setError(String(e?.message ?? e));
        setCallState("idle");
      });
      await device.register();
      deviceRef.current = device;
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function call(lead: any) {
    if (!deviceRef.current) {
      setError("connect your browser audio first");
      return;
    }
    try {
      setError("");
      setCallState("connecting");
      // Click-to-call via API — server enforces timezone window + suppression.
      const res = await api("/dialer/calls", {
        method: "POST",
        body: JSON.stringify({
          lead_id: lead.lead_id,
          to_number: lead.phone,
          operator_endpoint: `${location.origin}/api/dialer/twilio-webhook`,
          session_id: sessionId,
        }),
      });
      setActiveCallId(res.call_id);
      setActiveLead(lead);
      setCallState("live");
    } catch (e: any) {
      setError(e.message);
      setCallState("idle");
    }
  }

  async function disposition(d: string) {
    if (!activeCallId) return;
    try {
      await api(`/dialer/calls/${activeCallId}/disposition`, {
        method: "POST",
        body: JSON.stringify({ disposition: d }),
      });
    } catch (e: any) {
      setError(e.message);
    }
    setCallState("idle");
    setActiveCallId("");
    setActiveLead(null);
    if (sessionId) openSession(sessionId);
  }

  async function hangup() {
    activeCallRef.current?.disconnect?.();
    setCallState("idle");
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-lg font-semibold">Session Dialer</h1>
        {kpis && (
          <span className="mono text-xs text-zinc-500">
            today: {kpis.calls_today} calls ·{" "}
            {Math.round((kpis.connection_rate_today ?? 0) * 100)}% connect
          </span>
        )}
      </div>

      <div className="flex gap-2 items-center">
        <select
          value={sessionId}
          onChange={(e) => openSession(e.target.value)}
          className="bg-black/40 border border-zinc-700 rounded px-2 py-1.5 text-sm"
        >
          <option value="">— choose session —</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.queue_size})
            </option>
          ))}
        </select>
        <button
          onClick={connectBrowser}
          className={`rounded px-3 py-1.5 text-xs ${
            deviceRef.current ? "bg-[#22c55e]/20 text-[#22c55e]" : "bg-zinc-800 hover:bg-zinc-700"
          }`}
        >
          {deviceRef.current ? "browser connected ✓" : "connect browser audio"}
        </button>
        {callState !== "idle" && (
          <span className="mono text-xs text-[#22c55e] animate-pulse">● {callState}</span>
        )}
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {callState === "live" && activeLead && (
        <div className="bg-[#14161b] border border-[#22c55e]/40 rounded p-4 space-y-3">
          <div className="flex justify-between">
            <span className="font-medium">
              On call: {activeLead.business_name} ({activeLead.phone})
            </span>
            <button onClick={hangup} className="bg-red-900/70 text-red-100 rounded px-3 py-1 text-xs">
              Hang up
            </button>
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {DISPOSITIONS.map((d) => (
              <button
                key={d}
                onClick={() => disposition(d)}
                className={`rounded px-2.5 py-1 text-xs ${
                  d === "do_not_call"
                    ? "bg-red-900/60 text-red-200 hover:bg-red-800"
                    : d === "appointment_set"
                      ? "bg-[#22c55e]/20 text-[#22c55e] hover:bg-[#22c55e]/30"
                      : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
      )}

      <table className="w-full text-sm">
        <thead className="text-left text-xs text-zinc-500 border-b border-zinc-800">
          <tr>
            <th className="py-2">Business</th><th>Phone</th><th>Pri</th>
            <th>Last disposition</th><th></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {queue.map((q) => (
            <tr key={q.lead_id} className="hover:bg-zinc-800/30">
              <td className="py-2">{q.business_name}</td>
              <td className="mono">{q.phone ?? "—"}</td>
              <td className="mono">{q.priority_score ?? "—"}</td>
              <td>{q.last_disposition ?? "—"}</td>
              <td>
                <button
                  disabled={!q.phone || callState !== "idle"}
                  onClick={() => call(q)}
                  className="bg-[#22c55e]/20 text-[#22c55e] rounded px-3 py-1 text-xs disabled:opacity-30"
                >
                  Call
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sessionId && queue.length === 0 && <p className="text-zinc-600 text-sm">queue empty</p>}
    </div>
  );
}
