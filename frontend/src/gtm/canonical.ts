/**
 * Canonical GTM stage representation — single source of truth.
 * Powers: SYSTEM MAP, LESSONS, ONBOARDING (Learn Mode), PROSPECT SIMULATION,
 * SEARCH, and DETAIL PANELS. Prevents documentation drift.
 *
 * Architecture: 11-stage GTM + 2 brains + 7 principles
 * Trace: docs/ORBIT_MASTER_SPEC.md §6.4, §7.1, §9.1
 */

export type GtmStageId =
  | "find"
  | "understand"
  | "qualify"
  | "identify"
  | "opportunity"
  | "decide"
  | "gate"
  | "outreach"
  | "response"
  | "converse"
  | "book"
  | "learn";

export interface GtmStage {
  id: GtmStageId;
  index: number; // 1-based for display
  title: string;
  short: string;
  icon: string;
  color: string; // CSS gradient
  accent: string; // solid for dots/borders
  // Required panel sections — observable reasoning, not chain-of-thought
  whatItIs: string;
  whyExists: string;
  whatEnters: string[];
  whatHappens: string;
  decisions: string[];
  whatComesOut: string[];
  realExample: { title: string; body: string };
  edgeCases: string[];
  whatCanGoWrong: string[];
  howItConnects: { from: string; to: string; detail: string };
  whyItMatters: string;
  // Technical details for advanced disclosure
  advanced: string;
  // Implementation trace for observability
  trace: {
    backendModules: string[];
    stateMachine?: string;
    agent?: string;
    tables?: string[];
  };
}

export interface GtmBrain {
  id: "leads" | "intent";
  title: string;
  subtitle: string;
  icon: string;
  color: string;
  whatItIs: string;
  whatItDoes: string;
  whatItDoesNot: string;
  output: string;
  example: string;
  trace: string[];
}

export interface GtmPrinciple {
  n: number;
  title: string;
  detail: string;
}

// ---------------------------------------------------------------- canonical stages
export const GTM_STAGES: GtmStage[] = [
  {
    id: "find",
    index: 1,
    title: "FIND",
    short: "Business Discovery — raw to understood",
    icon: "F",
    color: "linear-gradient(135deg,#0ea5e9,#22d3ee)",
    accent: "#0ea5e9",
    whatItIs:
      "Build a broad but useful universe of potential businesses before deciding which deserve attention. Raw scattered public signals → initial business profile.",
    whyExists:
      "Without broad discovery you only talk to who you already know. FIND ensures coverage, then narrows with intelligence. It prevents pipeline starvation and bias toward familiar sources.",
    whatEnters: [
      "Google Maps, business directories, hiring activity, expansion signals",
      "Websites, social media, job postings, advertising, reviews",
      "Other public business signals (BBB, Yelp, Angi, state license DBs, chambers)",
    ],
    whatHappens:
      "Orbit continuously scans sources via pluggable provider adapters (JobsPipe, TheirStack, JSearch, FantasticJobs, Adzuna + Maps scrapers), normalizes to {name, website, phone, city, state, source, source_url}, deduplicates by SHA-256(name|city|state) and phone-normalized dedupe (dialer), checks active/legitimate via recency and signal absence, and creates an initial Company + Lead record with source lineage (source_url + collected_at). Enforced idempotency prevents double-counting.",
    decisions: [
      "Is there enough information to evaluate? → else mark low-info, keep monitoring",
      "Does it match broad ICP filters (home-services, local, owner-operated)?",
      "Is it active and legitimate vs closed/stale?",
      "Duplicate of existing business? → merge/keep best record",
    ],
    whatComesOut: [
      "Candidate business record (Company + Lead status=new)",
      "Initial profile: type, size proxy, services, location",
      "Flag: needs more info vs ready to UNDERSTAND",
      "Source lineage for audit (every contact stores source URL + date)",
    ],
    realExample: {
      title: "ABC HVAC at FIND",
      body: "Raw input: Local HVAC, 3 service areas, new dispatcher job posting, Google Ads active, website exists but booking flow weak. → Orbit creates candidate: HVAC, home-services, 3 areas, possible call-handling pressure. Not yet a judgment — just a profile. Stored as lead status=new, company deduplicated on city/state, activity logged.",
    },
    edgeCases: [
      "Duplicate name with slightly different spelling → normalized name+city+state dedupe catches it; phone dedupe in dialer",
      "Business with no website → still profiled from Maps + jobs, marked low-info, UNDERSTAND will have low confidence",
      "Inactive/closed business → filtered via recency + signal absence; hiring_superseded? expired after 60d",
      "CSV import with 5-row preview → column mapping + header detection prevents bad data entering FIND",
    ],
    whatCanGoWrong: [
      "Scraping blocked (anti-bot) → source adapter returns [] silently; provider fixtures fallback masks failure; no alert if all sources return 0",
      "Phone normalization skipped → duplicate leads slip through, double-contact risk",
      "Direct DB insert bypasses dedupe logic → duplicate companies with same name+city+state but different whitespace/casing",
      "No RLS row filter → tenant leak if workspace_id not supplied (conftest showed /events/pending unscoped)",
    ],
    howItConnects: {
      from: "External public signals",
      to: "UNDERSTAND",
      detail:
        "FIND produces raw candidates; UNDERSTAND enriches them with business context so signals become interpretable. FIND is the only stage that creates Company/Lead rows — downstream never creates, only transitions.",
    },
    whyItMatters:
      "Coverage is strategy. Without FIND you optimize only within what you already see; with FIND you build a machine that finds fewer, better leads with a clear reason to reach out.",
    advanced:
      "Providers: app/providers/job_sources.py + app/providers/base.py Registry with fixture overrides; dedupe: pipeline.py SHA-256 + dialer phone-normalized; state: leads.status=new; tables: companies, leads, job_postings/hiring_signals (dual — migration consolidation pending); worker: discovery:1 pool; resilience: CircuitBreaker(5,60s)+retry_with_backoff_sync(3).",
    trace: {
      backendModules: ["app/providers/job_sources.py", "app/services/pipeline.py", "app/routers/leads.py"],
      stateMachine: "new → enriching",
      agent: "GTM_LEADS",
      tables: ["companies", "leads", "job_postings", "hiring_signals"],
    },
  },
  {
    id: "understand",
    index: 2,
    title: "UNDERSTAND",
    short: "Who is this business? — business understanding",
    icon: "U",
    color: "linear-gradient(135deg,#06b6d4,#0ea5e9)",
    accent: "#06b6d4",
    whatItIs:
      "Turn a name into an understood business. Orbit asks what the business does, not just that it exists, and gathers context that makes downstream signals meaningful.",
    whyExists:
      "Raw businesses are useless for prioritization. Understood businesses let Orbit ask the right next question: what's happening here and why should we care now? Context prevents misclassifying signals.",
    whatEnters: [
      "Candidate profile from FIND (name, website, phone, city, state)",
      "Website content, Maps details, social presence",
      "Hiring and growth context if available from intent engine",
    ],
    whatHappens:
      "Extract business category, service area, size proxy (crew, locations, employee_estimate), relevant services, owner visibility, tech signals, review signals (google_rating, review_count), booking/chat/mobile/CTA/after-hours findings via website_intel (regex + PageSpeed API + optional LLM summarize), and hiring_signals processing. Deterministic rules run before any LLM — enrichment gated on qualified only per spec §7.2 hard rule #1.",
    decisions: [
      "What type/size is this business? → owner-operated vs franchise vs multi-location vs enterprise",
      "Which Orbit offers could be relevant given observed gaps?",
      "Is there enough context to interpret signals, or keep monitoring vs advance?",
      "Fail-closed: unclear data → borderline/rejected, never a guess (spec §10.3)",
    ],
    whatComesOut: [
      "Enriched business understanding (companies.tech_signals, companies.reviews, leads.website_findings)",
      "ICP relevance hint for QUALIFY",
      "Signal-interpretation readiness flag",
      "Enrichment notes + owner_operator_confidence (0-100, distinct from fit score per FR-5)",
    ],
    realExample: {
      title: "ABC HVAC at UNDERSTAND",
      body: "Orbit reads: HVAC, 3 areas, active website (weak booking, no chatbot, forms but slow), hiring dispatcher, running ads, 4.6★ 82 reviews. → Understanding: growing home-services, likely inbound demand, possible scheduling pressure, relevant for lead-response / booking automation. Confidence builds to medium-high. Evidence: tech_signals + website_findings written to both companies and leads.",
    },
    edgeCases: [
      "Minimal web presence → low confidence, stays monitoring, not promoted to QUALIFY",
      "Multi-location vs single-location → different scaling implications, impacts score",
      "Franchise vs independent → different decision maker (Founder vs Manager), suppressed for ICP",
      "React-rendered site blocks regex parse → stealth fetcher (Scrapling) retries with headless, fallback to Maps+hiring only",
    ],
    whatCanGoWrong: [
      "website_intel regex HTML parsing brittle on SPA sites → misses booking CTA, false negative pain",
      "Dual write companies.tech_signals + leads.website_findings can go stale if one path writes stale cache",
      "Enrichment owner_email dropped silently — TARGET_FIELDS has owner_email but COMPANY_ENRICHABLE_FIELDS lacks column (known bug)",
      "LLM summarize violates spec §10.3 'backend never calls LLM' — architectural contradiction; provider failure falls to generic fallback violating fail-closed",
    ],
    howItConnects: {
      from: "FIND",
      to: "Signals & QUALIFY",
      detail:
        "UNDERSTAND enriches FIND's raw profile with auditable evidence; QUALIFY then uses that evidence + signals to score ICP fit 0-10 with mandatory evidence text. UNDERSTAND never scores — it only gathers.",
    },
    whyItMatters:
      "Every downstream decision (QUALIFY, IDENTIFY, DECIDE) cites evidence produced here. Without evidence, downstream gates must fail closed.",
    advanced:
      "Modules: app/services/website_intel.py, app/services/enrichment.py (waterfall Apollo>Hunter>Clearbit, rank_title), app/services/hiring_signals.py (classify_role LLM cheap→keyword fallback); gates: enrichment hard-gated on fit_status==qualified; tables: companies.tech_signals jsonb, leads.website_findings jsonb, contacts; worker pools: enrichment:2, verification:2; constraints: never invent owner/email/findings.",
    trace: {
      backendModules: ["app/services/website_intel.py", "app/services/enrichment.py", "app/services/hiring_signals.py"],
      stateMachine: "new → enriching → qualified (if evidence supports)",
      agent: "GTM_LEADS (enrichment), GTM_INTENT (signals)",
      tables: ["companies", "contacts", "hiring_signals"],
    },
  },
  {
    id: "qualify",
    index: 3,
    title: "QUALIFY",
    short: "Is this actually a good prospect? — intelligent prioritization",
    icon: "Q",
    color: "linear-gradient(135deg,#10b981,#06b6d4)",
    accent: "#10b981",
    whatItIs:
      "Qualification is not whether a company exists, but whether it's worth attention now. Orbit scores Fit + Need + Timing + Confidence = Priority (P1/P2/P3) and maps to HIGH / POSSIBLE / NOT FIT.",
    whyExists:
      "Prevents wasting attention on everyone. Focus is a feature. Without qualification, outreach becomes spam; with it, every contact has a legitimate reason.",
    whatEnters: [
      "ICP fit signals: single-location +3, owner visible +3, family owned +2, simple site +2, etc.; franchise -4, multi-location -4, enterprise -3",
      "Need evidence: booking gaps, chat missing, after-hours gaps, hiring strain",
      "Timing: signal freshness, recency decay (1 - age/30), hiring intent 0-100",
      "Contactability, potential value, confidence, active status",
    ],
    whatHappens:
      "Deterministic arithmetic: icp_fit_score 0-10 (weighted ±, /1.8, QUALIFY_THRESHOLD=6), priority_score 0-100 (0.4 intent +0.3 fit+0.2 contact+0.1 history → tier P1 85-100 speed-to-lead, P2 65-84, P3 40-64, P4 <40 nurture), hiring_intent_score 0-100 (role +25, ICP +30, after-hours +15, phone-heavy +15, scheduling +15). Evidence text mandatory per pipeline hard rule #3. Borderline/low-confidence → review queue. intent_engine.reevaluate_lead recomputes priority with recency decay and writes scores row (score_type='opportunity').",
    decisions: [
      "HIGH-VALUE FIT (P1/P2, score≥6, evidence strong) → move toward IDENTIFY/OPPORTUNITY",
      "POSSIBLE FIT → monitor / gather more info (may be relevant, needs stronger evidence)",
      "NOT A FIT (rejected_too_large, rejected_not_relevant, rejected_unclear, do_not_call) → discard / suppress / monitor",
      "Do not conflate 3 scores: ICP fit 0-10 (is it ICP?), Priority 0-100 (what order?), Hiring intent 0-100 (how strong is timing?) — spec §7.3",
    ],
    whatComesOut: [
      "Priority P1/P2/P3/P4 + tier A+/A/B/C/D, recommended action, score breakdown",
      "fit_status ∈ {qualified, borderline, rejected_too_large, rejected_not_relevant, rejected_unclear}",
      "Evidence bundle + contributions[] for why-panel (observable factors)",
      "Signal expiry handling (60d hiring, 30d recency)",
    ],
    realExample: {
      title: "ABC HVAC qualify",
      body: "ICP fit strong (home-services, 3 areas = local, single-brand), need strong (dispatcher hiring + ads + weak booking = observed pains), timing medium-high (hiring now, fresh 3d), contactability unknown yet → P1 HIGH-VALUE FIT (priority 78, intent 35, fit 8/10) → worth contacting. If dispatcher were only signal and no ads, would be POSSIBLE → monitor. Evidence: hiring posting URL + website audit screenshot hashes logged.",
    },
    edgeCases: [
      "Borderline score 6 on rounding (total 10→6 vs 11→6) → stays POSSIBLE, not forced HIGH; deterministic threshold prevents judgment creep",
      "Strong fit but poor contactability → P2, needs email finder before OUTREACH gate",
      "Contradictory signals (hiring + layoff) → confidence lowered, not auto-HIGH; both kept, interpretation weighs context",
      "Stale 29d signal → recency 1/30 → P3 not P1; 30d → recency 0 → still inserts 0-point contributions (unfiltered)",
    ],
    whatCanGoWrong: [
      "Two qualification paths diverge: pipeline.apply_qualification (new→enriching|rejected) vs leads.score_lead (new→qualified|rejected) — different target states, bypasses signal_holding",
      "Threshold drift: icp_fit_score /1.8 divisor not calibrated; total=11 and 10 both map to 6 (borderline ambiguity)",
      "Known_event_types merges DEFAULT + mutable global _extra via register_event_type — no persistence, race unsafe, N+1 connections per reevaluate",
      "_has_tier_a reads scores.tier IN ('A','A+') but reevaluate never writes tier → always NULL, P2 promotion dead code",
      "OFFER_CATALOG duplicated 4 places with 8/9/10 sizes — adding offer to one doesn't propagate",
    ],
    howItConnects: {
      from: "Signals + Interpretation",
      to: "IDENTIFY",
      detail:
        "QUALIFY consumes signals (hiring_signals) + business understanding (website_intel) + ICP arithmetic (scoring.py) and produces a priority that IDENTIFY uses to rank contact search effort and that BOOK ranks queue. QUALIFY never contacts — it only prioritizes.",
    },
    whyItMatters:
      "Every send must be justified. QUALIFY is where Orbit proves it has a reason to contact vs blasting everyone.",
    advanced:
      "Modules: app/services/scoring.py (pure arithmetic, zero DB), app/services/intent_engine.py (reevaluate with recency decay, contributions, priority band), app/services/opportunity.py (composite 0-100 + EMV); gates: FAIL-CLOSED evidence mandatory, enrichment gated on qualified; trace: scores table, leads.priority_score, leads.fit_status; agent: GTM_LEADS + GTM_INTENT; tests: test_scoring.py, test_hiring_signals.py.",
    trace: {
      backendModules: ["app/services/scoring.py", "app/services/intent_engine.py", "app/services/opportunity.py"],
      stateMachine: "qualified | signal_holding | outreach_ready | rejected",
      agent: "GTM_LEADS + GTM_INTENT",
      tables: ["leads", "scores", "hiring_signals"],
    },
  },
  {
    id: "identify",
    index: 4,
    title: "IDENTIFY",
    short: "Who should we talk to? — Company → Person → Verified contact",
    icon: "P",
    color: "linear-gradient(135deg,#6366f1,#8b5cf6)",
    accent: "#6366f1",
    whatItIs:
      "A correct contact is not someone who works at the company; it's someone who understands the problem, influences decision, or approves solution. Rank decision makers and verify contactability.",
    whyExists:
      "Right person at wrong time fails; wrong person at right time also fails. IDENTIFY maximizes relevance and prevents blasting info@ or unverified emails that damage deliverability.",
    whatEnters: [
      "Qualified company (fit_status==qualified)",
      "Opportunity angle (ops vs hiring vs booking) to choose role",
      "Title ranking + enrichment providers (Apollo/Hunter/Clearbit) + verification waterfall",
    ],
    whatHappens:
      "Rank decision makers: Owner/Founder, GM, Operations/Service/Office Manager (rank_title: Owner 1, CEO/Founder 5, GM 10, etc.). Choose based on problem: ops problem→ops manager/GM, hiring pressure→owner/ops leader, booking→owner/office manager, multi-location→founder/regional operator. find_decision_maker_email loops 10 titles, waterfall enrich_company_waterfall (priority apollo>hunter>clearbit via flags, quota reserve 20), then verify_email_waterfall (DISPOSABLE_DOMAINS 22 + SPAM_TRAP_KEYWORDS + DNS MX → ZeroBounce>HunterVerify). Cross-check suppression, duplicate, DNC. Generic info@ → hold, don't send.",
    decisions: [
      "Which role is most likely to care about this problem? → title ranking + angle match",
      "Is the contact usable (verified, not suppressed, not duplicate, opted_in)? → else HOLD",
      "Multiple strong contacts → pick one highest-ranked, note alternative for later",
      "Wrong person reply later (\"not me, talk to X\") → re-identify and route, don't suppress domain",
    ],
    whatComesOut: [
      "Likely decision maker + verified contact (contacts.email, contacts.email_verification_status=verified) or HOLD if poor quality",
      "Enrichment provenance: provider_used, confidence, source_notes, verified_at",
      "Suppression/DNC clearance",
      "Lead stays contact-less if find_decision_maker_email ON CONFLICT DO NOTHING without linking leads.contact_id (known bug — must be handled by pipeline.apply_enrichment)",
    ],
    realExample: {
      title: "ABC HVAC identify",
      body: "Operational + hiring pressure → Owner or Operations Manager. Orbit waterfall finds owner email via Apollo (priority 1, 92% confidence), verifies via ZeroBounce (verified), checks suppression (clear), DNC (clear). Generic info@ also found but discarded — need decision maker. If only generic found, gate will hold with reason 'bad contact'. Contact linked to lead via contacts insertion + leads.contact_id update atomically.",
    },
    edgeCases: [
      "Generic contact only → HOLD, don't blast info@; log review queue 'missing owner'",
      "Wrong person later (reply: 'not me, talk to X') → intent_engine classifies wrong_person, re-identify with named referral, don't mark company suppressed",
      "Multiple strong contacts (Owner + GM) → pick Owner, keep GM as alternative in notes for handoff packet",
      "Disposable domain (mailinator) → local precheck fails 22-list before burning provider quota",
    ],
    whatCanGoWrong: [
      "TARGET_FIELDS has owner_email but COMPANY_ENRICHABLE_FIELDS lacks column → enriched owner_email silently dropped (data loss, still appears unverified)",
      "find_decision_maker_email inserts contacts ON CONFLICT DO NOTHING but never updates leads.contact_id → lead stays contact-less, gate fails with 'no email' even though contact exists",
      "rank_title duplicated with different values (enrichment 5 keys vs email_finder 10 keys, 1-99 mapping divergence) → waterfall picks different best title per path",
      "Phone normalization caller-dependent: suppression.check lowercases email but phone not normalized → suppressed phone bypasses if stored normalized vs raw",
      "Quota 0 initial row treated as unlimited then later quota>0 check inverts deprioritization logic for first call",
    ],
    howItConnects: {
      from: "QUALIFY",
      to: "OPPORTUNITY",
      detail:
        "QUALIFY decides it's worth contacting; IDENTIFY finds who. OPPORTUNITY then uses that person + problem + timing to build a personalized angle. IDENTIFY is gated on QUALIFY (hard rule) and produces the contact gate OUTREACH checks.",
    },
    whyItMatters:
      "Deliverability + relevance. One unverified email or wrong person damages domain health and wastes human review. Fail-closed contact quality protects the entire system.",
    advanced:
      "Modules: app/services/enrichment.py (waterfall, _local_prechecks, DISPOSABLE_DOMAINS), app/providers/email_finder.py (ApolloEmailFinder rank_title), app/providers/email_verification.py (ZeroBounce/HunterVerify, CircuitBreaker, fixture fallback); contracts: contacts.email + contacts.email_verification_status must be 'verified' before OUTBOUND gate; tables: contacts, companies, suppression; worker: enrichment:2, verification:2.",
    trace: {
      backendModules: ["app/services/enrichment.py", "app/providers/email_finder.py", "app/providers/email_verification.py"],
      stateMachine: "qualified → signal_holding/outreach_ready (needs contact)",
      agent: "GTM_LEADS (enrichment)",
      tables: ["contacts", "companies", "suppression"],
    },
  },
  {
    id: "opportunity",
    index: 5,
    title: "BUILD OPPORTUNITY",
    short: "Opportunity Profile — bridge from research to action",
    icon: "O",
    color: "linear-gradient(135deg,#0ea5e9,#6366f1)",
    accent: "#0ea5e9",
    whatItIs:
      "Combine everything learned into a reasoned, evidence-based hypothesis — not a facts dump. A structured profile that answers: who, what happening, what problem probably exists, why relevant, why now, strongest angle, who to contact, evidence, what not to assume.",
    whyExists:
      "Without convergence, outreach is generic. With a profile, every message has a reason to exist and every handoff gives a salesperson context for a relevant first call. It is the single source downstream stages cite.",
    whatEnters: [
      "Company info, decision maker, business signals, website observations",
      "Growth indicators, operational problems, relevant Orbit service catalog (8 offers)",
      "Previous interactions, contact history, confidence, timing, intent score",
    ],
    whatHappens:
      "Converge inputs into research_reports (research.py _assemble_evidence from hiring_signals+job_postings+companies data, _call_llm_research via providers.llm strong tier, _validate_research_report claim→evidence coverage with repair loop once). Then compute opportunity 0-100 composite (opportunity.py 6 components: icp_fit/intent/severity/contactability/recency/history) + tier A+/A/B/C/D + EMV p_reply×p_meeting×value. PAIN_TO_OFFER mapping deterministic: strongest pain → one catalog offer (hard rule #4). research_reports written every call (no dedupe), _get_latest_research reads latest only.",
    decisions: [
      "Is the hypothesis credible and evidence-backed? → else mark low confidence, gate will hold",
      "What is the strongest angle vs alternatives? → pick one, note secondaries for follow-up",
      "What should we avoid assuming? → explicitly list unknowns to prevent hallucination",
      "Link offer → pain deterministically: must address recorded primary/secondary pain or contract error",
    ],
    whatComesOut: [
      "Opportunity profile: structured hypothesis with confidence, angle, evidence[], avoid_assumptions, primary_problem, reason_now, pitch",
      "Research report (citations, confidence, sources) + scores row (tier, score, EMV)",
      "Recommended offer locked to pain (offer-pain consistency check enforced)",
      "Evidence bundle that DECIDE will cite verbatim in draft",
    ],
    realExample: {
      title: "ABC HVAC opportunity",
      body: "Business: Growing HVAC, 3 areas, hiring dispatcher, active ads, weak booking (no chatbot, slow form). Likely issue: inbound demand creating scheduling/response pressure. Angle: Capture/qualify leads, reduce manual handling (AI receptionist + booking automation). Decision maker: Owner. Confidence medium-high. Reason now: hiring + ads = active investment + strain. Evidence: posting URL, website_findings (mobile 62, no chatbot), ad observation. Offer: AI receptionist (matches primary pain 'missed-call pressure'). EMV $4.45 (default p 0.05).",
    },
    edgeCases: [
      "Low confidence → profile marked needs more evidence, outbound GATE will hold (not send)",
      "Contradictory evidence (strong hiring but website says closed Sundays) → profile notes uncertainty, avoids assumption, suggests 'ask about capacity' angle",
      "Missing contact → profile exists but outreach blocked at gate with 'no verified contact'",
      "Repeated research calls → unbounded research_reports rows orphaned, only latest used (storage drift)",
    ],
    whatCanGoWrong: [
      "Circular: severity heuristic keyword scans primary_problem text which itself came from research → severity → score → research loop",
      "contactability caps at 10 but wrapper min(weight, contactability) uses weight 10 → effectively binary, not weighted",
      "p_reply always default 0.05 (history query passes), EMV static $4.45 — not learning from outcomes",
      "_validate keyword overlap >3 chars false-flags paraphrased claim as hallucination; _fallback_research generic 'High inbound call volume…' violates fail-closed if LLM down",
      "Research->opportunity order not enforced by event — manual; website_intel→research also manual, can score before research ready",
    ],
    howItConnects: {
      from: "IDENTIFY",
      to: "DECIDE",
      detail:
        "OPPORTUNITY is the bridge: IDENTIFY says who, UNDERSTAND+QUALIFY say worth contacting, OPPORTUNITY synthesizes into a single hypothesis that DECIDE turns into a message angle. Every downstream stage (DECIDE, GATE, OUTREACH, BOOK) reads this profile — it is the decision packet.",
    },
    whyItMatters:
      "Salesperson gets context to have a relevant first call, not a cold one. The profile is the handoff packet's core.",
    advanced:
      "Modules: app/services/research.py (WS-D with citations, strong-tier LLM, 1 repair), app/services/opportunity.py (composite + EMV, SIGNAL_TYPE_TO_OFFER), app/services/scoring.py (OFFER_CATALOG 8); tables: research_reports, scores, companies; agent: GTM_RESEARCH (not in scheduler registry — manual); LLM tier: strong (LLM_STRONG_MODEL or first in chain).",
    trace: {
      backendModules: ["app/services/research.py", "app/services/opportunity.py", "app/routers/opportunity.py"],
      stateMachine: "RESEARCHED → COPY_GENERATED (after profile approved)",
      agent: "GTM_RESEARCH (manual), GTM_INTENT (intent)",
      tables: ["research_reports", "scores", "companies"],
    },
  },
  {
    id: "decide",
    index: 6,
    title: "DECIDE",
    short: "Message Strategy — personalized angle, not mail merge",
    icon: "✎",
    color: "linear-gradient(135deg,#ec4899,#8b5cf6)",
    accent: "#ec4899",
    whatItIs:
      "Orbit doesn't send the same message to everyone. DECIDE selects a relevant problem, plausible outcome, and evidence-backed angle for this business now.",
    whyExists:
      "The strongest message is about the prospect's current situation, not Orbit's capabilities. Personalization means selecting evidence that earns the right to talk — not mail-merge placeholders.",
    whatEnters: [
      "Opportunity profile: problem, angle, evidence, timing, confidence",
      "Decision maker, business context, signal strength, hiring_posting URL if applicable",
    ],
    whatHappens:
      "Choose outreach strategy from 8 offers mapped to pains: lead-response, missed-call, hiring-replacement, booking automation, website conversion, growth/scale, operational efficiency, customer experience. Map signal+service+person to angle, then draft via pipeline.create_draft_message → gtm_lifecycle DISCOVERED→…→COPY_GENERATED→QA_PENDING. Drift checks: 4-sentence structure (Fact, Inference, Offer, Question via Hermes), <75 words, no invented facts, evidence opener + one low-friction CTA, follow-up angle. Drafts only — never auto-send.",
    decisions: [
      "Which angle is strongest for this business now given evidence? → pick one, note alternatives",
      "Is the angle credible given evidence? → else HOLD, don't send generic 'learn about AI services'",
      "Generic vs contextual — is there enough situation-specific proof to be relevant?",
      "Draft length, banned-phrase, claim-evidence coverage → QA gate will enforce deterministically",
    ],
    whatComesOut: [
      "Message strategy + draft (personalization_notes, subject, first sentence with evidence, body <75w, CTA, follow-up angle)",
      "Messages row status=pending_approval, gtm_stage=COPY_GENERATED→QA_PENDING",
      "Quality signals: word-count OK? banned-phrases absent? 4-sentence structure valid? CAN-SPAM block present?",
    ],
    realExample: {
      title: "ABC HVAC decide",
      body: "Signal: hiring dispatcher + active ads + weak booking. Angle: booking automation + AI receptionist for missed calls. Generic: 'Learn about our AI services?' (rejected by QA GENERIC_COPY) → Contextual: 'Noticed you're hiring a dispatcher while promoting new areas — often means more calls & scheduling pressure. Orbit helps service businesses respond, qualify, and book automatically — even core dispatcher tasks. Worth a brief intro?' (73w, cites posting URL, one CTA, follow-up angle: missed-call cost).",
    },
    edgeCases: [
      "Weak evidence → no credible angle → QA flags unsupported claim, draft held not sent",
      "Multiple angles (hiring + weak booking + multi-location) → pick strongest (dispatch pressure), note booking as follow-up angle 1",
      "High confidence but sensitive timing (layoff post alongside hiring) → soften angle or hold, don't pitch hard",
      "Hallucination risk: draft invents owner name not in enrichment → QA UNSUPPORTED_FACT → HELD",
    ],
    whatCanGoWrong: [
      "GTM_COPY agent defined in registry but no handler — copy generation entirely delegated to n8n/pipeline, no autonomous in-process path (AGENTS omits COPY)",
      "pipeline.apply_draft word-count + banned-phrases + 4-sentence checks duplicated verbatim in qa_service.run_copy_qa (drift risk: 75w >= in both but pipeline warns vs QA critical)",
      "create_draft_MESSAGE hardcodes status='pending_approval' while GTM machine expects QA_PENDING — dual status columns (messages.status + gtm_stage) not atomically constrained",
      "Claim coverage _claim_is_covered uses substring text.lower() in lowered → false positive if evidence snippet short/common",
    ],
    howItConnects: {
      from: "OPPORTUNITY",
      to: "GATE (OUTBOUND GATE)",
      detail:
        "DECIDE consumes OPPORTUNITY's profile and produces a draft that GATE judges. DECIDE never sends — it only proposes. GATE is the judgment before send that verifies the draft's evidence, contact, and timing.",
    },
    whyItMatters:
      "This is where Orbit earns attention. A generic draft wastes the opportunity; an evidence-linked draft moves to BOOK.",
    advanced:
      "Modules: app/services/pipeline.py (stage_context → n8n prompts + apply_draft validate), app/services/qa_service.py (run_copy_qa, run_compliance_qa), app/agents/prompts/email-personalization.md (Hermes 4-sentence); tables: messages (pending_approval + gtm_stage), qa_runs; gate: pipeline hard rule #4 offer-pain consistency; test: test_gtm_acceptance.TestQARejectionThenPass, TestUnsupportedClaimBlocksSend.",
    trace: {
      backendModules: ["app/services/pipeline.py", "app/services/qa_service.py", "app/agents/registry.py:GTM_COPY"],
      stateMachine: "RESEARCHED → COPY_GENERATED → QA_PENDING",
      agent: "GTM_COPY (n8n) + GTM_QA (critic)",
      tables: ["messages", "qa_runs"],
    },
  },
  {
    id: "gate",
    index: 7,
    title: "OUTBOUND GATE",
    short: "Should Orbit contact them? — judgment before send",
    icon: "G",
    color: "linear-gradient(135deg,#f59e0b,#ef4444)",
    accent: "#f59e0b",
    whatItIs:
      "Autonomous does not mean send everything. This gate is where Orbit shows judgment: a deterministic, auditable compliance and quality check before any send.",
    whyExists:
      "This is what makes Orbit not spam. Every send has a legitimate reason or it doesn't send. Fail-closed protects domain health, compliance, and prospect respect.",
    whatEnters: [
      "Confidence, ICP fit, signal quality, contact quality",
      "Duplicate status, previous contact, suppression, outreach limits, mailbox/campaign health",
      "Whether message has credible reason and timing is appropriate",
    ],
    whatHappens:
      "outbound_gate.can_send(workspace_id,message_id) runs 13 structural checks: lead_eligible (not rejected/do_not_call/archived/lost), contact_eligible (email present + not opted_out), not_suppressed (email/phone/company vs suppression global), email_verified (contacts.email_verification_status==verified), copy_qa_passed (latest qa_runs status passed), compliance_passed, stage_authorized (gtm_stage IN (SEND_READY,SCHEDULED), legacy NULL skips), mailbox_healthy (health_state != paused), domain_healthy (sending_domains status active), within_sending_limits (sent_today < daily_send_limit, date-aware), provider_available (always True — stub), campaign_active, sequence_state_ok (no inbound reply after last outbound), followup_mailbox_correct (matches original mailbox). Fail-closed: any check fails → allowed=false + reasons[] + checks[] audit.",
    decisions: [
      "YES → send-ready (enough confidence, relevant, appropriate person, credible reason, good timing, all gates pass)",
      "NO → HOLD / SUPPRESSED / HELD / EXPIRED (insufficient evidence, poor contact, weak fit, duplicate, recent outreach, unclear timing, no angle, suppressed, unverified, QA failed)",
      "Shadow mode → decision logged but not sent (orbit/service flag)",
      "Approvals honor hybrid vs autonomous vs approval mode — scheduler._needs_approval only hybrid for A/A+",
    ],
    whatComesOut: [
      "Gate decision {allowed, reasons[], checks[]} — auditable, returned by GET /outreach/messages/{id}/send-decision and used by email_service.claim_for_send",
      "Stage transition: COMPLIANCE_PENDING → SEND_READY | COMPLIANCE_FAILED | SUPPRESSED | HELD",
      "Hold reason persisted to qa_runs.failed_rules for review queue",
    ],
    realExample: {
      title: "ABC HVAC gate",
      body: "Confidence medium-high (P1), contact verified (apollo→ZeroBounce), not suppressed, no recent outreach, credible angle (dispatcher + ads + weak booking cites posting URL), mailbox healthy (sent 3/30), domain active, campaign active, sequence initial (step 0) → all 13 checks pass → allowed=true → gtm_stage SEND_READY. If contact were generic info@ (unverified) → email_verified false → allowed=false → COMPLIANCE_FAILED → HELD with reason 'email not provider-verified'.",
    },
    edgeCases: [
      "Duplicate company+contact → not_suppressed may pass but lead_eligible or history check would hold; dedupe at FIND already merged",
      "Recent outreach (contacted status) → lead_eligible false or sequence_state_ok false → hold for cooldown",
      "Suppressed email/domain/phone → hard BLOCK regardless of confidence; suppression table hard gate in code not just UI (spec §11.2)",
      "Follow-up step must match original mailbox → followup_mailbox_correct prevents split-mailbox thread break",
      "Legacy unmanaged messages (gtm_stage NULL) skip QA/compliance/stage checks — pre-existing flows unchanged but bypass controls",
    ],
    whatCanGoWrong: [
      "provider_available always True — dead check gives false confidence; real SMTP/Twilio failure only caught at send time",
      "within_sending_limits uses sent_today vs daily_send_limit but reset logic only in scheduler.get_daily_capacity — date rollover race shows sent_today=30 yesterday blocks today if sent_today_date stale (fallback date.today() masks but not elsewhere)",
      "_latest_qa ORDER BY created_at DESC LIMIT 1 vs qa_service ORDER BY created_at DESC, id DESC tie-break divergence → gate may read older QA than QA service wrote",
      "sequence_state_ok COALESCE(MAX(sent_at), to_timestamp(0)) — first send always allowed even if inbound exists before any outbound (reply before outreach not treated as prior conversation)",
      "Suppression phone normalization caller-dependent → stored normalized vs raw check bypass",
    ],
    howItConnects: {
      from: "DECIDE",
      to: "OUTREACH or HOLD",
      detail:
        "DECIDE drafts, GATE judges. Only SEND_READY/SCHEDULED stage may be claimed by email_service. GATE is the only path to SEND_READY; cannot be bypassed because claim_for_send calls can_send first and outbound_gate is enforced in code, not UI.",
    },
    whyItMatters:
      "Without this gate, autonomy becomes spam. With it, autonomy means observe→reason→decide→act when appropriate→stop when appropriate→escalate when appropriate.",
    advanced:
      "Modules: app/services/outbound_gate.py (13 checks, auditable), app/services/gtm_lifecycle.py (AUTHORIZED_SEND_STAGES), app/services/email_service.py (claim_for_send + idempotency), app/services/suppression.py (hard gate, global/email/phone/company); endpoints: GET /outreach/send-decision, POST /outreach/claim/{id}; tables: messages.gtm_stage, qa_runs, suppression, mailboxes, sending_domains; tests: test_email_gates.py, test_gtm_acceptance.TestComplianceFailureCannotSend.",
    trace: {
      backendModules: ["app/services/outbound_gate.py", "app/services/gtm_lifecycle.py", "app/services/suppression.py"],
      stateMachine: "COMPLIANCE_PENDING → SEND_READY | COMPLIANCE_FAILED | SUPPRESSED | HELD | SCHEDULED",
      agent: "GTM_QA (compliance), GTM_OUTBOUND (claim)",
      tables: ["messages", "qa_runs", "suppression", "mailboxes", "sending_domains"],
    },
  },
  {
    id: "outreach",
    index: 8,
    title: "OUTREACH",
    short: "Controlled sequence that reacts to behavior",
    icon: "↗",
    color: "linear-gradient(135deg,#10b981,#0ea5e9)",
    accent: "#10b981",
    whatItIs:
      "Outreach is not a blast. It is a controlled cadence that changes based on prospect behavior, with deterministic timing, mailbox assignment, and kill-switch.",
    whyExists:
      "Respect + deliverability. Behavior should always change the path. A sequence that ignores replies burns domain reputation and prospect trust.",
    whatEnters: [
      "Send-ready message + verified contact + mailbox assignment (originating_mailbox_id)",
      "Sequence config: initial + follow-ups (day 0/3/7/14/28), angle rotation, breakup honored, stop-on-reply",
      "Mailbox health, domain health, campaign allocation, business-hours guardrail",
    ],
    whatHappens:
      "Candidate passes GATE → APProvals queue (dashboard + Telegram cards: approve/edit/reject/push-to-phone). Operator approves → email_service.claim_for_send (idempotency + outbound_gate) → status sending → provider SMTP send → apply_send_result (sending→sent, gtm_stage SCHEDULED→SENT). Scheduler tick handles capacity (get_daily_capacity health-multiplied), campaign_allocation_filter, assign_mailboxes (lowest sent/effective ratio), next_available_slot (business hours + jitter). Follow-ups via schedule_followups (creates messages, inherits mailbox) + sequences.on_initial_sent (creates outbound_messages). Kill switch on any inbound reply → pause automation, purge from call queues, alert operator via kill_switch.",
    decisions: [
      "Is it time for next step per pacing, health, capacity, campaign cap, mailbox limit, business hours?",
      "Has prospect behavior changed the path? → reply → cancel queued follow-ups (check_followup_cancellation), unsubscribe → suppression, bounce → mailbox health downgrade + pause_on_bounce",
      "Which mailbox/domain to assign? → health-multiplied capacity, lowest ratio wins, deduplicated",
      "Follow-up mailbox must match original → outbound_gate enforces",
    ],
    whatComesOut: [
      "Send attempts with idempotency keys, observations (delivered/open/click/reply/bounce/complaint via email_events)",
      "State: waiting, follow-up queued (SCHEDULED), cancelled on reply/terminal/suppression, HELD on mailbox mismatch",
      "Activities timeline entries: email/call/sms/ai_action/system + audit_log",
      "Mailbox health update: sent_today++, bounce handling → degraded/paused if >2%",
    ],
    realExample: {
      title: "ABC HVAC outreach",
      body: "Day 0: approved initial about dispatcher + booking via mailbox hello@orbit-send1.com (organic1:30). Sent 10:15 ET (business hours OK). Day 3: no reply, capacity 28 remaining, follow-up angle (missed-call cost) queued via same mailbox. If reply 'not interested' on Day 1 → kill_switch deletes session_leads, marks messages rejected, outbound_messages queued cancelled within minutes, alerts operator via Telegram + dashboard toast + control-plane. Outbound sequence loop: send → wait → observe → react.",
    },
    edgeCases: [
      "Reply during follow-up wait → check_followup_cancellation purges queued outbound_messages (polling, not instant — minutes gap)",
      "Bounce/complaint → mailbox health downgraded, future sends paused via kill_switches JSON blob (concurrent writes race on global flags)",
      "Out-of-office auto-reply → reply_classifier tags OOO, records timing, follow up appropriately (don't suppress)",
      "Mailbox daily caps 20-30 per inbox, per-domain stagger, warmup 2-4 weeks required before volume (FR-28 dormant if not warmed)",
      "No-show sequence after booking → distinct state machine (not outreach)",
    ],
    whatCanGoWrong: [
      "Dual queues: messages vs outbound_messages split infra; scheduler walks outbound_messages while outreach walks messages → two dashboards show different reality, followupsEnrolled structurally not unified",
      "email_service.schedule_followups creates approved directly without approval mode check — violates FR-10 human approval in hybrid/autonomous",
      "claim_for_send UPDATE status='sending' before gates — gate failure _release_claim may race with due_sends poll, double-claim window",
      "Scheduler global_limit += domain_limit inside mailbox loop double counts → over-allocates capacity",
      "No per-inbox daily cold caps enforcement in send path despite spec §7.4 (mailboxes.daily_send_limit 30 default, not 20)",
      "Kill switch deletes session_leads + marks messages rejected but outbound_messages queued rows remain until polling → followups assignable for minutes after reply",
    ],
    howItConnects: {
      from: "OUTBOUND GATE",
      to: "UNDERSTAND RESPONSE (RESPONSE)",
      detail:
        "OUTREACH sends and then listens. Every send produces events that RESPONSE interprets. OUTREACH is the only stage that touches external SMTP/Twilio — all prior stages are internal reasoning. Its idempotency keys and health guards protect deliverability.",
    },
    whyItMatters:
      "This is the stage customers feel. A broken cadence (spam, ignored reply, wrong mailbox) damages brand permanently. Deterministic timing + human approval + behavior-reactive kill switch are what make outreach safe.",
    advanced:
      "Modules: app/services/email_service.py (approve→claim→send→followups→kill_switch), app/services/scheduler.py (tick, capacity, allocation, mailbox assign, business hours), app/services/sequences.py (cadence FSM), app/services/mailbox_health.py (.5 factor), app/routers/outreach.py (approvals, claim, send-result, classify-reply); tables: messages, outbound_messages, mailboxes, sending_domains, campaigns, activities; agent: GTM_OUTBOUND (60s), GTM_REPLIES (300s); safety: dry-run via mock SMTP fixtures, NO real sends without approval.",
    trace: {
      backendModules: [
        "app/services/email_service.py",
        "app/services/scheduler.py",
        "app/services/sequences.py",
        "app/services/mailbox_health.py",
      ],
      stateMachine: "SEND_READY → SCHEDULED → SENT (plus HELD/EXPIRED/SUPPRESSED on failure)",
      agent: "GTM_OUTBOUND + GTM_REPLIES",
      tables: ["messages", "outbound_messages", "mailboxes", "email_events", "activities"],
    },
  },
  {
    id: "response",
    index: 9,
    title: "UNDERSTAND RESPONSE",
    short: "What does prospect mean? — intent + next step",
    icon: "?",
    color: "linear-gradient(135deg,#6366f1,#ec4899)",
    accent: "#6366f1",
    whatItIs:
      "Understand what the prospect is trying to accomplish, not just classify the message. Classify into intent taxonomy, flag escalation, and recommend next action routing.",
    whyExists:
      "Wrong interpretation wastes the opportunity. A pricing question is not a rejection; a 'maybe later' is not a no; a 'wrong person, talk to X' is a lead not a loss. Intent before response prevents misplay.",
    whatEnters: ["Reply text + history + thread_id", "Previous opportunity profile and conversation state", "Full conversation history for context, previous questions/objections"],
    whatHappens:
      "Reply classification agent (n8n workflow reply-classification.json + backend email_service.classify_reply) parses intent. Deterministic routing per class (FR-13): INTERESTED → acknowledge & propose meeting; PRICE/QUESTION → notify human + draft for review; OBJECTION → understand concern + handle; NOT_INTERESTED → suppress + learn; BOOKING_REQUEST → booking link; HUMAN_REQUIRED → escalate immediately (attach packet). Universal kill switch: any inbound on any channel → pause all automation for lead, remove from call queues, alert operator. Activity timeline updated, task created for HUMAN_REQUIRED.",
    decisions: [
      "What is intent? 13-category taxonomy: interested, curious, pricing, details, objection, not_interested, wrong person, later, ready to book, existing conversation, unclear, proof, timing, industry fit, do_not_call (opt-out)",
      "Needs escalation? (high value P1, complex, sensitive, HUMAN_REQUIRED class, large deal, negotiation)",
      "Is this exploring, evaluating, or ready? Should Orbit continue or hand to human?",
      "Wrong person → find right contact via enriched suggestion, don't mark company do_not_call; later → record timing, nurture; unclear → ask clarifying question, don't assume",
    ],
    whatComesOut: [
      "Intent + escalation flag + next action recommendation (route: booking vs draft vs suppress)",
      "Kill switch fired (messages cancelled, session_leads deleted, alert emitted)",
      "Classification stored: reply intent + confidence + suggested response draft (needs human review)",
      "Lead status transition contacted→responded (kill switch fires here, all automation stops per FR-12)",
    ],
    realExample: {
      title: "ABC HVAC response — 6 variants",
      body: "Positive: 'Looks interesting, how does it work with ServiceTitan?' → intent=QUESTION, escalation=false, next=answer workflow + determine ready? → Converse. Objection: 'We already have a receptionist' → OBJECTION, next=handle 'AI augments, not replaces — after-hours + overflow' (HUMAN_REQUIRED false). Wrong person: 'Not me, talk to Jamie in ops' → WRONG_PERSON, next=re-identify with referral Jamie. Pricing: 'What does it cost?' → PRICE, escalation=true (high value), next=human notify. UNSUBSCRIBE: 'Remove me' → NOT_INTERESTED + do_not_call, suppression added, routed to archived. No reply → stays contacted, follow-up due.",
    },
    edgeCases: [
      "Unclear reply ('maybe??') → ask clarifying question, don't assume or advance to BOOK",
      "Wrong person with referral → re-identify using named referral (higher confidence than waterfall), don't suppress domain",
      "Angry response → immediate do_not_call + global suppression + alert; never argue",
      "Negative but polite → respect, suppress if requested, learn (signal quality for similar ICP may be low)",
      "Auto-reply OOO → don't fire full kill switch; record timing, follow up appropriately",
      "Multiple intents in one reply ('price? and can it do X?') → pick dominant, address both in suggested draft",
    ],
    whatCanGoWrong: [
      "Reply classification LLM delegated to n8n workflow with no backend fallback — if n8n down, replies queue but not classified, automation not paused until manual",
      "GET /events/pending and /events/poll no workspace scoping → tenant leak (intent events visible cross-workspace)",
      "Auto categorization confidence thresholds unused — low confidence still routes without human review",
      "Reply classification may miss CAN-SPAM unsubscribe intent phrase variant → suppressed check bypassed, illegal send",
      "Kill switch deletes session_leads and marks messages rejected but outbound_messages queued rows remain until poll → stale follow-ups still assignable for minutes",
    ],
    howItConnects: {
      from: "OUTREACH",
      to: "CONVERSE → BOOK",
      detail:
        "RESPONSE interprets the reply that OUTREACH caused, then CONVERSE continues the dialogue observing behavior. RESPONSE is the most important GTM step: misclassifying intent loses the meeting even if everything prior was perfect.",
    },
    whyItMatters:
      "This is where pipeline value is captured or lost. Correct interpretation moves to BOOK; incorrect interpretation (e.g., treating objection as rejection) discards a qualified opportunity.",
    advanced:
      "Modules: app/services/email_service.py (classify_reply, apply_classification, kill_switch), app/services/sequences.py (keyword classify), n8n/workflows/reply-classification.json (LLM classify), app/routers/outreach.py (classify-reply, apply/classification); taxonomy: 13 classes per spec §4.1 FR-13; tables: messages (inbound), activities, tasks, suppression; guard: universal kill switch (FR-12) enforced deterministically.",
    trace: {
      backendModules: ["app/services/email_service.py", "app/services/sequences.py", "n8n/workflows/reply-classification.json"],
      stateMachine: "contacted → responded → qualified_conversation | lost | archived",
      agent: "GTM_REPLIES (300s poll)",
      tables: ["messages", "activities", "tasks", "suppression"],
    },
  },
  {
    id: "converse",
    index: 10,
    title: "CONVERSE",
    short: "Remember what was said and respond accordingly",
    icon: "💬",
    color: "linear-gradient(135deg,#0ea5e9,#8b5cf6)",
    accent: "#0ea5e9",
    whatItIs:
      "Continue the conversation intelligently: remember history, answer questions, handle objections, provide relevant info, avoid repeating, and recognize when human should take over. Progression: Question → Answer → Clarification → Qualification → Next step.",
    whyExists:
      "Goal is clarity, not endless chat — move toward right outcome (BOOKED / QUALIFIED NOT READY / NOT A FIT) without looping, without asking for already-provided info, and without hallucinating.",
    whatEnters: [
      "Full conversation history (all outbound + inbound messages, activities, research profile)",
      "Prospect intent, previous answers, qualification notes, objections already discussed",
    ],
    whatHappens:
      "Contextual dialogue management: answer questions with evidence, handle objections with deterministic QA for compliance before any booking, provide relevant info, avoid repeating, avoid asking for already-provided info (e.g., service area). Recognize stages: exploring vs evaluating vs ready. When criteria met (interest + qualification + timing), propose meeting. When sensitive (pricing/legal/negotiation/high-value), escalate via HUMAN_REQUIRED task + briefing packet. State kept in conversation_state / activities timeline, not hidden chain-of-thought.",
    decisions: [
      "Is this exploring (wants details/proof), evaluating (comparing options), or ready (wants to book)?",
      "Should Orbit continue or escalate to human? → high-value, complex, sensitive, negotiation → escalate",
      "Is answer consistent with prior replies? → don't loop, don't contradict",
      "Qualification update: does new info change P1/P2/P3 tier?",
    ],
    whatComesOut: [
      "Contextual replies (drafted, QC'd, human-approved if needed), updated qualification",
      "Next step proposal: answer + follow-up question vs booking proposal vs escalation",
      "Conversation state persisted (activities timeline actor-labeled: human/agent/system)",
      "HUMAN_REQUIRED task + handoff packet draft if escalated",
    ],
    realExample: {
      title: "ABC HVAC converse",
      body: "Q: 'Does it work with ServiceTitan?' → A: 'Yes — Orbit integrates with ServiceTitan and similar. We capture the call, transcribe, and push booking/task to your system. What's your current booking flow like — do you use ServiceTitan scheduling directly?' → determines exploring vs ready. If sensitive: 'What does 24/7 cost for 50 calls/day?' → HUMAN_REQUIRED (pricing negotiation, high value), escalate with packet (company summary, hiring signal, weak booking proof, ServiceTitan interest). Never ask for service area again if already known (3 areas). Conversation history prevents re-asking.",
    },
    edgeCases: [
      "Repeated question → answer consistently, don't loop or vary claims",
      "Sensitive pricing/legal/compliance → escalate to human, don't guess at pricing or liability",
      "Prospect goes quiet after 2 exchanges → nurture track, don't spam; record timing, follow up via intent signals",
      "Contradictory info ('we have 1 location' vs '3 areas') → acknowledge, clarify, update company record, adjust qualification",
      "Wrong timing ('call me in 3 months') → QUALIFIED NOT READY, record timing, set nurture reminder, don't close",
    ],
    whatCanGoWrong: [
      "No deterministic QA for conversation replies before booking — only outbound_gate covers sends, not conversational replies (could send hallucinated pricing)",
      "State kept across multiple connections (conn, lead_id, ws) but no single transaction — partial failure leaves conversation_state inconsistent",
      "Inbound call routing + transcription pipeline (A9 Call Intelligence) not wired — conversation only covers email replies, not phone callbacks",
      "No battlecards / objection knowledge panel in dialer (PROPOSED per §5.5) — human handles objections without system support",
      "Unbound token growth if conversation history never summarized — no truncation/compaction, LLM context may overflow",
    ],
    howItConnects: {
      from: "UNDERSTAND RESPONSE",
      to: "BOOK / HANDOFF",
      detail:
        "CONVERSE is the interactive extension of RESPONSE: RESPONSE classifies one intent, CONVERSE carries the dialogue over multiple turns until outcome. Both observe behavior and both may trigger escalation. CONVERSE's only success is a correct outcome (BOOKED / QUALIFIED NOT READY / NOT A FIT) with explainable evidence.",
    },
    whyItMatters:
      "Bookings come from conversations, not blasts. A good CONVERSE moves a curious reply to a qualified meeting; a bad CONVERSE loops, hallucinates, or misses escalation and loses trust.",
    advanced:
      "Modules: app/services/email_service.py (classification), app/routers/outreach.py (draft responses for human review), app/services/llm.py (budget guard), n8n reply-classification; tables: messages (thread_id), activities, tasks; state: conversation_state via activities payload_json; guard: HUMAN_REQUIRED → Task assigned, operator notified via Telegram; future: Deepgram/Whisper transcription → A9.",
    trace: {
      backendModules: ["app/services/email_service.py", "app/routers/outreach.py", "app/services/llm.py"],
      stateMachine: "responded → qualified_conversation → meeting_booked (or lost/archived)",
      agent: "GTM_REPLIES + human",
      tables: ["messages", "activities", "tasks"],
    },
  },
  {
    id: "book",
    index: 11,
    title: "BOOK / HANDOFF",
    short: "Turn cold business into real conversation",
    icon: "✓",
    color: "linear-gradient(135deg,#10b981,#059669)",
    accent: "#10b981",
    whatItIs:
      "Ultimate objective is not sending messages — it's qualified meetings. Human should get useful opportunity, not empty calendar event, with a handoff packet explaining why qualified.",
    whyExists:
      "Salesperson time is the scarcest resource. A packet with company summary, trigger/signal, likely problem, history, intent, objections, qualification notes lets the human have a relevant first call instead of discovery from scratch. Every outcome (BOOKED / QUALIFIED NOT READY / NOT A FIT) is equally valid if correctly decided.",
    whatEnters: [
      "Qualified conversation, prospect intent (READY TO BOOK / interested+qualified+timing)",
      "Opportunity profile + conversation history + questions/objections + qualification notes",
    ],
    whatHappens:
      "Propose meeting (booking link via Cal.com-style embed / agent booking link, reminders), confirm, notify appropriate person, update opportunity, summarize conversation, highlight needs/objections, explain why qualified, prepare salesperson. Lead state transition: qualified_conversation → meeting_booked → meeting_held → proposal → won/lost. Activities + audit_log updated. Winning outcome feeds learning loop (outcome→ interpretation → evidence → future adjustment). No-show/reschedule state transitions handled via meeting status.",
    decisions: [
      "BOOKED → prepare for meeting (briefing packet + calendar + reminder)",
      "QUALIFIED NOT READY → nurture/monitor later (timing recorded, intent signal watched)",
      "NOT A FIT → suppress/close/learn (wrong ICP, poor fit confirmed via conversation)",
      "Outcome must be explainable: what was available, what decision made, what happens next — without exposing hidden chain-of-thought (structured decision evidence only)",
    ],
    whatComesOut: [
      "Meeting record (meetings table: scheduled_at, timezone, status booked/held/no_show, calendar_link, brief) + opportunity stage update",
      "Handoff packet: company summary, contact, trigger/signal (e.g., dispatcher hiring URL), likely problem, history, intent, objections, qualification notes, recommended context/openers",
      "Lead state meeting_booked, hot-lead alert (Telegram + dashboard + queue priority injection for 3+ opens/form fill)",
      "Learning signal: booked + angle + source → positive reinforcement for future targeting",
    ],
    realExample: {
      title: "ABC HVAC booking",
      body: "Interest ('How does booking integration work?') + qualified P1 + timing now → propose times via booking embed, book Thu 10 ET, notify owner, packet includes: HVAC (3 areas, 4.6★, 82 reviews), trigger (dispatcher posting 3d old + Google Ads + weak booking audit), likely scheduling pressure (evidence: posting + site findings), owner contact verified, asked about ServiceTitan integration (needs follow-up), no objections, medium-high confidence, recommended opener: 'dispatcher hiring + areas suggests call volume pressure — confirm?'. Close rate context: prior similar angle 18% reply, high booking among viewed (learning feeds back).",
    },
    edgeCases: [
      "No-show → record no_show, follow up, learn (maybe intent strong but booking friction high)",
      "Wrong time ('not for 3 months') → QUALIFIED NOT READY, don't close — nurture with timing, suppress not needed",
      "High-value but not ready → keep warm, don't spam; monitor hiring_intent expiry (60d) and re-approach if new signal",
      "Booking via wrong channel (phone call-back not email) → inbound routing PREFERRED but missing — manual attribution required",
      "Double-book race (prospect books via both email link + Calendly) → idempotency key on meeting insert prevents duplicate",
    ],
    whatCanGoWrong: [
      "Booking via Cal.com embed not wired — FixtureCalendar never overridden, BOOK/HANDOFF missing real calendar provider registration",
      "Meeting brief generation missing — pre-call research not linked to booking, handoff packet incomplete",
      "Booking link in dialer not wired — no inline booking during call (PREFERRED per spec)",
      "lost→archived and unreachable→archived reachable but won terminal prevents win-back (no reset path; terminal states permanent with no operator override)",
      "Hot-lead handoff queue priority injection alerts but not idempotently deduplicated — duplicate alerts on same lead if 3+ opens fires repeatedly",
    ],
    howItConnects: {
      from: "CONVERSE",
      to: "LEARN (feedback)",
      detail:
        "BOOK is the conversion point that LEARN measures. Every booking (or qualified not ready / not a fit) becomes evidence that LEARN interprets to adjust future FIND→QUALIFY→DECIDE. BOOK's packet is also the trace that makes the decision explainable after the fact (spec §12): what happened, why, what info available, what decision, what next.",
    },
    whyItMatters:
      "Revenue starts here. A perfect upstream but broken BOOK (no-show handling, missing brief, double-book) still loses the deal. BOOK is where automation stops and human judgment (close) begins.",
    advanced:
      "Modules: app/routers/opportunity.py, app/services/pipeline.py, app/routers/leads.py (transition endpoint), meetings/opportunities tables; calendar: Google/Cal.com provider via FixtureCalendar (TBD); lead states: meeting_booked (self-loop for reschedule), meeting_held, proposal, won/lost; observable: activities timeline + meetings + audit_log (actor user/agent/system, before/after hash).",
    trace: {
      backendModules: ["app/routers/leads.py", "app/routers/opportunity.py", "app/services/opportunity.py"],
      stateMachine: "meeting_booked → meeting_held → proposal → won | lost → archived",
      agent: "Human (close) + system (alerts)",
      tables: ["meetings", "opportunities", "activities", "audit_log"],
    },
  },
  {
    id: "learn",
    index: 12,
    title: "LEARN",
    short: "Every outcome becomes evidence → better targeting",
    icon: "↻",
    color: "linear-gradient(135deg,#f59e0b,#ef4444)",
    accent: "#f59e0b",
    whatItIs:
      "Every GTM outcome becomes evidence that improves next decision. The system continuously improves by distinguishing OBSERVATION from INTERPRETATION from DECISION from LEARNING, without letting one bad outcome rewrite behavior.",
    whyExists:
      "Without learning, GTM is static and repeats mistakes. With it, it compounds: better targeting, qualification, messaging, timing, prioritization, contact selection, signal interpretation over time. Learning is evidence-based and appropriately conservative (not one anecdote).",
    whatEnters: [
      "Outcomes: replies, no replies, positive/negative, meetings booked/missed/held/no-show/won/lost",
      "Signals: wrong ICP, bad contacts, objections, unsubscribes, signal quality, message performance per variant/angle/source",
      "System metrics: source quality, reply rate per signal, qualification rate per source, booking rate per role/angle, unsubscribe rate per angle",
    ],
    whatHappens:
      "Interpret: what does outcome tell us? Examples: high response to hiring-pressure messaging → hiring signals valuable for ICP; many positives from ops managers → strong contact role; high interest but low booking → conversation→meeting needs fix; many fails from source → downgrade source; high unsubscribe from angle → pause angle. Loop: Outcome → interpretation → evidence (store scores, provider_usage, agent_runs.cost, mailbox_health, audit_log) → future adjustment (queue ordering, prompt optimization, signal expiry weighting). Conservative: require N observations before changing; don't auto-rewrite prompts on one outcome. Winner analysis + feature extraction + template library (FR-24 PROPOSED) wired via control-plane analytics + audit_history. Daily digest (Sales Manager A10) flags stale leads, missing follow-ups, anomalies, converting-whats.",
    decisions: [
      "What to change for future prospects? → targeting (which signals/ICPs to prioritize), qualification thresholds, messaging variants, timing (when to re-approach), contact selection (which titles work)",
      "Keep vs change: weigh recency, sample size, strength — small sample → don't overfit, conflicting outcomes → weigh evidence weight",
      "Negative learning: suppress poor fits/sources/angles, don't just chase positives",
      "Observation vs interpretation vs decision vs learning — keep them distinct; log each separately for audit",
    ],
    whatComesOut: [
      "Better targeting (which FIND sources to weight), qualification (thresholds), messaging (winner variants in template library)",
      "Timing/prioritization adjustments (intent reweight, signal expiry tuning 30d vs 60d, recency decay)",
      "Contact selection (title ranking learning), signal interpretation (which hiring roles are truly high-intent)",
      "Dashboard analytics: funnel conversion by stage, per-vertical/per-source performance, AI cost over time (control-plane)",
    ],
    realExample: {
      title: "ABC HVAC learn",
      body: "Outcome: booked from dispatcher + weak booking angle (P1) → reinforce that combination for similar HVAC with hiring + ads + weak booking. Stored as scores history + provider success + agent_runs. Interpretation: hiring dispatcher is high-intent for this ICP (HVAC 3 areas). Decision: weight dispatcher + ads signals higher for HVAC vertical in next FIND batch. If ABC HVAC had been NOT A FIT (wrong size: national chain 12 locations → rejected_too_large) → negative learning: downgrade similar national profiles at QUALIFY, don't source franchise/mega. Both outcomes logged to audit_log and visible in Analytics page (funnel, per-source).",
    },
    edgeCases: [
      "Small sample (n=3) → don't overfit, need more evidence before rewriting system behavior; require statistical significance",
      "Conflicting outcomes (5 dispatcher->booked, 2 dispatcher->unsubscribe) → weigh recency and strength, not average blindly",
      "Negative learning only → suppress poor fits/sources, don't just chase positives; prevents amplification loop",
      "Seasonality (HVAC demand spikes summer) → signal quality varies by season, don't permanently downgrade off-season sources",
      "Provider hallucination risk → if evidence bundle weak, learning marks source low-confidence, not wrong interpretation",
    ],
    whatCanGoWrong: [
      "Outcome tracking not closed-loop (no winner analysis/prompt evolution wired) — learning is PROPOSED (Phase 2+) but not implemented past audit_history last 24h; email_events bounce/open/reply aggregation not feeding scores",
      "Budget guard llm.check_budget reads agent_runs.cost_usd but n8n+hiring_signals write via job_queue handlers that bypass llm.record_run → spend under-counted, daily $10 budget not enforced",
      "One bad outcome auto-rewrites behavior if LEARNING threshold too low — system must be conservative but currently no N threshold enforced",
      "learning loop edge: booking + angle + source positive, but similar ICP next batch may be geographically different (Gainsville vs Greensboro) — signal locality matters",
      "Daily digest A10 Sales Manager not wired beyond audit run/history — stale leads/missing follow-ups/anomalies not automatically flagged without operator polling",
    ],
    howItConnects: {
      from: "BOOK/HANDOFF (and every stage)",
      to: "FIND (future targeting)",
      detail:
        "LEARN is the return edge (booking→discovery 'every outcome → better targeting' dashed) that closes the loop. Every stage's outcome is evidence: FIND source quality, UNDERSTAND website gap detection accuracy, QUALIFY threshold calibration, IDENTIFY title success, DECIDE angle performance, OUTREACH deliverability, RESPONSE classification accuracy, CONVERSE handoff quality, BOOK close rate.",
    },
    whyItMatters:
      "Without LEARN, GTM is a static pipeline that repeats mistakes at scale. With it, it compounds — each booked meeting makes the next FIND→DECIDE smarter. Spec §4.2 FR-24 explicitly designs this as Phase 2+ to avoid premature optimization, but foundation (scores history, provider_usage, audit_log) already exists.",
    advanced:
      "Modules: app/services/intent_engine.py (reevaluate history component 10%), app/services/opportunity.py (EMV static — needs learning to become dynamic), app/services/mailbox_health.py (5-factor → daily GTМ health audit), app/routers/control_plane.py (overview/campaigns/audit), app/agents/ledger.py (agent_runs cost/latency), control_plane analytics + audit_history; tables: scores, agent_runs, provider_usage, activities, audit_log; principle: evidence-based, conservative, distinguish observation/interpretation/decision/learning (never one bad outcome auto-rewrites).",
    trace: {
      backendModules: ["app/services/intent_engine.py", "app/services/opportunity.py", "app/routers/control_plane.py", "app/agents/ledger.py"],
      stateMachine: "won | lost | archived → re-entry via new FIND batch (no direct transition — new Company/Lead for similar profile)",
      agent: "A10 Sales Manager (daily digest, frontier tier)",
      tables: ["scores", "agent_runs", "provider_usage", "audit_log", "activities"],
    },
  },
];

export const GTM_BRAINS: GtmBrain[] = [
  {
    id: "leads",
    title: "GTM Leads",
    subtitle: "Who should Orbit pursue?",
    icon: "L",
    color: "linear-gradient(135deg,#0ea5e9,#6366f1)",
    whatItIs: "FIND → UNDERSTAND → QUALIFY → IDENTIFY (Company → Person → Verified contact) + Opportunity hypothesis",
    whatItDoes:
      "Find businesses, understand them, identify decision-maker contacts, match company/contact, qualify (ICP fit + evidence + fit_status), prioritize (P1/P2/P3), build opportunity, decide if worth pursuing. Deterministic scoring before LLM, fail-closed on missing evidence.",
    whatItDoesNot:
      "It does NOT send outreach. It produces Target + Contact + Qualification + Priority + Rationale — the hypothesis that GATE judges and OUTREACH acts on. Sending is a separate brain's job.",
    output: "TARGET + CONTACT + QUALIFICATION + PRIORITY + RATIONALE",
    example:
      "ABC HVAC: Leads finds HVAC (Maps), understands 3 areas + hiring dispatcher + weak booking, finds owner (Apollo→ZeroBounce verified), qualifies P1 HIGH (fit 8/10, intent 35, priority 78), builds hypothesis (scheduling pressure → AI receptionist + booking).",
    trace: ["app/services/pipeline.py", "app/services/scoring.py", "app/services/enrichment.py", "app/agents/registry.py:GTM_LEADS"],
  },
  {
    id: "intent",
    title: "GTM Intent",
    subtitle: "What is happening with this business?",
    icon: "I",
    color: "linear-gradient(135deg,#8b5cf6,#ec4899)",
    whatItIs: "OBSERVE → INTERPRET → DETECT timing signals (hiring, growth, expansion, website, advertising, operational, buying signals)",
    whatItDoes:
      "Observe changes (job postings, ads, site changes), interpret signal → possible problem → opportunity (e.g., hiring dispatcher → call pressure → scheduling bottleneck → AI receptionist angle), detect why now (freshness, recency decay, signal score 0-100). Signal ≠ opportunity until context fits.",
    whatItDoesNot:
      "It does NOT qualify ICP fit alone — GTM Leads does that. Intent provides timing context ('why now') that Leads uses to prioritize. Intent EMAIL ONLY for hiring queue.",
    output: "SIGNAL → INTERPRETATION → POSSIBLE PROBLEM → OPPORTUNITY (why now?)",
    example:
      "Signal: hiring dispatcher (fresh 3d, high intent) → interpretation: call handling pressure → problem: scheduling/response bottleneck → opportunity: 24/7 AI receptionist + missed-call recovery. High ads + weak booking → demand generation but losing conversions → booking automation angle. Detecting signal is not pitching — requires contextual fit.",
    trace: [
      "app/services/hiring_signals.py",
      "app/services/intent_engine.py",
      "app/services/website_intel.py",
      "app/agents/registry.py:GTM_INTENT",
    ],
  },
];

export const GTM_PRINCIPLES: GtmPrinciple[] = [
  { n: 1, title: "Evidence before action", detail: "Observable business info (hiring URL, site findings, ads) forms the reason for outreach — never invent facts. Hard rule #3 evidence mandatory." },
  { n: 2, title: "Context before messaging", detail: "Message reflects prospect's situation, not Orbit's capabilities. One CTA, evidence opener, <75 words, no banned phrases." },
  { n: 3, title: "Qualification before escalation", detail: "Not every business gets same attention. P1 → send, P2 → review, P3/P4 → monitor/nurture. Enrichment gated on qualified only." },
  { n: 4, title: "Intent before response", detail: "Understand what prospect means before deciding reply. 13-class taxonomy; HUMAN_REQUIRED → escalate; wrong_person → re-identify, don't suppress." },
  { n: 5, title: "Behavior changes the path", detail: "Replies, silence, objections, timing alter next action. Kill switch on any reply pauses all automation instantly; follow-ups cancelled; sequence reacts." },
  { n: 6, title: "Every action has outcome", detail: "Track what happened to improve next decision. Activities timeline (actor human/agent/system), audit_log, scores history, provider_usage feed LEARN." },
  { n: 7, title: "Humans where judgment matters", detail: "Orbit automates research/monitoring/outreach; humans handle high-value judgment, complex relationships, negotiation, closing. Approval required before send (FR-10)." },
];

export const GTM_DECISION_TRANSPARENCY = {
  title: "Decision Transparency — Explain why",
  detail:
    "For any qualified decision, Orbit can answer: WHAT HAPPENED? WHY? WHAT INFO AVAILABLE? WHAT DECISION? WHAT NEXT? Structured evidence, not hidden reasoning. Click 'Why?' on qualifies to see: ICP fit, need evidence, timing, contact quality, relevant service, confidence → 'High enough confidence to proceed' vs 'Hold: insufficient evidence'. Observable factors, not black box.",
  example: "Explain why — ABC HVAC qualified? → ICP fit: strong (HVAC, 3 areas, local, owner-operated). Need: strong (dispatcher + ads + weak booking). Timing: medium-high (hiring now 3d). Contact: verified owner (Apollo→ZeroBounce). Service: AI receptionist / booking. Confidence: medium-high → HIGH-VALUE FIT — worth contacting. Evidence cites posting URL + website audit.",
};

// Search helper — powers global search across stages
export function searchStages(query: string, stages: GtmStage[] = GTM_STAGES): GtmStage[] {
  const q = query.toLowerCase().trim();
  if (!q) return stages;
  return stages.filter((s) => {
    const hay = [
      s.title,
      s.short,
      s.whatItIs,
      s.whyExists,
      s.whatHappens,
      s.whyItMatters,
      s.howItConnects.detail,
      ...s.whatEnters,
      ...s.decisions,
      ...s.whatComesOut,
      ...s.edgeCases,
      s.realExample.title,
      s.realExample.body,
      ...s.whatCanGoWrong,
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

// For testing / verification
export const GTM_STAGE_IDS = GTM_STAGES.map((s) => s.id);
export const GTM_LEARN_STEPS = GTM_STAGES.length; // 12
