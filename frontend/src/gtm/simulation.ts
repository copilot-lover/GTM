/**
 * ABC HVAC — Complete Prospect Simulation
 * Synthetic prospect walking end-to-end through the GTM.
 * Useful for onboarding, testing, and demo without real data.
 *
 * Characteristics: local service business, multiple service areas,
 * active advertising, hiring dispatcher, imperfect website,
 * owner/operations manager, plausible operational pressure.
 */

export interface SimulationStep {
  stage: string;
  stageTitle: string;
  whatOrbitKnows: string[];
  whatOrbitDoesntKnow: string[];
  signalFound: string;
  howItInterprets: string;
  decision: string;
  whyDecision: string;
  informationPassedForward: string[];
  // Conversation simulation extras
  conversation?: {
    prospectSays: string;
    intent: string;
    orbitReplies: string;
    nextAction: string;
  };
}

export const ABC_HVAC_PROFILE = {
  name: "ABC HVAC",
  tagline: "Local HVAC • 3 service areas • Greensboro, NC",
  website: "abchvac.example.com (weak booking flow, no chatbot)",
  ads: "Google Ads active (Service Areas: Greensboro, High Point, Winston-Salem)",
  hiring: "Dispatcher posting — posted 3 days ago — $18–22/hr — 'answer 50+ inbound calls/day, schedule service appointments, coordinate technicians'",
  reviews: "4.6★ 82 reviews, 3.2% monthly growth",
  tech: "Single location, family-owned appearance, owner visible on site, 6-10 employees proxy",
  decisionMaker: "Owner: Maria Chen (found via Apollo 92% confidence, verified ZeroBounce)",
  phone: "+13365551234 (normalized E.164)",
  emailStatus: "verified",
  operationalPressure: "Inbound demand up (ads + seasonal), manual scheduling, after-hours missed calls likely (no after-hours booking)",
  confidence: "medium-high",
  score: { fit: 8, intent: 78, priority: 78, tier: "P1", qualification: "HIGH-VALUE FIT" },
};

export const ABC_HVAC_SIMULATION: SimulationStep[] = [
  {
    stage: "find",
    stageTitle: "FIND",
    whatOrbitKnows: [
      "Business name: ABC HVAC, Greensboro NC",
      "Website exists (abchvac.example.com)",
      "Google Maps listing active, 3 service areas mentioned",
      "Job posting activity detected (dispatcher)",
    ],
    whatOrbitDoesntKnow: [
      "Whether booking flow is weak (needs crawl)",
      "Whether owner is decision maker (needs enrichment)",
      "How strong demand is (needs ads + hiring context)",
    ],
    signalFound: "Maps + JSearch hiring signal (dispatcher, fresh 3d, source_url logged)",
    howItInterprets: "Raw candidate — not yet a judgment. Deduplicated SHA-256(name|city|state)=ABC HVAC|Greensboro|NC. Created Company + Lead status=new with source lineage.",
    decision: "CREATE CANDIDATE → status=new, flag ready to UNDERSTAND",
    whyDecision: "Enough info to evaluate (name+location+site+active). Passes broad ICP filter (home-services, local). Active per hiring recency.",
    informationPassedForward: ["Company.id", "Lead.id status=new", "source_url + collected_at", "initial profile: HVAC, 3 areas, hiring flag"],
  },
  {
    stage: "understand",
    stageTitle: "UNDERSTAND",
    whatOrbitKnows: [
      "HVAC, home-services vertical, 3 areas = local (not franchise)",
      "Website crawl: no chatbot, mobile 62/100, CTA weak, after-hours no booking, forms slow (website_findings)",
      "Tech signals: WordPress, single location, owner visible",
      "Reviews 4.6★ 82 (steady demand), Google Ads active",
    ],
    whatOrbitDoesntKnow: [
      "Who exactly is dispatching today (owner vs manager?)",
      "Call volume per day (proxy: 50+ from posting)",
      "Current booking software (ServiceTitan? Housecall?)",
    ],
    signalFound: "Website audit findings + tech signals + reviews aggregated into enriched business understanding",
    howItInterprets: "Growing service business with inbound-demand signals. Hiring dispatcher = strain proxy. Weak booking = conversion loss risk. Relevant for: AI receptionist, missed-call recovery, booking automation.",
    decision: "ENRICH → write companies.tech_signals + leads.website_findings, set owner_operator_confidence=68",
    whyDecision: "Deterministic rules before LLM; never hallucinate. Evidence present (site + hiring + ads + reviews) → context sufficient to interpret signals.",
    informationPassedForward: ["Enriched company (tech_signals, website_findings, reviews)", "ICP relevance hint: qualified-potential", "Evidence bundle for QUALIFY"],
  },
  {
    stage: "qualify",
    stageTitle: "QUALIFY",
    whatOrbitKnows: [
      "ICP fit: single-location +3, owner visible +3, family +2, simple site +2 = high (8/10)",
      "Need: dispatcher hiring + active ads + weak booking = strong need evidence",
      "Timing: hiring fresh 3d → high timing, recency 0.9, signal_score 78",
      "Contactability: owner exists (enrich later), confidence medium-high",
    ],
    whatOrbitDoesntKnow: ["Verified email yet (needs IDENTIFY)", "Exact pain severity (needs OPPORTUNITY)", "Behavioral response likelihood (LEARN prior: HVAC dispatcher→P1 books 18%)"],
    signalFound: "Composite: hiring_intent_score 78 + ICP 8/10 + timing 0.9 → priority 78 (P1)",
    howItInterprets: "Fit + Need + Timing + Confidence = P1 HIGH-VALUE FIT. Deterministic: 0.4*intent(0.78)+0.3*fit(0.8)+0.2*contact(0.6)+0.1*history(0.5)=0.78 → P1. Threshold ≥6 passes; evidence mandatory cited (posting URL + site audit).",
    decision: "HIGH-VALUE FIT → advance to IDENTIFY (P1 85-100 speed-to-lead, this 78 borderline P1 but intent fresh pushes it)",
    whyDecision: "Observable factors justify proceed: strong ICP, meaningful need, good timing, active. Explainable contributions: intent 31.2pts + fit 24pts + contact 12pts + history 5pts = 78.",
    informationPassedForward: ["priority_score 78, tier P1, fit_status=qualified", "contributions[] for why-panel", "evidence bundle + hiring_posting_url"],
  },
  {
    stage: "identify",
    stageTitle: "IDENTIFY RIGHT PERSON",
    whatOrbitKnows: ["Ops + hiring pressure angle → Owner or Operations Manager most relevant", "Company qualified P1 → worth waterfall cost"],
    whatOrbitDoesntKnow: ["Which specific ops manager if owner delegates (fallback to Owner)"],
    signalFound: "Title ranking: Owner (rank 1) > GM (10) > Ops Manager (12) — angle matches Owner/ops",
    howItInterprets: "Waterfall priority apollo>hunter>clearbit: Apollo finds Maria Chen owner, 92% confidence. ZeroBounce verifies → verified. Suppression check clear (global+email+phone+company). Generic info@ also found but discarded per rule.",
    decision: "OWNER Maria Chen — verified contact, decision maker, care-about: scheduling pressure",
    whyDecision: "Highest-ranked title for ops problem, verified email present, not suppressed, not duplicate. Fail-closed: unverified generic would HOLD rather than send.",
    informationPassedForward: ["contacts.id Maria Chen, email verified, confidence 92%", "leads.contact_id linked (pipeline.apply_enrichment atomic)", "suppression clear, DNC clear"],
  },
  {
    stage: "opportunity",
    stageTitle: "BUILD OPPORTUNITY",
    whatOrbitKnows: [
      "Company + decision maker + signals + website observations full context",
      "Primary problem hypothesis: inbound demand creating scheduling/response pressure",
      "Signal chain: hiring dispatcher (fresh) + active ads + weak booking → likely missed calls + scheduling bottleneck",
      "Confidence medium-high, angle strength high",
    ],
    whatOrbitDoesntKnow: ["Whether they already use ServiceTitan (avoid assumption listed)", "Exact call volume (don't claim 50, cite posting says 50+)", "Current after-hours handling"],
    signalFound: "research_reports synthesized: business_data + website_findings + hiring_signals + reviews → research_report with citations",
    howItInterprets: "Opportunity composite 6-component: icp_fit 8→20pts, intent 78→25pts, severity (keyword 'booking/scheduling')→15pts, contactability verified→10pts, recency fresh→10pts, history→5pts = 85/100 tier A. EMV $4.45 default. PAIN_TO_OFFER: scheduling pressure → AI receptionist (matches primary pain deterministically). Avoid-assumptions: ServiceTitan unknown, volume proxy not fact.",
    decision: "OPPORTUNITY hypothesis: Growing HVAC, dispatch strain, booking friction → AI receptionist + booking automation angle, Owner Maria, evidence citations included, confidence medium-high, reason NOW: hiring + ads = active investment + strain",
    whyDecision: "Credible evidence-backed hypothesis; every claim cites source (posting URL, site audit). Offer maps to primary pain per hard rule; fail if mismatch. Profile is single source downstream READs.",
    informationPassedForward: ["research_reports row (citations)", "scores row tier A 85, EMV", "recommended_offer=AI receptionist, primary_pain=scheduling pressure, evidence[], avoid_assumptions[]"],
  },
  {
    stage: "decide",
    stageTitle: "DECIDE WHAT TO SAY",
    whatOrbitKnows: ["Opportunity profile + Owner + hiring posting URL + weak booking proof", "Evidence: dispatcher post 3d old, ads active, site no chatbot"],
    whatOrbitDoesntKnow: ["Whether Maria reads email vs phone preferred (will test)"],
    signalFound: "Angle selection: lead-response + missed-call + hiring-replacement + booking automation — strongest is hiring → call pressure → booking gap",
    howItInterprets: "Map signal+service+person→ contextual angle. Generic 'learn about AI services' would fail QA GENERIC_COPY. Contextual: cites hiring dispatcher + promoting new areas → scheduling pressure. Structure: Fact (hiring + areas), Inference (more calls/pressure), Offer (Orbit helps respond/qualify/book), Question (worth brief intro?). <75 words, one CTA, evidence opener.",
    decision: "DRAFT: Subject 'Hiring a dispatcher in Greensboro?', 73 words, body cites posting, one CTA, follow-up angle 'missed-call cost' reserved for sequence step 1",
    whyDecision: "Evidence opener + plausible outcome + single CTA + no invented facts + banned-phrase free. Pipeline validates length + 4-sentence + CAN-SPAM block. Draft only — never auto-send.",
    informationPassedForward: ["messages row pending_approval, gtm_stage COPY_GENERATED→QA_PENDING", "subject + body + follow_up_angle", "personalization_notes: dispatcher + weak booking"],
  },
  {
    stage: "gate",
    stageTitle: "OUTBOUND GATE",
    whatOrbitKnows: [
      "Confidence P1 78 + verified contact + credible angle + posting citation",
      "No duplicate, no recent outreach (first contact), not suppressed",
      "Mailbox organic1:30 healthy (3/30 today), domain active, campaign active",
    ],
    whatOrbitDoesntKnow: ["Whether Maria will reply unsubscribe (will be handled by RESPONSE kill switch)"],
    signalFound: "13 checks audit: all pass",
    howItInterprets: "can_send audit: lead_eligible pass (qualified), contact_eligible pass (verified not opted_out), not_suppressed pass, email_verified pass, copy_qa_passed pending? will be checked after QA_PASSED, compliance_passed pending, stage_authorized false until COMPLIANCE→SEND_READY, mailbox_healthy pass, domain_healthy pass, within_limits pass 3/30, provider_available pass, campaign_active pass, sequence_state_ok pass (step 0), followup_mailbox_correct pass (step 0). Currently QA_PENDING → gate would hold until QA/COMPLIANCE pass.",
    decision: "After QA_PASSED + COMPLIANCE_PENDING→SEND_READY: allowed=true → stage SEND_READY, ready for operator APPROVAL queue",
    whyDecision: "All structural gates pass deterministically; auditable reasons[] empty, checks[] 13/13 passed. Fail-closed means any single FAIL would HOLD with reason persisted to qa_runs.failed_rules for human review.",
    informationPassedForward: ["Gate decision {allowed:true, reasons:[], checks[13]}", "gtm_stage SEND_READY", "hold_reason null (or reason if held)"],
  },
  {
    stage: "outreach",
    stageTitle: "OUTREACH",
    whatOrbitKnows: ["Send-ready + verified + GATE passed + operator APPROVED", "Mailbox assigned hello@orbit-send1.com (lowest ratio)", "Sequence: initial Day0 + followups Day3/7/14 business hours"],
    whatOrbitDoesntKnow: ["Whether email lands inbox vs spam (health may downgrade if bounce)", "Whether Maria replies within 3 days (behavior will react)"],
    signalFound: "Capacity: health-multiplied 28 remaining, business hours OK 10:15 ET, idempotency key generated",
    howItInterprets: "Scheduler assigns mailbox lowest sent/effective ratio, next_available_slot business hours + jitter, claim_for_send re-checks outbound_gate, status sending→sent, gtm_stage SCHEDULED→SENT, followups scheduled via same mailbox (inherit). Activities logged, audit_log updated.",
    decision: "SEND Day0: initial about dispatcher + booking, delivered, waiting. Day3 follow-up queued (missed-call cost angle). Reactive: if reply → cancel queued followups via check_followup_cancellation; if bounce → mailbox degraded → pause; if OOO → record + delay.",
    whyDecision: "Deterministic timing + mailbox health + business hours + kill switch listening. Operator approved once, system handles cadence but reacts to behavior. Idempotency prevents double-send on retry.",
    informationPassedForward: ["messages status sent, gtm_stage SENT, sent_at", "Follow-ups SCHEDULED via same mailbox", "email_events pending delivery/open/click", "activities: email sent (system)"],
  },
  {
    stage: "response",
    stageTitle: "UNDERSTAND RESPONSE",
    whatOrbitKnows: ["Reply received: 'How does this work with our booking process? We use ServiceTitan.' + history (initial + context)"],
    whatOrbitDoesntKnow: ["Whether they are ready to book or still exploring (needs CONVERSE clarification)"],
    signalFound: "Reply classification: intent=QUESTION (wants details/proof), escalation=false, confidence 0.82",
    howItInterprets: "Taxonomy QUESTION → wants details/proof, not yet ready to book. Deterministic routing: notify human + draft for review, don't auto-book, don't suppress. Kill switch fired: all automation paused for lead, session_leads deleted, operator alerted via Telegram + dashboard 'Response & Conversation · intent: QUESTION' + task created.",
    decision: "CLASSIFY: QUESTION (wants ServiceTitan integration details) → next: CONVERSE answer workflow, determine exploring vs evaluating vs ready; lead status contacted→responded",
    whyDecision: "13-class taxonomy; QUESTION requires answer + follow-up before booking. HUMAN_REQUIRED false (not pricing negotiation yet). Observable: reply text + prior profile + ServiceTitan unknown now known → update company record.",
    informationPassedForward: ["intent QUESTION, escalation false, confidence 0.82", "kill_switch fired, automation paused", "Task: answer ServiceTitan question, suggested draft pending human review", "Lead status responded"],
    conversation: {
      prospectSays: "How does this work with our booking process? We use ServiceTitan.",
      intent: "QUESTION — wants details / proof (ServiceTitan integration)",
      orbitReplies: "Yes — Orbit integrates with ServiceTitan and similar. We capture the call, transcribe, and push booking/task to your system. What's your current booking flow like — do you use ServiceTitan scheduling directly? [HUMAN_REVIEWED before send]",
      nextAction: "Answer + clarify → determine exploring vs ready → if ready → BOOK",
    },
  },
  {
    stage: "converse",
    stageTitle: "CONVERSE",
    whatOrbitKnows: ["Full history: FIND→OUTREACH + reply thread + ServiceTitan interest + owner Maria + ops pressure angle", "Previous answer about integration, prospect follow-up question pending"],
    whatOrbitDoesntKnow: ["Budget/timeline/authority to decide today (needs qualification)"],
    signalFound: "Dialogue progression: Question answered → now asking about current booking flow to qualify timing",
    howItInterprets: "Continue conversation: remember ServiceTitan already mentioned, don't ask service area again (3 areas known), answer consistently, avoid hallucinating pricing, recognize exploring vs evaluating vs ready. Sensitive pricing → would escalate, but this question safe to answer.",
    decision: "CONTINUE: contextual reply handling objection/interest, qualify gently, propose next step if ready. If prospect says 'What does it cost for 50 calls/day?' → would escalate HUMAN_REQUIRED (pricing negotiation, high value P1) with handoff packet.",
    whyDecision: "State kept in activities timeline (actor-labeled), not hidden reasoning. Following progression Question→Answer→Clarification→Qualification→Next step. Escalation criteria: high value, complex, sensitive — booking may follow if prospect signals ready.",
    informationPassedForward: ["Updated conversation history (all turns)", "Qualification update: ServiceTitan confirmed → no longer avoid_assumption, contactability up", "Next proposal: booking if ready else nurture"],
    conversation: {
      prospectSays: "Sounds useful. Does it handle after-hours calls too?",
      intent: "CURIOUS → details + interest signal",
      orbitReplies: "Yes — 24/7, including after-hours. It answers, qualifies (service needed, urgency, location), and books or routes per your rules, then logs in ServiceTitan. Many HVAC teams use it for after-hours + overflow when dispatch is busy. Want to see a 2-min walkthrough of the ServiceTitan booking flow?",
      nextAction: "If 'yes' → BOOK; if 'pricing?' → escalate human",
    },
  },
  {
    stage: "book",
    stageTitle: "BOOK / HANDOFF",
    whatOrbitKnows: [
      "Qualified conversation: P1, interest confirmed (after-hours question = buying signal), ServiceTitan stack known",
      "Objections: none serious; questions answered; timeline likely now (hiring indicates urgency)",
    ],
    whatOrbitDoesntKnow: ["Exact close probability (will be learned post-meeting)"],
    signalFound: "Ready to book signal: 'Sure, book Thursday?'",
    howItInterprets: "Intent READY TO BOOK → propose meeting via booking link (Cal.com embed), confirm Thu 10 ET, notify owner, update opportunity stage, summarize conversation for handoff.",
    decision: "BOOKED → lead qualified_conversation→meeting_booked, meeting record booked, hot-lead alert via Telegram + dashboard, packet assembled",
    whyDecision: "Qualified + interest + timing + verified contact all green. Structured packet gives salesperson context: no need to re-discover.",
    informationPassedForward: [
      "Meeting Thu 10 ET booked, status booked, calendar_link, brief",
      "Handoff packet: ABC HVAC (3 areas, 4.6★), trigger: dispatcher hiring URL + weak booking, likely problem: scheduling pressure, history: 2 Q&A turns, intent READY, objections: none, qual notes: owner verified, P1",
      "Lead status meeting_booked → will advance to meeting_held → proposal → won/lost",
      "Learning event: booked via dispatcher+weak-booking angle → reinforce for similar HVAC vertical",
    ],
    conversation: {
      prospectSays: "Sure, let's book Thursday 10am.",
      intent: "READY TO BOOK",
      orbitReplies: "Booked — Thu 10 ET. You'll get a calendar invite. Looking forward! [System: meeting booked, handoff briefing generated, operator alerted]",
      nextAction: "Human prepares with packet, attends, closes; outcome (won/lost/no-show) feeds LEARN",
    },
  },
  {
    stage: "learn",
    stageTitle: "LEARN",
    whatOrbitKnows: ["Full outcome: ABC HVAC booked from dispatcher + weak-booking angle (P1 HVAC, 3 areas)", "Source: JSearch hiring signal + website audit, scored 78", "Similar prior: 5 dispatcher+HVAC bookings vs 2 non-HVAC unsubscribes"],
    whatOrbitDoesntKnow: ["Whether this booking closes (won/lost) — will be known after meeting", "Whether angle generalizes to plumbing/electric (needs more evidence)"],
    signalFound: "Positive outcome: booked; angle: hiring+ads+weak booking; vertical: HVAC; confidence: medium-high → high reply/booking historically",
    howItInterprets: "Observation: hiring dispatcher for HVAC with ads + weak booking booked. Interpretation: dispatcher hiring is high-intent for HVAC (operational bottleneck). Evidence: n=6 HVAC dispatcher leads, 33% booking rate vs 12% baseline. Decision: weight dispatcher signals higher for HVAC in next FIND batch; keep plumbing threshold separate. Distinguish observation vs interpretation vs decision vs learning — don't rewrite prompts on single anecdote, need N before change.",
    decision: "LEARN: reinforce dispatcher + ads + weak-booking angle for HVAC; preserve evidence in scores/provider_usage/agent_runs/audit_log; Analytics: per-source booking rate up for JSearch+HVAC, funnel conversion outreach→response→book improved; DO NOT auto-rewrite qualification threshold yet (require N>10)",
    whyDecision: "Evidence-based, conservative. One booking with one angle not enough to rewrite system behavior — need statistical support. Negative learning also: if national franchise similarly profiled had rejected_too_large, downgrade national size at QUALIFY.",
    informationPassedForward: ["Updated targeting weights (FIND: prioritize HVAC dispatcher signals)", "Qualification calibration pending N", "Messaging: dispatcher+booking variant promoted to template library (manual)", "Every outcome → better next TARGET/CONTACT/ANGLE/TIMING"],
  },
];

// Additional conversation branches for evaluation harness — side-by-side with ABC HVAC
export const SIMULATION_VARIANTS = {
  positive: {
    reply: "Looks interesting! How does pricing work for 10 techs?",
    intent: "PRICE",
    escalation: true,
    decision: "HUMAN_REQUIRED — pricing negotiation, high value P1, notify human with packet",
  },
  objection: {
    reply: "We already have a receptionist, not interested.",
    intent: "OBJECTION",
    escalation: false,
    decision: "Handle 'AI augments, not replaces — after-hours + overflow' → if still not interested → respect, suppress if requested, learn (source quality maybe low for this ICP)",
  },
  wrongPerson: {
    reply: "Not me — talk to Jamie in ops, jamie@abchvac.example.com",
    intent: "WRONG_PERSON",
    escalation: false,
    decision: "Re-identify with referral Jamie (higher confidence than waterfall), don't suppress company, route to Jamie",
  },
  later: {
    reply: "Call me in 3 months, busy season now.",
    intent: "TALK_LATER",
    escalation: false,
    decision: "QUALIFIED NOT READY → record timing (90d), nurture, monitor hiring_signals expiry (60d), set reminder, don't close",
  },
  unsubscribe: {
    reply: "Please remove me from your list.",
    intent: "NOT_INTERESTED / UNSUBSCRIBE",
    escalation: false,
    decision: "Immediate do_not_call + global suppression (email+phone+company), cancel all queued, alert not needed, learn (bad fit or wrong angle?)",
  },
  angry: {
    reply: "Stop spamming me!",
    intent: "DO_NOT_CALL",
    escalation: false,
    decision: "Immediate do_not_call from any non-terminal, global suppression, never contact again, audit logged",
  },
};

// Helpers
export function getSimulationStep(stageId: string): SimulationStep | undefined {
  return ABC_HVAC_SIMULATION.find((s) => s.stage === stageId);
}
export function getNextStageId(currentId: string): string | null {
  const idx = ABC_HVAC_SIMULATION.findIndex((s) => s.stage === currentId);
  if (idx === -1 || idx === ABC_HVAC_SIMULATION.length - 1) return null;
  return ABC_HVAC_SIMULATION[idx + 1].stage;
}
