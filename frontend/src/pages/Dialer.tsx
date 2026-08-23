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
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [activeCallObj, setActiveCallObj] = useState<any>(null);
  const deviceRef = useRef<Device | null>(null);
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
      // mic picker: enumerate inputs; permission prompt may be needed for labels
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        stopTracks();
        const devices = await navigator.mediaDevices.enumerateDevices();
        setMics(devices.filter((d) => d.kind === "audioinput"));
      } catch { /* enumeration without labels still lists devices */ }
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

  function stopTracks() {
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((s) => s.getTracks().forEach((t) => t.stop()))
      .catch(() => {});
  }

  async function pickMic(deviceId: string) {
    try {
      await deviceRef.current?.audio?.setInputDevice(deviceId);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    }
  }

  async function sendDigit(d: string) {
    if (activeCallObj) await activeCallObj.sendDigits(d);
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
      // attach the browser to the live call for DTMF
      try {
        const conn = await deviceRef.current?.connect?.({
          params: { To: res.call_sid },
        });
        setActiveCallObj(conn);
      } catch { /* conference join is best-effort; click-to-call still works */ }
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
    activeCallObj?.disconnect?.();
    setActiveCallObj(null);
    setCallState("idle");
    setActiveCallId("");
    setActiveLead(null);
    if (sessionId) openSession(sessionId);
  }

  function hangup() {
    activeCallObj?.disconnect?.();
    setActiveCallObj(null);
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
        {deviceRef.current && mics.length > 0 && (
          <select
            defaultValue=""
            onChange={(e) => pickMic(e.target.value)}
            className="bg-black/40 border border-zinc-700 rounded px-2 py-1.5 text-xs max-w-56"
          >
            <option value="">mic: default</option>
            {mics.map((m, i) => (
              <option key={m.deviceId} value={m.deviceId}>
                {m.label || `microphone ${i + 1}`}
              </option>
            ))}
          </select>
        )}
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

          {/* persistent DTMF keypad — visible from connecting through live */}
          <div className="flex items-center gap-4">
            <div className="grid grid-cols-3 gap-1.5 w-44">
              {["1","2","3","4","5","6","7","8","9","*","0","#"].map((d) => (
                <button key={d} onClick={() => sendDigit(d)}
                  className="mono bg-black/40 border border-zinc-700 rounded py-1.5 text-sm hover:bg-zinc-800">
                  {d}
                </button>
              ))}
            </div>
            <div className="text-xs text-zinc-500">DTMF<br />(live call)</div>
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
