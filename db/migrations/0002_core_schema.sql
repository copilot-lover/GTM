-- Phase 1: core operational schema.
-- All enums snake_case. All tenant tables workspace-scoped.

CREATE TABLE companies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    business_name text NOT NULL,
    website text,
    phone text,
    address text,
    city text,
    state text,
    zip text,
    vertical text,
    employee_estimate int,
    number_of_locations int,
    owner_name text,
    owner_operator_confidence int CHECK (owner_operator_confidence BETWEEN 0 AND 100),
    google_rating numeric(2,1),
    review_count int,
    tech_signals jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text,
    source_url text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_companies_dedupe
    ON companies (workspace_id, lower(business_name), coalesce(city,''), coalesce(state,''));

CREATE TABLE contacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name text,
    title text,
    email citext,
    email_verification_status text NOT NULL DEFAULT 'unknown'
        CHECK (email_verification_status IN ('unknown','syntax_ok','dns_ok','verified','failed')),
    email_verification_confidence int,
    email_verification_provider text,
    email_verified_at timestamptz,
    phone text,
    line_type text,
    is_decision_maker boolean NOT NULL DEFAULT false,
    source_url text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    opt_out_flag boolean NOT NULL DEFAULT false
);

-- Lead lifecycle state machine (spec §6.4).
CREATE TABLE leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id uuid REFERENCES contacts(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'new'
        CHECK (status IN ('new','enriching','qualified','signal_holding','outreach_ready',
                          'contacted','responded','qualified_conversation','meeting_booked',
                          'meeting_held','proposal','won','lost','rejected','do_not_call',
                          'unreachable','archived')),
    outcome text CHECK (outcome IN ('new','in_progress','completed','disqualified')),
    fit_status text NOT NULL DEFAULT 'pending'
        CHECK (fit_status IN ('pending','qualified','borderline','rejected_too_large',
                              'rejected_not_relevant','rejected_unclear')),
    lead_score int CHECK (lead_score BETWEEN 0 AND 10),
    priority_score int CHECK (priority_score BETWEEN 0 AND 100),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    website_findings jsonb NOT NULL DEFAULT '{}'::jsonb,
    recommended_offer text,
    primary_pain text,
    secondary_pain text,
    personalization_notes jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    source text,
    source_url text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    compliance jsonb NOT NULL DEFAULT '{"consent_status":"none","opt_out_flag":false}'::jsonb,
    rejection_reason text,
    next_action_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_leads_workspace_status ON leads (workspace_id, status);
CREATE INDEX ix_leads_priority ON leads (workspace_id, priority_score DESC);

CREATE TABLE activities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    type text NOT NULL CHECK (type IN ('email','call','sms','ai_action','meeting','note','system')),
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor text NOT NULL CHECK (actor IN ('human','agent','system')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_activities_lead ON activities (lead_id, created_at DESC);

CREATE TABLE campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    vertical text,
    geo jsonb NOT NULL DEFAULT '{}'::jsonb,
    channel_policy text NOT NULL DEFAULT 'email_phone' CHECK (channel_policy IN ('email_only','email_phone')),
    cadence_config jsonb NOT NULL DEFAULT '{"offsets_days":[0,3,7,14]}'::jsonb,
    daily_cap int NOT NULL DEFAULT 20,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    channel text NOT NULL CHECK (channel IN ('email','sms')),
    direction text NOT NULL CHECK (direction IN ('outbound','inbound')),
    subject text,
    body_text text,
    body_html text,
    variant_id text,
    feature_tags jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'drafted'
        CHECK (status IN ('drafted','pending_approval','approved','scheduled','sent',
                          'delivered','opened','replied','bounced','failed','rejected')),
    sequence_step int NOT NULL DEFAULT 0,
    idempotency_key text UNIQUE,
    provider_message_id text UNIQUE,
    thread_id text,
    approved_by uuid REFERENCES users(id),
    approved_at timestamptz,
    scheduled_send_at timestamptz,
    sent_at timestamptz,
    error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_messages_lead ON messages (lead_id, created_at DESC);
CREATE INDEX ix_messages_approval ON messages (workspace_id, status) WHERE status = 'pending_approval';

CREATE TABLE email_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (event_type IN ('delivered','open','click','reply','bounce','complaint')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ix_email_events_message ON email_events (message_id);

CREATE TABLE calling_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','paused','completed')),
    filters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz
);

CREATE TABLE session_leads (
    session_id uuid NOT NULL REFERENCES calling_sessions(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    queue_order int NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, lead_id)
);

CREATE TABLE calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
    session_id uuid REFERENCES calling_sessions(id) ON DELETE SET NULL,
    twilio_call_sid text UNIQUE,
    direction text NOT NULL CHECK (direction IN ('outbound','inbound')),
    from_number text,
    to_number text,
    duration_seconds int NOT NULL DEFAULT 0,
    recording_url text,
    transcript text,
    disposition text CHECK (disposition IN ('connected_dm','connected_gk','connected_other','voicemail',
        'busy','no_answer','bad_number','not_interested','do_not_call','callback_requested',
        'appointment_set','dialed')),
    notes text,
    called_at timestamptz,
    edited_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_calls_workspace ON calls (workspace_id, called_at DESC);

CREATE TABLE meetings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    scheduled_at timestamptz NOT NULL,
    tz text NOT NULL DEFAULT 'America/New_York',
    status text NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked','held','no_show','rescheduled','cancelled')),
    source text NOT NULL DEFAULT 'human' CHECK (source IN ('agent','human')),
    calendar_link text,
    brief text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE opportunities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    value_mrr numeric(10,2),
    value_setup numeric(10,2),
    stage text NOT NULL DEFAULT 'open' CHECK (stage IN ('open','won','lost')),
    probability int CHECK (probability BETWEEN 0 AND 100),
    expected_close date,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    version text NOT NULL DEFAULT '1.0',
    model_tier text NOT NULL DEFAULT 'cheap' CHECK (model_tier IN ('cheap','frontier')),
    config jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE agent_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_name text NOT NULL,
    trigger text NOT NULL,
    input_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','success','failed','review')),
    confidence numeric(4,3),
    tokens_in int NOT NULL DEFAULT 0,
    tokens_out int NOT NULL DEFAULT 0,
    cost_usd numeric(10,6) NOT NULL DEFAULT 0,
    latency_ms int,
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX ix_agent_runs_started ON agent_runs (started_at DESC);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    type text NOT NULL,
    due_at timestamptz,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','cancelled')),
    assigned_to uuid REFERENCES users(id),
    created_by text NOT NULL DEFAULT 'system' CHECK (created_by IN ('agent','human','system')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    type text NOT NULL CHECK (type IN ('hiring','review_cluster','site_change','other')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    score int NOT NULL DEFAULT 0,
    detected_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','consumed','expired'))
);

-- Hiring-intent subsystem (isolated; EMAIL ONLY per spec §8).
CREATE TABLE job_postings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    company_id uuid REFERENCES companies(id) ON DELETE SET NULL,
    source text NOT NULL,
    source_url text NOT NULL,
    external_job_id text NOT NULL,
    title text NOT NULL,
    description_raw text,
    location text,
    posted_at timestamptz,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    intent_score int CHECK (intent_score BETWEEN 0 AND 100),
    intent_category text CHECK (intent_category IN ('very_high','high','medium','low','ignored')),
    relevant_responsibilities jsonb NOT NULL DEFAULT '[]'::jsonb,
    recommended_offer text,
    confidence numeric(4,3),
    qualification_rationale text,
    status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','qualified','nurture','rejected','duplicate')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, external_job_id)
);

CREATE TABLE hiring_intent_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    posting_id uuid NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    company_id uuid REFERENCES companies(id) ON DELETE SET NULL,
    contact_id uuid REFERENCES contacts(id) ON DELETE SET NULL,
    -- NOTE: no phone/call path exists from this queue anywhere in the codebase.
    status text NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready','approved','sent','follow_up_1','follow_up_2',
                          'replied','meeting','won','lost','expired','rejected')),
    drafted_message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
    approved_by uuid REFERENCES users(id),
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, posting_id)
);

CREATE TABLE suppression (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    scope text NOT NULL CHECK (scope IN ('email','phone','company','global')),
    value text NOT NULL,
    reason text NOT NULL,
    source_event text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, scope, value)
);

CREATE TABLE audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid,
    actor_type text NOT NULL CHECK (actor_type IN ('user','agent','system')),
    actor_id text,
    action text NOT NULL,
    entity text NOT NULL,
    entity_id text,
    before_state jsonb,
    after_state jsonb,
    ip text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_created ON audit_log (created_at DESC);

CREATE TABLE saved_filters (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name text NOT NULL,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, owner_user_id, name)
);

ALTER TABLE users ADD COLUMN display_name text;
