import { useEffect, useState } from "react";
import { api } from "../api";
import type { TelegramSettingsData } from "../types";

const NOTIFICATION_TYPES = ["alerts", "meetings", "new_leads", "daily_summary", "errors"];
const LEVELS = ["info", "warning", "critical"];

export default function TelegramSettings() {
  const [settings, setSettings] = useState<TelegramSettingsData>({
    bot_token: "",
    chat_id: "",
    enabled: false,
    notification_types: [],
    level: "info",
  });
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [testing, setTesting] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api<TelegramSettingsData>("/telegram/settings")
      .then((d) => { setSettings(d); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  async function save() {
    try {
      await api("/telegram/settings", { method: "POST", body: JSON.stringify(settings) });
      setMsg("Settings saved");
      setError("");
    } catch (e: any) { setError(e.message); }
  }

  async function testConnection() {
    setTesting(true);
    try {
      await api("/telegram/test", { method: "POST" });
      setMsg("Test message sent");
      setError("");
    } catch (e: any) { setError(e.message); }
    setTesting(false);
  }

  function toggleType(t: string) {
    setSettings((s) => ({
      ...s,
      notification_types: s.notification_types.includes(t)
        ? s.notification_types.filter((x) => x !== t)
        : [...s.notification_types, t],
    }));
  }

  if (!loaded) return <div className="w-full max-w-7xl mx-auto text-slate-400">loading…</div>;

  return (
    <div className="w-full max-w-3xl mx-auto space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-semibold text-slate-900">Telegram Settings</h1>
      </div>

      {error && <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">{error}</div>}
      {msg && <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-2.5 text-sm text-emerald-700">{msg}</div>}

      <div className="panel space-y-5">
        <div>
          <label className="panel-title">Bot Token</label>
          <input
            className="input w-full mt-1"
            type="password"
            placeholder="123456:ABC-..."
            value={settings.bot_token}
            onChange={(e) => setSettings((s) => ({ ...s, bot_token: e.target.value }))}
          />
        </div>

        <div>
          <label className="panel-title">Chat ID</label>
          <input
            className="input w-full mt-1"
            placeholder="-1001234567890"
            value={settings.chat_id}
            onChange={(e) => setSettings((s) => ({ ...s, chat_id: e.target.value }))}
          />
        </div>

        <div className="flex items-center gap-3">
          <label className="panel-title mb-0">Enabled</label>
          <button
            className={`w-10 h-5 rounded-full transition-colors relative ${settings.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
            onClick={() => setSettings((s) => ({ ...s, enabled: !s.enabled }))}
          >
            <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${settings.enabled ? "left-5" : "left-0.5"}`} />
          </button>
        </div>

        <div>
          <label className="panel-title">Notification Types</label>
          <div className="flex flex-wrap gap-2 mt-1">
            {NOTIFICATION_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${settings.notification_types.includes(t) ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="panel-title">Level</label>
          <select
            className="select mt-1"
            value={settings.level}
            onChange={(e) => setSettings((s) => ({ ...s, level: e.target.value }))}
          >
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>

        <div className="flex gap-2 pt-2">
          <button className="btn" onClick={save}>Save Settings</button>
          <button className="btn btn-ghost" onClick={testConnection} disabled={testing}>
            {testing ? "Sending…" : "⚡ Test Connection"}
          </button>
        </div>
      </div>
    </div>
  );
}
