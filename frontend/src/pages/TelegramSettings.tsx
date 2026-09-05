import { useEffect, useState } from "react";
import { api } from "../api";
import { PaperPlaneTilt, CheckCircle } from "@phosphor-icons/react";

type TgSettings = {
  bot_token: string | null; // masked from backend
  chat_id: string | null;
  enabled: boolean;
  notify_types: Record<string, boolean>;
  level: string;
};

const EVENT_TYPES: { key: string; label: string; desc: string }[] = [
  { key: "meeting_booked", label: "Meeting booked", desc: "Lead books a meeting" },
  { key: "positive_reply", label: "Positive reply", desc: "Warm reply lands in a mailbox" },
  { key: "hot_lead", label: "Hot lead", desc: "Lead crosses your intent threshold" },
  { key: "alert_critical", label: "Critical alerts", desc: "System breaks, domain down, provider exhausted" },
  { key: "alert_warning", label: "Warnings", desc: "Degraded systems, quota nearing limits" },
  { key: "daily_digest", label: "Daily digest", desc: "Morning GTM health summary" },
];

const LEVELS = [
  { value: "all", label: "All — every notified event" },
  { value: "important", label: "Important — meetings, replies, warnings" },
  { value: "critical", label: "Critical only — failures and booked meetings" },
];

export default function TelegramSettings() {
  const [settings, setSettings] = useState<TgSettings | null>(null);
  const [tokenValue, setTokenValue] = useState("");
  const [tokenEdited, setTokenEdited] = useState(false);
  const [chatId, setChatId] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api<TgSettings>("/telegram/settings")
      .then((d) => {
        setSettings(d);
        setChatId(d.chat_id ?? "");
        setTokenValue(""); // masked token not editable; blank = keep existing
        setLoaded(true);
      })
      .catch((e) => { setError(e.message); setLoaded(true); });
  }, []);

  async function save() {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        chat_id: chatId || null,
        enabled: settings?.enabled ?? false,
        notify_types: settings?.notify_types ?? {},
        level: settings?.level ?? "important",
      };
      if (tokenEdited && tokenValue.trim()) body.bot_token = tokenValue.trim();
      await api("/telegram/settings", { method: "POST", body: JSON.stringify(body) });
      setMsg("Saved");
      setError("");
      setTokenEdited(false);
      const d = await api<TgSettings>("/telegram/settings");
      setSettings(d);
    } catch (e: any) { setError(e.message); }
    setSaving(false);
  }

  async function testConnection() {
    setTesting(true);
    try {
      await api("/telegram/test", { method: "POST" });
      setMsg("Test message sent — check your chat");
      setError("");
    } catch (e: any) { setError(e.message); }
    setTesting(false);
  }

  if (!loaded) return <div className="w-full max-w-3xl mx-auto text-sm" style={{ color: "var(--ink-3)" }}>loading…</div>;

  const hasToken = !!settings?.bot_token;
  const enabled = settings?.enabled ?? false;

  return (
    <div className="w-full max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>Telegram</h1>
        <p className="text-sm mt-1" style={{ color: "var(--ink-3)" }}>
          Push notifications when something needs you — booked meetings, hot leads, system failures.
        </p>
      </div>

      {error && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--bad-deep)", borderColor: "#f2cfcf", background: "var(--bad-soft)" }}>{error}</div>}
      {msg && <div className="card px-4 py-2.5 text-sm" style={{ color: "var(--good-deep)", borderColor: "#d2e9de", background: "var(--good-soft)" }}>{msg}</div>}

      <div className="card px-5 py-4 flex items-center gap-4">
        <div className="flex-1">
          <div className="text-sm font-medium" style={{ color: "var(--ink)" }}>Notifications enabled</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
            Master switch — nothing is sent while off
          </div>
        </div>
        <button
          aria-label="Toggle notifications"
          className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${enabled ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
          onClick={() => setSettings((s) => s ? { ...s, enabled: !s.enabled } : s)}
        >
          <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${enabled ? "left-5" : "left-0.5"}`} />
        </button>
      </div>

      <div className="panel space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="panel-title mb-1">Bot token</label>
            <input
              className="input w-full"
              type="password"
              placeholder={hasToken ? "saved — enter new to replace" : "123456:ABC-..."}
              value={tokenValue}
              onChange={(e) => { setTokenValue(e.target.value); setTokenEdited(true); }}
            />
            {hasToken && (
              <p className="text-xs mt-1.5" style={{ color: "var(--ink-3)" }}>
                Current: <span className="mono">{settings.bot_token}</span>
              </p>
            )}
          </div>
          <div>
            <label className="panel-title mb-1">Chat ID</label>
            <input
              className="input w-full mono"
              placeholder="-1001234567890"
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
            />
            <p className="text-xs mt-1.5" style={{ color: "var(--ink-3)" }}>
              Message @userinfobot on Telegram to get your chat ID
            </p>
          </div>
        </div>

        <div>
          <label className="panel-title mb-1">Minimum level</label>
          <select
            className="select w-full sm:w-96"
            value={settings?.level ?? "important"}
            onChange={(e) => setSettings((s) => s ? { ...s, level: e.target.value } : s)}
          >
            {LEVELS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">What to notify on</div>
        <div className="divide-y" style={{ borderColor: "var(--line-soft)" }}>
          {EVENT_TYPES.map((t) => {
            const on = settings?.notify_types?.[t.key] ?? false;
            return (
              <label
                key={t.key}
                className="flex items-center gap-3 py-3 cursor-pointer"
              >
                <span
                  className="w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors"
                  style={on
                    ? { background: "var(--ink)", borderColor: "var(--ink)" }
                    : { background: "#fff", borderColor: "var(--ink-3)" }}
                >
                  {on && <CheckCircle size={12} weight="fill" color="#fff" />}
                </span>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={on}
                  onChange={() =>
                    setSettings((s) =>
                      s ? { ...s, notify_types: { ...s.notify_types, [t.key]: !on } } : s)
                  }
                />
                <span>
                  <span className="block text-sm font-medium" style={{ color: "var(--ink)" }}>{t.label}</span>
                  <span className="block text-xs" style={{ color: "var(--ink-3)" }}>{t.desc}</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="flex gap-2">
        <button className="btn" onClick={save} disabled={saving}>
          <PaperPlaneTilt size={14} weight="bold" /> {saving ? "Saving…" : "Save"}
        </button>
        <button className="btn btn-ghost" onClick={testConnection} disabled={testing || !hasToken}>
          {testing ? "Sending…" : "Send test message"}
        </button>
      </div>
      {!hasToken && (
        <p className="text-xs" style={{ color: "var(--ink-3)" }}>
          Save a bot token to enable the test message.
        </p>
      )}
    </div>
  );
}