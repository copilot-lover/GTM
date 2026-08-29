# Foundation Contracts

Authoritative reference for the outbound infrastructure, intelligence, and
ops layers added in migrations 0005–0007 and `backend/app/providers/`.
Later workstreams code against THIS document. Last verified: 0005–0007 apply
cleanly; suite green (`uv run pytest -q`, backend/).

## 1. Tables

### 0005_outbound_infra.sql

**sending_domains** — sending-domain pool (global when workspace_id IS NULL)
- id uuid PK DEFAULT gen_random_uuid()
- workspace_id uuid NULL → workspaces(id) ON DELETE CASCADE (NULL = global pool)
- domain text NOT NULL UNIQUE
- provider text NOT NULL DEFAULT 'smtp'
- status text CHECK ('active','paused','unverified') DEFAULT 'unverified'
- dns_status jsonb NOT NULL DEFAULT '{}' (keys spf/dkim/dmarc/mx, each {verified bool, details})
- daily_cap int NOT NULL DEFAULT 600
- created_at/updated_at timestamptz NOT NULL DEFAULT now()

**mailboxes**
- id uuid PK DEFAULT gen_random_uuid()
- workspace_id uuid NULL → workspaces(id) ON DELETE CASCADE
- domain_id uuid NULL → sending_domains(id) ON DELETE SET NULL
- email citext NOT NULL UNIQUE
- provider text NOT NULL DEFAULT 'smtp'
- display_name text
- status text CHECK ('ready','paused','error','setup') DEFAULT 'setup'
- health_score int DEFAULT 100 CHECK 0..100
- health_state text CHECK ('healthy','normal','reduced','restricted','paused') DEFAULT 'healthy'
- daily_send_limit int NOT NULL DEFAULT 30
- sent_today int NOT NULL DEFAULT 0; sent_today_date date
- timezone text NOT NULL DEFAULT 'America/New_York'
- window_start time DEFAULT '08:30'; window_end time DEFAULT '16:30'
- credentials jsonb NOT NULL DEFAULT '{}' — encrypted payload pointer or env-ref names ONLY, never plaintext secrets
- last_send_at timestamptz; last_health_check timestamptz
- created_at/updated_at timestamptz NOT NULL DEFAULT now()

**mailbox_events**
- id uuid PK; mailbox_id uuid NOT NULL → mailboxes(id) ON DELETE CASCADE
- event_type text CHECK ('auth_check','send','bounce','complaint','reply','health_check','pause','resume','error')
- metrics jsonb NOT NULL DEFAULT '{}'
- created_at timestamptz; INDEX ix_mailbox_events_mailbox (mailbox_id, created_at DESC)

**sequences**
- id uuid PK; workspace_id uuid NOT NULL → workspaces ON DELETE CASCADE
- name text NOT NULL; steps_config jsonb NOT NULL DEFAULT '[]' (array of {step, offset_days, angle})
- status text CHECK ('active','paused','archived') DEFAULT 'active'
- created_at/updated_at

**sequence_steps**
- id uuid PK; sequence_id uuid NOT NULL → sequences ON DELETE CASCADE
- step_no int NOT NULL; offset_days int NOT NULL DEFAULT 0; angle/subject_template/body_template text
- UNIQUE (sequence_id, step_no)

**outbound_messages**
- id uuid PK
- workspace_id uuid NOT NULL → workspaces CASCADE; lead_id uuid NOT NULL → leads CASCADE
- campaign_id uuid NULL → campaigns SET NULL; sequence_id uuid NULL → sequences SET NULL; sequence_step_id uuid NULL → sequence_steps SET NULL
- kind text CHECK ('initial','followup') DEFAULT 'initial'
- priority int CHECK 0..5 DEFAULT 3 (0 = most urgent)
- eligible_at timestamptz NOT NULL DEFAULT now(); deadline timestamptz
- assigned_mailbox_id uuid NULL → mailboxes SET NULL
- status text CHECK ('drafted','queued','scheduled','claimed','sent','failed','cancelled') DEFAULT 'queued'
- attempt_count int NOT NULL DEFAULT 0
- message_id uuid NULL → messages(id) SET NULL; shadow boolean NOT NULL DEFAULT false
- idempotency_key text UNIQUE
- scheduled_slot_at timestamptz; sent_at timestamptz; error text
- created_at/updated_at
- INDEXES: ix_outbound_messages_due (status, eligible_at); ix_outbound_messages_workspace (workspace_id, status); ix_outbound_messages_mailbox (assigned_mailbox_id, status)

**system_flags** — kill switches live here
- key text PK; value jsonb NOT NULL; updated_at timestamptz; updated_by text
- Known keys: pause_all_sending, pause_followups, pause_ai_replies,
  pause_hiring_campaigns, shadow_mode, approval_mode ('autonomous'|'approval'|'hybrid')

### 0006_intelligence.sql

**hiring_signals**
- id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE; company_id uuid NOT NULL → companies CASCADE
- source text NOT NULL; source_job_id text; job_url text; title/description text
- role_category text CHECK ('receptionist','dispatcher','customer_service','appointment_setter','call_center','scheduler','service_coordinator','office_admin','sales','other')
- intent_category text CHECK ('relevant','irrelevant','high_value','medium_value','low_value')
- pain_hypothesis/orbit_product_fit text; confidence numeric(4,3); signal_score int
- freshness_multiplier numeric(3,2) NOT NULL DEFAULT 1.0; expires_at timestamptz
- status text CHECK ('active','expired','consumed') DEFAULT 'active'
- posted_at timestamptz; discovered_at timestamptz NOT NULL DEFAULT now()
- UNIQUE INDEX uq_hiring_signals_dedupe (workspace_id, source, coalesce(source_job_id, job_url))

**enrichments** — audit trail of enrichment calls
- id uuid PK; workspace_id uuid NOT NULL → workspaces CASCADE
- company_id uuid NULL → companies CASCADE; contact_id uuid NULL → contacts CASCADE
- provider/operation text NOT NULL; request/response jsonb DEFAULT '{}'
- succeeded boolean NOT NULL DEFAULT false; cost_units numeric(10,4) DEFAULT 0; created_at

**email_verifications**
- id uuid PK; workspace_id uuid NOT NULL; contact_id uuid NULL → contacts SET NULL
- email citext NOT NULL
- result text CHECK ('valid','invalid','accept_all','unknown','disposable','spam_trap','abuse','risky')
- provider text; local_checks jsonb DEFAULT '{}'; confidence numeric(4,3)
- checked_at/created_at; INDEX ix_email_verifications_contact (contact_id, checked_at DESC)

**research_reports**
- id uuid PK; workspace_id NOT NULL; company_id uuid NOT NULL → companies CASCADE
- summary/primary_problem/reason_now/recommended_offer text
- evidence jsonb NOT NULL DEFAULT '[]' (items: {claim, source_ref, source_type}); model_used text; created_at

**provider_usage** — monthly quota ledger
- id uuid PK; provider/operation/period text NOT NULL (period = 'YYYY-MM')
- quota int DEFAULT 0; used int DEFAULT 0; reserve_threshold int DEFAULT 20; cost numeric(10,4) DEFAULT 0
- last_reset_at timestamptz; UNIQUE (provider, operation, period)

**scores**
- id uuid PK; workspace_id NOT NULL; lead_id uuid NOT NULL → leads CASCADE
- score_type text CHECK ('opportunity','emv'); score int; components jsonb DEFAULT '{}'
- tier text CHECK ('A+','A','B','C','D')
- recommended_action text CHECK ('call_email_linkedin','email_call','email_sequence','do_not_contact')
- recommended_pitch/primary_problem/reason_now text; computed_at timestamptz DEFAULT now()
- INDEX ix_scores_lead (lead_id, computed_at DESC)

**experiments**
- id uuid PK; workspace_id NOT NULL; name text NOT NULL; hypothesis text
- dimension text CHECK ('subject','opening','cta','offer','signal_type','email_length','followup_timing','industry','segment')
- status text CHECK ('running','paused','completed') DEFAULT 'running'; created_at/updated_at

**experiment_assignments**
- id uuid PK; experiment_id uuid NOT NULL → experiments CASCADE; lead_id uuid NOT NULL → leads CASCADE
- variant text NOT NULL; created_at; UNIQUE (experiment_id, lead_id)

**watch_subscriptions**
- id uuid PK; workspace_id NOT NULL; company_id uuid NOT NULL → companies CASCADE
- kinds jsonb NOT NULL DEFAULT '["hiring","website_change","leadership"]'
- last_checked_at timestamptz; status CHECK ('active','paused') DEFAULT 'active'; created_at

### 0007_ops.sql

**jobs** — durable queue (see §4)
- id uuid PK; type text NOT NULL
- pool text CHECK ('discovery','enrichment','verification','ai','outbound','meeting')
- priority int CHECK 0..5 DEFAULT 3 (P0 = highest urgency = lowest number)
- status text CHECK ('QUEUED','RUNNING','COMPLETED','FAILED','RETRYING','CANCELLED','DEAD_LETTER') DEFAULT 'QUEUED'
- payload jsonb DEFAULT '{}'; result jsonb; attempts/max_attempts int DEFAULT 0/3
- run_at timestamptz NOT NULL DEFAULT now(); provider text; idempotency_key text UNIQUE
- error text; workspace_id uuid NULL → workspaces CASCADE
- created_at/started_at/completed_at; INDEX ix_jobs_claim (pool, status, priority, run_at)

**alerts**
- id uuid PK; workspace_id uuid NULL → workspaces CASCADE
- severity CHECK ('critical','warning','attention','info'); source/entity_type/entity_id text
- message text NOT NULL; detail jsonb DEFAULT '{}'
- status CHECK ('open','acknowledged','resolved') DEFAULT 'open'; created_at; resolved_at

**daily_audits**
- id uuid PK; audit_date date NOT NULL UNIQUE; overall_score int
- report jsonb DEFAULT '{}' (sections: domains, mailboxes, apis, n8n, db, campaign, problems, actions); report_md text; created_at

**telegram_settings** — singleton row (id=true)
- id boolean PK DEFAULT true CHECK (id = true)
- bot_token_encrypted text (Fernet ciphertext via APP_SECRET; never plaintext)
- chat_id text; enabled boolean DEFAULT false; notify_types jsonb DEFAULT '{}'
- level CHECK ('all','important','critical') DEFAULT 'important'; created_at/updated_at

## 2. Provider protocols (backend/app/providers/base.py)

All imports from `app.providers` (re-exported). Exceptions:
`ProviderUnavailable(msg)`.

Dataclasses:
- `VerificationResult(email: str, result: str, confidence: float = 0.0, raw: dict = {})`
- `LLMResponse(content: str, model_used: str, tokens_in: int = 0, tokens_out: int = 0, latency_ms: int = 0, cost_usd: float = 0.0)`
- `SendResult(ok: bool, provider_message_id: str | None = None, error: str | None = None)`

ABCs (all methods abstract):
- `JobSourceProvider.search(query: str, filters: dict | None = None) -> list[dict]`
- `EnrichmentProvider.enrich_company(company: dict) -> dict`
- `EmailFinderProvider.find_email(company: dict, contact_name: str, title: str | None = None) -> dict | None`
- `EmailVerificationProvider.verify(email: str) -> VerificationResult`
- `LLMProvider.complete(system: str, user: str, model_tier: str = "cheap") -> LLMResponse`  # tier: cheap|strong|frontier
- `EmailSendingProvider.send(*, from_addr: str, to: str, subject: str, body_text: str, body_html: str | None = None, message_id: str | None = None) -> SendResult`
- `CRMProvider.upsert_company(company_data: dict) -> dict | None`
- `CRMProvider.upsert_contact(contact_data: dict) -> dict | None`
- `CRMProvider.create_opportunity(opp_data: dict) -> dict | None`
- `CRMProvider.get_contact(contact_id: str) -> dict | None`
- `CRMProvider.search_contacts(query: str) -> dict | None`
- `CalendarProvider.create_event(event_data: dict) -> dict | None`
- `CalendarProvider.get_availability(start: str, end: str) -> dict | None`
- `CalendarProvider.book_slot(slot: dict, contact: dict) -> dict | None`

Registry (module singleton `registry`; helpers `register(name, provider)`,
`get(name)`):
- `register(name, provider)` — production wiring
- `override(name, provider)` / `clear_overrides()` — fixture shadowing, overrides win
- `get(name)` raises `ProviderUnavailable` if neither present

### OpenRouter LLM (app/providers/llm_openrouter.py)

`OpenRouterChatLLM(transport=None)`. Raises `ProviderUnavailable` at
construction when no API key (settings.llm_api_key or OPENROUTER_API_KEY).
Model chain: settings.llm_model_chain_list (from comma-separated
LLM_MODEL_CHAIN). complete() walks models in order from the tier start point;
retries next model on network errors, HTTP >= 500, and 429 (`OpenRouterError.status_code`);
non-retryable 4xx raises immediately; exhausted chain raises ProviderUnavailable.
Tiering hook: cheap → chain[0]; strong → LLM_STRONG_MODEL env override else
chain[0] (documented default), then continues down chain; frontier → chain[-1].
cost_usd uses app.services.llm.estimate_cost (agent_runs-compatible fields);
record_run is untouched. `transport(payload_dict) -> dict` injectable for tests
(OpenRouter chat-completions response shape).

## 3. Resilience (app/providers/resilience.py)

- `CircuitBreaker(failure_threshold=10, reset_timeout=60.0)` — states
  closed/open/half-open. `allow() -> bool` (lazy open→half-open after timeout),
  `check()` raises CircuitOpenError when open, `record_success()` /
  `record_failure()`; sync `call(fn)` and async `acall(async_fn)` wrappers.
- `AsyncRateLimiter(max_concurrency)` — asyncio semaphore gate,
  `async with limiter:`; loop-safe lazy construction.
- `retry_with_backoff(fn, attempts=3, base_delay=1.0, jitter=0.5, retry_on=(Exception,))` async
- `retry_with_backoff_sync(...)` identical signature, sync fn/sleep.

## 4. Job queue + workers (backend/app/services/job_queue.py)

Functions (dict rows via db.get_pool()):
- `enqueue(*, type, pool, priority=3, payload=None, idempotency_key=None, max_attempts=3, run_at=None, workspace_id=None, provider=None) -> dict`
  ON CONFLICT (idempotency_key) DO UPDATE SET id = jobs.id RETURNING * → returns existing row on replay.
- `claim_next(pool) -> dict | None` — FOR UPDATE SKIP LOCKED; QUEUED + run_at <= now();
  ORDER BY priority ASC (P0 first), run_at ASC; sets RUNNING, attempts+1, started_at.
- `complete(job_id, result=None)` → COMPLETED + result + completed_at.
- `fail(job_id, error, *, base_delay=2.0, jitter=1.0)` → DEAD_LETTER when
  attempts >= max_attempts; else back to QUEUED with run_at =
  now() + base*2^attempts ± jitter (RETRYING is a conceptual state; rows land QUEUED).
- `get_job(job_id) -> dict | None`.

Worker pattern:
```python
from app.services import job_queue as jq

@jq.worker("verification", "verify_email")   # (pool, type)
def handle(job: dict):                       # may be sync or async
    return {"ok": True}                      # return value stored under result.result
```
Unhandled (pool,type) or handler exception → fail() path (retry/backoff/DLQ).

`WorkerSupervisor(pools=None, poll_interval=1.0)` — pools default from
settings.worker_pools_json ({"ai":2,"enrichment":2,"verification":2,"outbound":2,"discovery":1,"meeting":1});
per-provider caps from settings.provider_concurrency_json via AsyncRateLimiter.
API: `start()` spawns one asyncio task per pool; `await stop()` cancels gracefully;
`await run()` = start + block. Lifespan: main.py starts a supervisor only when
settings.workers_enabled (default False; set WORKERS_ENABLED=true in prod env).

## 5. System flags helper (backend/app/services/flags.py)

- `set_flag(key, value, updated_by=None) -> dict` — upsert (value JSON-serialized)
- `get_flag(key) -> value | None`
- `all_flags() -> dict[key, value]`

## 6. Fixture mode (tests)

Selection mechanism: real providers needing credentials raise
ProviderUnavailable at construction; tests install fixtures via
`providers.registry.override(name, instance)` (shadow wins over register;
`clear_overrides()` restores). Available in app/providers/fixtures.py:

- `FixtureLLM(scripts={marker_substring: canned_content}, fail_once=False)` — marker substring match on system+"\n"+user, else deterministic echo of system+\n+user; `fail_once=True` raises RuntimeError once.
- `FixtureJobSource(postings=[...])` — search filters on filters["title_contains"].
- `FixtureVerifier(result="valid", confidence=0.95)` — records verified emails.
- `FixtureEnrichment(extra_fields={...})` — merges into company dict.
- `FixtureEmailSender(fail_next=0)` — records sends in `.sent`; next N sends return SendResult(ok=False).
- `FixtureEmailFinder(addresses={(business_name, contact_name): email})` — falls back to deterministic first-name@domain.

Env for tests: conftest points Settings at orbit_test; LLM chain/key tests
clear get_settings.cache_clear() around monkeypatched env.
