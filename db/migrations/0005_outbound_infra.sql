-- Outbound infrastructure: sending domains, mailboxes, sequences,
-- the outbound send queue, and global kill-switch flags.

CREATE TABLE sending_domains (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    domain text NOT NULL UNIQUE,
    provider text NOT NULL DEFAULT 'smtp',
    status text NOT NULL DEFAULT 'unverified'
        CHECK (status IN ('active','paused','unverified')),
    dns_status jsonb NOT NULL DEFAULT '{}'::jsonb,
    daily_cap int NOT NULL DEFAULT 600,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mailboxes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    domain_id uuid REFERENCES sending_domains(id) ON DELETE SET NULL,
    email citext NOT NULL UNIQUE,
    provider text NOT NULL DEFAULT 'smtp',
    display_name text,
    status text NOT NULL DEFAULT 'setup'
        CHECK (status IN ('ready','paused','error','setup')),
    health_score int NOT NULL DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
    health_state text NOT NULL DEFAULT 'healthy'
        CHECK (health_state IN ('healthy','normal','reduced','restricted','paused')),
    daily_send_limit int NOT NULL DEFAULT 30,
    sent_today int NOT NULL DEFAULT 0,
    sent_today_date date,
    timezone text NOT NULL DEFAULT 'America/New_York',
    window_start time NOT NULL DEFAULT '08:30',
    window_end time NOT NULL DEFAULT '16:30',
    credentials jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_send_at timestamptz,
    last_health_check timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mailbox_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mailbox_id uuid NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
    event_type text NOT NULL
        CHECK (event_type IN ('auth_check','send','bounce','complaint','reply',
                              'health_check','pause','resume','error')),
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_mailbox_events_mailbox ON mailbox_events (mailbox_id, created_at DESC);

CREATE TABLE sequences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    steps_config jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','paused','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sequence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id uuid NOT NULL REFERENCES sequences(id) ON DELETE CASCADE,
    step_no int NOT NULL,
    offset_days int NOT NULL DEFAULT 0,
    angle text,
    subject_template text,
    body_template text,
    UNIQUE (sequence_id, step_no)
);

CREATE TABLE outbound_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    sequence_id uuid REFERENCES sequences(id) ON DELETE SET NULL,
    sequence_step_id uuid REFERENCES sequence_steps(id) ON DELETE SET NULL,
    kind text NOT NULL DEFAULT 'initial' CHECK (kind IN ('initial','followup')),
    priority int NOT NULL DEFAULT 3 CHECK (priority BETWEEN 0 AND 5),
    eligible_at timestamptz NOT NULL DEFAULT now(),
    deadline timestamptz,
    assigned_mailbox_id uuid REFERENCES mailboxes(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('drafted','queued','scheduled','claimed','sent',
                          'failed','cancelled')),
    attempt_count int NOT NULL DEFAULT 0,
    message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
    shadow boolean NOT NULL DEFAULT false,
    idempotency_key text UNIQUE,
    scheduled_slot_at timestamptz,
    sent_at timestamptz,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_outbound_messages_due ON outbound_messages (status, eligible_at);
CREATE INDEX ix_outbound_messages_workspace ON outbound_messages (workspace_id, status);
CREATE INDEX ix_outbound_messages_mailbox ON outbound_messages (assigned_mailbox_id, status);

CREATE TABLE system_flags (
    key text PRIMARY KEY,
    value jsonb NOT NULL DEFAULT 'null'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
);
