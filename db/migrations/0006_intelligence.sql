-- Intelligence layer: hiring signals, enrichment audit trail, verification
-- records, research reports, provider quota ledger, scores, experiments,
-- and watch subscriptions.

CREATE TABLE hiring_signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source text NOT NULL,
    source_job_id text,
    job_url text,
    title text,
    description text,
    role_category text
        CHECK (role_category IN ('receptionist','dispatcher','customer_service',
                                 'appointment_setter','call_center','scheduler',
                                 'service_coordinator','office_admin','sales','other')),
    intent_category text
        CHECK (intent_category IN ('relevant','irrelevant','high_value',
                                   'medium_value','low_value')),
    pain_hypothesis text,
    orbit_product_fit text,
    confidence numeric(4,3),
    signal_score int,
    freshness_multiplier numeric(3,2) NOT NULL DEFAULT 1.0,
    expires_at timestamptz,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','expired','consumed')),
    posted_at timestamptz,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_hiring_signals_dedupe
    ON hiring_signals (workspace_id, source, coalesce(source_job_id, job_url));

CREATE TABLE enrichments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid REFERENCES companies(id) ON DELETE CASCADE,
    contact_id uuid REFERENCES contacts(id) ON DELETE CASCADE,
    provider text NOT NULL,
    operation text NOT NULL,
    request jsonb NOT NULL DEFAULT '{}'::jsonb,
    response jsonb NOT NULL DEFAULT '{}'::jsonb,
    succeeded boolean NOT NULL DEFAULT false,
    cost_units numeric(10,4) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE email_verifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    contact_id uuid REFERENCES contacts(id) ON DELETE SET NULL,
    email citext NOT NULL,
    result text NOT NULL
        CHECK (result IN ('valid','invalid','accept_all','unknown','disposable',
                          'spam_trap','abuse','risky')),
    provider text,
    local_checks jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence numeric(4,3),
    checked_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_email_verifications_contact ON email_verifications (contact_id, checked_at DESC);

CREATE TABLE research_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    summary text,
    primary_problem text,
    reason_now text,
    recommended_offer text,
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_used text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE provider_usage (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    operation text NOT NULL,
    period text NOT NULL,
    quota int NOT NULL DEFAULT 0,
    used int NOT NULL DEFAULT 0,
    reserve_threshold int NOT NULL DEFAULT 20,
    cost numeric(10,4) NOT NULL DEFAULT 0,
    last_reset_at timestamptz,
    UNIQUE (provider, operation, period)
);

CREATE TABLE scores (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    score_type text NOT NULL CHECK (score_type IN ('opportunity','emv')),
    score int,
    components jsonb NOT NULL DEFAULT '{}'::jsonb,
    tier text CHECK (tier IN ('A+','A','B','C','D')),
    recommended_action text
        CHECK (recommended_action IN ('call_email_linkedin','email_call',
                                      'email_sequence','do_not_contact')),
    recommended_pitch text,
    primary_problem text,
    reason_now text,
    computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_scores_lead ON scores (lead_id, computed_at DESC);

CREATE TABLE experiments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    hypothesis text,
    dimension text
        CHECK (dimension IN ('subject','opening','cta','offer','signal_type',
                             'email_length','followup_timing','industry','segment')),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','paused','completed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE experiment_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id uuid NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    variant text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (experiment_id, lead_id)
);

CREATE TABLE watch_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kinds jsonb NOT NULL DEFAULT '["hiring","website_change","leadership"]'::jsonb,
    last_checked_at timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused')),
    created_at timestamptz NOT NULL DEFAULT now()
);
