-- 0008_gtm_agents.sql
-- GTM agent architecture add-on (spec v3):
--   * explicit GTM message lifecycle stage machine (structural send gate)
--   * independent QA runs with machine-readable findings
--   * intent event model for continuous re-evaluation
--   * scheduled agent runner
--   * agent run ledger extensions
--   * experiment isolation + copy contract columns on messages
-- Extends existing tables only; creates no duplicate queues/schedulers.

-- ---------------------------------------------------------------- lifecycle

ALTER TABLE messages ADD COLUMN gtm_stage text;
-- NULL = legacy/unmanaged row; managed outbound rows walk the GTM stage machine.
ALTER TABLE messages ADD CONSTRAINT ck_messages_gtm_stage CHECK (
    gtm_stage IS NULL OR gtm_stage IN (
        'DISCOVERED','QUALIFIED','INTENT_SCORED','RESEARCHED','COPY_GENERATED',
        'QA_PENDING','QA_PASSED','COMPLIANCE_PENDING','SEND_READY','SCHEDULED','SENT',
        'QA_FAILED','COMPLIANCE_FAILED','SUPPRESSED','HELD','EXPIRED','CANCELLED'));

CREATE TABLE message_stage_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    from_stage text,
    to_stage text NOT NULL,
    actor text NOT NULL DEFAULT 'system',
    reason text,
    qa_run_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_message_stage_events ON message_stage_events (message_id, created_at);

-- ---------------------------------------------------------------- QA runs

CREATE TABLE qa_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type text NOT NULL CHECK (object_type IN ('lead','research','copy','compliance')),
    object_id uuid NOT NULL,
    score numeric(5,2),
    status text NOT NULL CHECK (status IN ('passed','failed')),
    findings jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    failed_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
    attempt int NOT NULL DEFAULT 1,
    model text,
    model_version text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_qa_runs_object ON qa_runs (workspace_id, object_type, object_id, created_at DESC);

-- ---------------------------------------------------------------- intent events

CREATE TABLE intent_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid REFERENCES companies(id) ON DELETE CASCADE,
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    signal_id uuid,
    event_type text NOT NULL,          -- extensible registry, enforced in code not SQL
    source text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    processed boolean NOT NULL DEFAULT false,
    processed_at timestamptz
);
CREATE INDEX ix_intent_events_pending ON intent_events (processed, occurred_at);
CREATE INDEX ix_intent_events_company ON intent_events (company_id, occurred_at DESC);

-- ---------------------------------------------------------------- agent schedules

CREATE TABLE agent_schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    agent text NOT NULL CHECK (agent IN ('GTM_LEADS','GTM_INTENT','GTM_COPY',
                                         'GTM_QA','GTM_OUTBOUND','GTM_REPLIES')),
    task_type text NOT NULL,
    pool text NOT NULL DEFAULT 'ai',
    schedule_seconds int NOT NULL,
    priority int NOT NULL DEFAULT 3 CHECK (priority BETWEEN 0 AND 5),
    concurrency int NOT NULL DEFAULT 1,
    enabled boolean NOT NULL DEFAULT true,
    last_run timestamptz,
    next_run timestamptz NOT NULL DEFAULT now(),
    last_status text,
    last_error text,
    UNIQUE (agent, task_type)
);

-- ---------------------------------------------------------------- ledger extensions

ALTER TABLE agent_runs ADD COLUMN parent_run_id uuid REFERENCES agent_runs(id);
ALTER TABLE agent_runs ADD COLUMN provider text;
ALTER TABLE agent_runs ADD COLUMN model text;
ALTER TABLE agent_runs ADD COLUMN model_version text;

-- ---------------------------------------------------------------- copy contract + experiments

ALTER TABLE messages ADD COLUMN copy_input jsonb;              -- structured GTM_COPY input
ALTER TABLE messages ADD COLUMN claims jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE messages ADD COLUMN evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE messages ADD COLUMN experiment_id text;
ALTER TABLE messages ADD COLUMN prompt_version text;
ALTER TABLE messages ADD COLUMN copy_version text;
ALTER TABLE messages ADD COLUMN model_version text;
ALTER TABLE messages ADD COLUMN originating_mailbox_id uuid;   -- follow-up mailbox binding

-- intent score breakdown for the "Why this lead is hot" panel lives in
-- scores.components (existing table) — no new scoring store.
