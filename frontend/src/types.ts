export interface SystemHealthComponent {
  status: "healthy" | "degraded" | "down" | "unknown";
  label: string;
}

export interface TodayStats {
  capacity: number;
  sent: number;
  queued: number;
  followups_due: number;
}

export interface PipelineStage {
  name: string;
  count: number;
  health: "healthy" | "degraded" | "down" | "unknown";
}

export interface ControlPlaneOverview {
  systems: Record<string, SystemHealthComponent>;
  today: TodayStats;
  pipeline: PipelineStage[];
  actions: {
    paused: boolean;
  };
}

export interface LeadQueueItem {
  id: string;
  business_name: string;
  city?: string;
  state?: string;
  opportunity_score: number;
  priority_tier: string;
  signal_type: string;
  signal_age_days: number;
  decision_maker?: string;
  email_status: string;
  recommended_action: string;
}

export interface Signal {
  id: string;
  business_name: string;
  role_category: string;
  score: number;
  freshness: string;
  posted_age: string;
  status: string;
  source_url: string;
}

export interface Provider {
  name: string;
  quota: number;
  used: number;
  remaining: number;
  reset_date: string;
  success_rate: number;
  circuit_breaker: "closed" | "open" | "half_open";
}

export interface Mailbox {
  email: string;
  domain: string;
  health_score: number;
  health_state: string;
  sent: number;
  limit: number;
  bounce_rate: number;
  reply_rate: number;
  last_send?: string;
}

export interface AlertItem {
  id: string;
  severity: "critical" | "warning" | "info";
  source: string;
  message: string;
  entity: string;
  created_at: string;
  status: "open" | "acknowledged" | "resolved";
}

export interface AuditEntry {
  date: string;
  score: number;
  summary: string;
}

export interface AuditReport {
  latest: AuditEntry | null;
  history: AuditEntry[];
}

export interface TelegramSettingsData {
  bot_token: string;
  chat_id: string;
  enabled: boolean;
  notification_types: string[];
  level: string;
}

export interface GtmAgent {
  agent: string;
  capabilities?: string[];
  cannot_send?: boolean;
  task_type?: string | null;
  pool?: string | null;
  schedule_seconds?: number | null;
  enabled?: boolean | null;
  last_run?: string | null;
  next_run?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  avg_latency_ms?: number | null;
  tokens_24h?: number | null;
  runs_24h?: number | null;
  successes_24h?: number | null;
  failures_24h?: number | null;
}

export interface AgentRun {
  id: string;
  trigger?: string | null;
  status?: string | null;
  latency_ms?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface SendDecision {
  allowed: boolean;
  reasons?: string[];
  checks?: { name: string; passed: boolean; detail: string }[];
}

export interface LeadWhyContribution {
  component?: string;
  value?: unknown;
  label?: string;
  points?: number;
  signal_score?: number;
  age_days?: number;
}

export interface LeadWhy {
  score: number | null;
  priority: number | null;
  components?: { contributions?: LeadWhyContribution[] };
  contributions?: LeadWhyContribution[];
}
