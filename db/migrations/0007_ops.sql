-- Ops layer: durable job queue, alert inbox, daily audit reports,
-- telegram notification settings.

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type text NOT NULL,
    pool text NOT NULL
        CHECK (pool IN ('discovery','enrichment','verification','ai',
                        'outbound','meeting')),
    priority int NOT NULL DEFAULT 3 CHECK (priority BETWEEN 0 AND 5),
    status text NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','RETRYING',
                          'CANCELLED','DEAD_LETTER')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    attempts int NOT NULL DEFAULT 0,
    max_attempts int NOT NULL DEFAULT 3,
    run_at timestamptz NOT NULL DEFAULT now(),
    provider text,
    idempotency_key text UNIQUE,
    error text,
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz
);
CREATE INDEX ix_jobs_claim ON jobs (pool, status, priority, run_at);

CREATE TABLE alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    severity text NOT NULL DEFAULT 'info'
        CHECK (severity IN ('critical','warning','attention','info')),
    source text,
    entity_type text,
    entity_id text,
    message text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','acknowledged','resolved')),
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE TABLE daily_audits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_date date NOT NULL UNIQUE,
    overall_score int,
    report jsonb NOT NULL DEFAULT '{}'::jsonb,
    report_md text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram_settings (
    id boolean PRIMARY KEY DEFAULT true CHECK (id = true),
    bot_token_encrypted text,
    chat_id text,
    enabled boolean NOT NULL DEFAULT false,
    notify_types jsonb NOT NULL DEFAULT '{}'::jsonb,
    level text NOT NULL DEFAULT 'important'
        CHECK (level IN ('all','important','critical')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
