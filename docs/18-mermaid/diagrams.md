# MERMAID — Canonical diagrams (generated from code, not decoration)

> Each diagram is rendered from the same canonical relationships that power `frontend/src/gtm/canonical.ts` and `services/state_machine.py` / `services/gtm_lifecycle.py`. If diagram ≠ code, file a drift bug.

---

## 1. Overall GTM flow (continuous decision system)

```mermaid
flowchart LR
  FIND[FIND<br/>Business Discovery] --> U[UNDERSTAND<br/>Who is this?]
  U --> Q[QUALIFY<br/>Prioritize P1-P4]
  Q --> IDENT[IDENTIFY<br/>Company→Person→Verified contact]
  IDENT --> OPP[OPPORTUNITY<br/>Hypothesis + evidence + why now]
  OPP --> DECIDE[DECIDE<br/>Angle = Problem+Service+Contact+Signal]
  DECIDE --> GATE{OUTBOUND GATE<br/>13 checks<br/>allowed?}
  GATE -->|allowed}| OUT[OUTREACH<br/>Day0/3/7/14 react to behavior]
  GATE -->|held| HELD[HELD / Review]
  OUT --> RESP{RESPONSE<br/>Classify intent 13 classes}
  RESP -->|question/objection| CONV[CONVERSE<br/>Remember + answer + qualify]
  RESP -->|ready to book| BOOK[BOOK / HANDOFF<br/>Prepared opportunity]
  CONV --> BOOK
  RESP -->|not a fit / later / do_not_call| ARCH[Archived / Nurture]
  BOOK --> LEARN[LEARN<br/>Outcome → evidence → future targeting]
  LEARN -.->|better FIND weights| FIND
  style GATE fill:#fef3c7,stroke:#f59e0b
  style LEARN fill:#fffbeb,stroke:#f59e0b
```

---

## 2. Two brains

```mermaid
flowchart TD
  subgraph LEADS[GTM Leads — Who should Orbit pursue?]
    L1[FIND → UNDERSTAND → QUALIFY → IDENTIFY → OPPORTUNITY]
    L1 --> LOUT[TARGET + CONTACT + QUALIFICATION + PRIORITY + RATIONALE]
  end
  subgraph INTENT[GTM Intent — What is happening?]
    I1[OBSERVATION → SIGNAL → CONTEXT → INTERPRETATION → OPPORTUNITY HYPOTHESIS]
    I1 --> IOUT[SIGNAL + TIMING + PROBLEM HYPOTHESIS]
  end
  LOUT --> OPP{Opportunity}
  IOUT --> OPP
  OPP --> DEC[DECISION: OUTREACH?]
  style LEADS fill:#eef2ff,stroke:#6366f1
  style INTENT fill:#fdf2f8,stroke:#ec4899
```

---

## 3. Lead state machine (from `services/state_machine.py:6`)

```mermaid
stateDiagram-v2
  [*] --> new
  new --> enriching: qualified
  new --> rejected
  enriching --> qualified: fit≥6
  enriching --> signal_holding: needs timing
  enriching --> rejected
  qualified --> signal_holding
  qualified --> outreach_ready
  qualified --> contacted
  signal_holding --> outreach_ready
  signal_holding --> qualified
  outreach_ready --> contacted: send-ready + approved
  contacted --> responded: reply (kill switch)
  responded --> qualified_conversation
  qualified_conversation --> meeting_booked
  meeting_booked --> meeting_held
  meeting_held --> proposal
  proposal --> won
  proposal --> lost
  meeting_held --> won
  contacted --> unreachable
  responded --> lost
  lost --> archived
  unreachable --> archived
  new --> do_not_call: any non-terminal
  enriching --> do_not_call
  qualified --> do_not_call
  contacted --> do_not_call
  won --> [*]
  archived --> [*]
  do_not_call --> [*]
  rejected --> [*]
```

---

## 4. GTM message lifecycle (from `services/gtm_lifecycle.py:31`)

```mermaid
stateDiagram-v2
  [*] --> DISCOVERED
  DISCOVERED --> QUALIFIED
  QUALIFIED --> INTENT_SCORED
  INTENT_SCORED --> RESEARCHED
  RESEARCHED --> COPY_GENERATED
  COPY_GENERATED --> QA_PENDING
  QA_PENDING --> QA_PASSED: passed
  QA_PENDING --> QA_FAILED: critical findings
  QA_FAILED --> COPY_GENERATED: resubmit
  QA_FAILED --> HELD: ceiling
  QA_PASSED --> COMPLIANCE_PENDING
  COMPLIANCE_PENDING --> SEND_READY: passed
  COMPLIANCE_PENDING --> COMPLIANCE_FAILED
  COMPLIANCE_FAILED --> SUPPRESSED
  SEND_READY --> SCHEDULED
  SCHEDULED --> SENT: claimed + delivered
  SEND_READY --> HELD
  SCHEDULED --> HELD
  HELD --> QA_PENDING: fixable
  HELD --> CANCELLED
  SENT --> [*]
  SUPPRESSED --> [*]
  EXPIRED --> [*]
  CANCELLED --> [*]
```

Note: `AUTHORIZED_SEND_STAGES=(SEND_READY,SCHEDULED)` enforced in `services/outbound_gate.py:154`. Legacy `gtm_stage IS NULL` skips QA/compliance/stage checks.

---

## 5. Outbound gate decision tree (13 checks)

```mermaid
flowchart TD
  A[can_send check 13] --> B{lead_eligible?}
  B -->|no| HOLD1[HOLD: bad lead status]
  B -->|yes| C{contact_eligible?}
  C -->|no| HOLD2[HOLD: no email / opted out]
  C -->|yes| D{not_suppressed?}
  D -->|no| BLOCK[HELD/SUPPRESSED]
  D -->|yes| E{email_verified?}
  E -->|no| HOLD3[HOLD: not verified]
  E -->|yes| F{copy_qa_passed?}
  F -->|no| QAFAIL[QA_FAILED]
  F -->|yes| G{compliance_passed?}
  G -->|no| COMFAIL[COMPLIANCE_FAILED]
  G -->|yes| H{stage_authorized?}
  H -->|no| HOLD4[HOLD: wrong stage]
  H -->|yes| I{mailbox/domain healthy + limits + campaign + sequence}
  I -->|fail| HOLD5[HOLD with reason]
  I -->|all pass| SEND[SEND_READY: allowed]
```

---

## 6. Learning loop

```mermaid
flowchart LR
  OUT[OUTCOME<br/>reply/no-reply, booked, won/lost, unsubscribe] --> INT[INTERPRETATION]
  INT --> EV[EVIDENCE<br/>scores, provider_usage, agent_runs, audit_log]
  EV --> ADJ[FUTURE ADJUSTMENT<br/>targeting, qualification, messaging, timing, contact]
  ADJ --> FIND[FIND weights]
  FIND --> Q[QUALIFY threshold]
  Q --> DEC[DECIDE angle]
  DEC --> OPP[OPPORTUNITY hypothesis]
  style OUT fill:#fef3c7,stroke:#f59e0b
  style ADJ fill:#e0f2fe,stroke:#0ea5e9
```

Examples: high reply to hiring-pressure → valuable signal; high interest but low booking → CONVERSE→BOOK transition needs fix; poor qualification from source → downgrade.

---

## 7. System layering (from `services/pipeline.py:1` §10.3)

```mermaid
flowchart TB
  subgraph Frontend[Frontend]
    W[React + Vite + Tailwind<br/>GTM Explorer, Dialer, Approvals]
  end
  subgraph Backend[Backend Core API - FastAPI]
    API[Lead state machine, scoring, gate, QA, suppression, audit]
  end
  DB[(Postgres<br/>system of record<br/>9 migrations)]
  EVT{{Postgres outbox<br/>orbit_events LISTEN/NOTIFY}}
  N8N[[n8n<br/>orchestration: LLM + scrape + SMTP + retries]]
  LLM[(LLM providers<br/>OpenRouter nemotron:free → mimo)]
  COMMS{{Twilio Voice + WebRTC<br/>+ SMTP mailboxes}}
  SRC[(Source adapters<br/>Maps, job feeds, hunter/ apollo)]
  W --> API
  API --> DB
  API --> EVT --> N8N
  N8N --> LLM
  N8N --> COMMS
  N8N --> SRC
  API -.->|never calls LLM directly| LLM
  W -.->|never owns state| API
```

---

## 8. Conversation flow (RESPONSE → CONVERSE → BOOK)

```mermaid
sequenceDiagram
  participant P as Prospect
  participant O as Orbit (OUTREACH)
  participant R as RESPONSE classifier
  participant C as CONVERSE
  participant H as Human
  O->>P: initial (73w, evidence opener)
  P->>R: reply
  R->>R: classify intent (13 classes) + kill switch
  alt interested/curious
    R->>C: draft + context
    C->>P: answer + qualify
    P->>C: follow-up question
    C->>H: HUMAN_REQUIRED if pricing/high-value
    C->>H: propose booking if ready
  else objection
    R->>C: handle concern
    C->>P: augment not replace, after-hours
  else wrong person
    R->>R: re-identify with referral
  else not interested / do_not_call
    R->>R: suppress + archive
  else ready to book
    R->>H: packet + booking link
  end
  H->>P: meeting booked (handoff)
  Note over H,P: Human receives prepared opportunity, not empty event
```

---

## 9. Opportunity synthesis

```mermaid
flowchart TB
  WHO[Who is this? identity + contacts]
  SIG[What happening? signals + timing]
  PROB[What problem likely exists? pains]
  WHY{{Why Orbit? offer catalog match}}
  NOW{{Why now? hiring + ads recency}}
  COH[Contact + history]
  CONF[Confidence]
  WHO & SIG & PROB & WHY & NOW & COH --> PROF[Opportunity profile<br/>hypothesis + evidence + avoid_assumptions]
  PROF --> GATE{Gate decision}
  GATE --> ANGLE[Outreach angle = Problem + Service + Contact + Context + Signal]
```

---

## 10. Agent boundaries

```mermaid
flowchart LR
  LLMCHAIN[LLM chain nemotron-3 free → mimo]
  subgraph AGENTS[Agents]
    LEADS[GTM_LEADS]
    INTENT[GTM_INTENT]
    QA[GTM_QA independent critic]
    OUTB[GTM_OUTBOUND]
    REPL[GTM_REPLIES]
  end
  subgraph DETERM[Deterministic code]
    PIPE[pipeline.py scoring arithmetic]
    GATE[ outbound_gate 13 checks ]
    LIFE[gtm_lifecycle FSM]
    STATE[state_machine FSM]
  end
  AGENTS -.-> DETERM
  PIPE -.-> LLMCHAIN
  GATE -.-> AGENTS
```

Each agent narrow JSON-in JSON-out, event-driven, model-tiered. QA never generates copy.
