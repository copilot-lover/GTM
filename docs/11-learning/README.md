# STAGE 12 — LEARN (Outcome → Evidence → Future Adjustment)

> **IETM teaching doc · Stage 12 of 12 · Progressive disclosure: 🟢 Everyone → 🟡 Operator → 🔴 Builder**
> Canonical: `frontend/src/gtm/canonical.ts:~` (`id:"learn", index:12`) · Simulation: `frontend/src/gtm/simulation.ts:226` · Engine: `backend/app/services/learning_loop.py:1` · Scoring weights: `backend/app/services/scoring.py`, `opportunity.py:23` (`system_flags opportunity_weights`) · Events: `backend/app/services/intent_engine.py:58`, `email_service.py:201` outcomes

---

# WHAT IS IT?

> 🟢 **BASIC**

**LEARN** is where Orbit **studies what actually happened** and **gets smarter without overfitting**. It distinguishes four nouns that are often confused:

| Noun | Verbatim definition | Example for ABC HVAC |
|------|---------------------|----------------------|
| **OBSERVATION** | *What happened* — measured outcome | `reply rate`, `booking rate` (`learning_loop.Observation:11` — `what, source, n`) |
| **INTERPRETATION** | *What it means* — why it happened, with strength | `hiring dispatcher for HVAC → high-intent (operational bottleneck)` — `evidence_strength weak|medium|strong` (`learning_loop.Interpretation:17`) |
| **DECISION** | *What to change* — targeting/threshold/angle | `weight dispatcher signals higher for HVAC in next FIND batch` |
| **LEARNING** | *Evidence for future* — not an instant rewrite | `adjustment + confidence low|medium|high + should_change bool` (`learning_loop.Learning:23`) |

> 🟡 LEARN's job: **observe → interpret with appropriate conservatism → log learning for the next cycle → change only when evidence is strong enough.**

---

# WHY DOES IT EXIST?

> 🟢 Two failure modes if you skip it:

1. **No learning → same mistakes forever.** You keep burning sends on Yelp + plumber + `receptionist` signals that never book.
2. **Over-learning → rewrite behavior on one bad outcome.** One HVAC dispatcher who unsubscribed causes you to block all HVAC dispatchers — you overfit an N=1.

LEARN exists to make both errors impossible via **conservative thresholds** (`learning_loop.CONSERVATIVE_THRESHOLDS:38` — `min_observations 10, min_strong 5` before `should_change=true`).

---

# WHAT GOES IN?

> 🟡 Every **terminal or positive outcome** that is ground-truth:

- `BOOKED` → `meetings.status booked` + `opportunities.stage proposal|won` (source: `JSearch+HVAC, score 78` for ABC HVAC — `simulation.ts:228`)
- `WON / LOST` → `opportunities.stage` + `opportunities.value_mrr` (for `opportunity.compute_emv:379` next pricing calibration)
- `NO-SHOW / HELD NOT HELD` → `meetings` outcome
- `REPLY positive|negative|neutral` → `intent_events (REPLY_CLASS)` + `activities`
- `UNSUBSCRIBE / DO_NOT_CALL` → `suppression` rows
- `NONE (ignored)` → `email_events` not opened / `sequence` cancelled

Plus the **angle + signal + vertical provenance** that produced the booked lead: `JSearch hiring, weak-booking audit, HVAC dispatcher, P1`.

> Inputs are **observations**, not interpretations — that line is enforced in code (`learning_loop.evaluation` naming: `OBSERVATION is what happened (reply rate, booking rate)` — `learning_loop.learning_principles:64`).

---

# WHAT HAPPENS?

> 🟡 Deterministic, countable, operator-readable path:

1. **Collect observations** — aggregate `Observation(what, source, n)` across `N` outcomes. Example: `high reply from dispatcher+HVAC (N=6, 33% booking rate vs 12% baseline)`, `low qual from Yelp source (N=12)`, `high unsubscribe from angle X`.
2. **Interpret** — map each `Observation → Interpretation(observation, meaning, evidence_strength)` (`learning_loop.LEARNING_EXAMPLES:29` — 6 exemplars):
   - `high_reply_from_signal: hiring dispatcher + HVAC` → `hiring signal valuable for ICP` (strong)
   - `low_qual_from_source: Yelp` → `Yelp low fit for ICP` (medium)
   - `high_positive_from_role: ops manager` → `ops manager strong decision-maker` (strong)
   - `high_interest_low_booking` → `conversation→meeting needs fix` (strong)
   - `high_unsubscribe_from_angle` → `angle resonates poorly or audience wrong` (medium)
   - `poor_signal_performance → signal not predictive for this vertical` (weak)
3. **Gate by N** — `evaluate_learning(observations):43`:
   - if `sum(n) < 10` → `Learning(Interpretation("insufficient evidence", "small sample"), "no change — collect more", confidence low, should_change false)`
   - else `by_source = Counter(source) → top_source, top_n`; if `top_n ≥5` → `evidence_strength strong else medium`, `should_change = top_n ≥5` (`learning_loop.py:55`)
4. **Hold the learning** — preserved in `scores`, `provider_usage`, `agent_runs`, `audit_log`, and `analytics` (`per-source booking rate up for JSearch+HVAC, funnel conversion outreach→response→book improved` — `simulation.ts:234`).
5. **Don't rewrite prompts on single anecdote** — `evaluation` contract is explicit: **one booking with one angle is not enough to rewrite system behavior — need statistical support** (`simulation.ts:234`, `learning_loop.learning_principles:69` `Require N≥10… Require strong evidence n≥5…`)

> 🔴 Critically: `LEARN` **does not** call `register_event_type()` or `opportunity_weights` flag mutations inline. It **produces an Interpretation + should_change flag** that an **operator** reviews via `control-plane flags` before promoting to dial weight changes — spec §11.2 `control → outbound pause/resume` edge, not an automatic rewrite.

---

# WHAT DECISIONS ARE MADE?

> 🟡 Only two exits, both conservative:

- **`should_change = false`** → `"no change — collect more evidence"` (`learning_loop.py:49`) — log but don't adjust thresholds. Negative learning still logged (`suppression` poor fits equally valuable — `learning_loop.learning_principles:73`).
- **`should_change = true`** (`top_n ≥5, total ≥10, strength strong|medium`) → suggest `"consider weighting {source} higher in FIND targeting"` or `"angle X resonates poorly"` — operator applies via `campaign_allocation` flag or `opportunity_weights` (`opportunity.py:102` `get_flag("opportunity_weights")`), not automatic code mutation.

Also: **distinguish seasonal/regional variance from permanent shift** — `learning_loop.learning_principles:72` — before changing dials.

---

# WHAT COMES OUT?

> 🟡 Not a rewrite — a **logged recommendation with confidence**:

- **Updated targeting weights (suggestion)** — `FIND: prioritize HVAC dispatcher signals` (`simulation.ts:234` line 1 of `informationPassedForward`)
- **Qualification calibration pending N** — thresholds stay `QUALIFY_THRESHOLD 6, TIER_THRESHOLDS` until `learning_principles` thresholds satisfied
- **Messaging variant promoted to template library (manual)** — `dispatcher+booking variant → template` after N≥threshold
- **Analytics deltas** — `per-source booking rate, funnel conversion outreach→response→book` (dashboard)
- **Evidence preservation** — `scores/opportunity, provider_usage/agent_runs/audit_log` retained for next `research._assemble_evidence` cycle

> The universal forward is: **"Every outcome → better next TARGET / CONTACT / ANGLE / TIMING"** — that's the continuous decision loop resetting (`simulation.ts:218`). The chain is `OBSERVATION → SIGNAL → CONTEXT → INTERPRETATION → OPPORTUNITY → … → (new FIND pass)` — `03-gtm-intent/` documents that chain; LEARN re-feeds it honestly.

---

# REAL-WORLD EXAMPLE — ABC HVAC at LEARN

> 🟢 Local HVAC, 3 areas, hiring dispatcher, weak booking — from `simulation.ts:226` `stage:"learn"`:

```
What Orbit knows:
  Full outcome: ABC HVAC booked from dispatcher + weak-booking angle (P1, HVAC, 3 areas)
  Source: JSearch hiring + website audit, scored 78
  Similar prior: 5 dispatcher+HVAC bookings vs 2 non-HVAC unsubscribes
  (ranneing total: 6 HVAC dispatcher leads, 33% booking rate vs 12% baseline)

Signal found: Positive outcome: booked; angle: hiring+ads+weak booking;
              vertical: HVAC; confidence: medium-high → high reply/booking historically

Interpretation:
  Observation: hiring dispatcher for HVAC with ads + weak booking booked.
  Interpretation: dispatcher hiring is high-intent for HVAC (operational bottleneck).
  Evidence: n=6 HVAC dispatcher leads, 33% booking vs 12% baseline.
  Decision: weight dispatcher signals higher for HVAC in next FIND batch;
            keep plumbing threshold separate.
  Learning type: distinguish observation vs interpretation vs decision vs learning —
            don't rewrite prompts on single anecdote, need N before change.

Decision (from simulation):
  LEARN: reinforce dispatcher + ads + weak-booking angle for HVAC;
         preserve evidence in scores/provider_usage/agent_runs/audit_log;
         Analytics: per-source booking rate up for JSearch+HVAC, funnel conversion
           outreach→response→book improved;
         DO NOT auto-rewrite qualification threshold yet (require N>10)

Why that decision:
  Evidence-based, conservative. One booking with one angle not enough to
  rewrite system behavior — need statistical support.
  Negative learning equally: if a national franchise similarly profiled had
  rejected_too_large, downgrade national size at QUALIFY.
```

> Note: even though ABC HVAC's dispatcher signal scored 78 and booked, `evaluate_learning` would still return `should_change=false` with just this one observation (`sum(n)=1 <10`) → expected. The reinforcement after ABC HVAC is the **5-prior-bookings context**, not the single new booking — consistent with `learning_loop.py:47`.

---

# WHAT CAN GO WRONG?

> 🟡

- **Overfitting on N=1** — operator promotes dispatcher weighting before N≥10 (`learning_loop.CONSERVATIVE_THRESHOLDS` ignored); next plumbing batch inherits a wrong prior
- **Under-learning by ignoring negative signals** — `suppression` grows but `LEARN` never attributes it to a source (e.g., Yelp), so FIND keeps buying Yelp leads at same weight
- **Stale `p_reply` default** (`opportunity.DEFAULT_P_REPLY 0.05` — `opportunity.py:78`) never recalibrated by actual reply rates → `EMV` stuck at `$4.45` (`opportunity.py:389` `history pass` but compute never wired) → no signal to deprioritize low-EMV verticals
- **Seasonal vs permanent shift conflation** — HVAC peak-season Jan-July vs off-season: dispatcher signal valuable in peak, weak off-peak; naive annual average masks it (`learning_loop.learning_principles:72` warns, not enforced)
- **Ancestors missing:** `research._fallback_research:207` generic "High inbound…" on LLM failure would be counted as valid evidence by `LEARN` if not filtered — should exclude fallback-flagged reports from `Observation` source

---

# EDGE CASES

> 🟡

- **`min_observations <10` with a strong single book** → still `should_change=false` (`learning_loop.py:47`) — intentional conservatism; the fix is to **collect more**, not lower the gate
- **Contradictory evidence (booking + unsubscribe on same signal)** → `by_source Counter` picks top by `n` — if tie, `most_common(1)` picks arbitrary first (deterministic Python heap on insertion order) — document which wins when n equal
- **Vertical sub-splits (HVAC vs Plumbing)** → `evaluate_learning` groups by `source` only (not `source×vertical`) — to keep HVAC/plumbing separate, call `evaluate_learning` per-vertical rather than once globally (`learning_loop.py:55`)
- **No past bookings yet (early lifecycle)** → `history component 0` via `opportunity._compute_history:229` → LEARN has no history to improve `EMV` estimate yet, which is expected
- **All observations negative** → `top_n ≥5` over `low_qual_from_source` still fires `should_change=true` with message `weight {source} lower` — equally valuable path; log but also consider deprecating that vertical's `FIND` provider weight

---

# WHAT HAPPENS NEXT?

> 🟢 LEARN closes the loop and re-opens it:

- **→ new FIND batch** — `orbit service flag` adjustments (e.g., `opportunity_weights` override via `flags.get_flag`, `campaign_allocation new_prospects_pct`, provider `track_provider_usage` priority shifts) applied **before** next discovery scan, so the next universe of candidates is already shaped
- **Nothing auto-rewrites without review** — per `learning_loop.learning_principles:68` all four lines: observation/interpretation/decision/learning distinction; single bad outcome never rewrites behavior; require `N≥10`; distinguish seasonal

> Reading loop: `FIND` sees different `TARGET` → `INTENT` re-ranks differently → `GATE` judges differently → `CONVERSE` prompts evolve (manual via `email-personalization.md` prompts) → `BOOK` packet gets better over time.

---

# WHY DOES IT MATTER?

> 🟢 GTM is a **machine that bets on reasons**. LEARN turns bets into receipts. Without it, Orbit is a guess factory; with it — even conservatively logged and operator-reviewed — it becomes **a system that finds fewer, better leads with a clear reason to reach out**, and the reason **gets clearer every cycle**.

---

# DEEPER DETAIL (technical)

> 🔴 **BUILDER**

**Modules:**
- `backend/app/services/learning_loop.py:1` — contract module: `Observation:11 (what, source, n)`, `Interpretation:17 (observation, meaning, evidence_strength weak|medium|strong)`, `Learning:23 (interpretation, adjustment, confidence low|medium|high, should_change bool)`, `LEARNING_EXAMPLES:29` (6 exemplars), `CONSERVATIVE_THRESHOLDS:38 ({min_observations 10, min_strong 5})`, `evaluate_learning:43`, `learning_principles:64` (9 axioms)
- `backend/app/services/scoring.py:39,71,113` — arithmetic LEARN feeds back via `OFFER_CATALOG` + `PRIORITY_WEIGHTS` constants, not magic
- `backend/app/services/opportunity.py:102` `_get_opportunity_weights()` flag override → lets LEARN dials be applied as `system_flags` JSON without code deploy
- `backend/app/services/intent_engine.py:58` + `hiring_signals.py:315` — raw observations LEARN aggregates are the same rows FIND produced
- `backend/app/services/email_service.py:201` + `twilio_service.py:192` — outcome sinks (`sent → replied → booked → won/lost → EMV`) that feed `meetings, opportunities, suppression`

**Tables (sink of truth):**
- `scores(…, score_type='opportunity' | 'emv', components jsonb)` — LEARN's deltas are diffs to these rows per vertical/signal
- `provider_usage(provider, operation, period, quota, used, reserve_threshold)` — `track_provider_usage:109` trends indicate `deprioritized` sources
- `audit_log, agent_runs, email_events, activities, alerts` — LEARN's `observation` audit trail is already here (nothing new to create, just interpret)

**Status:**
- ✅ IMPLEMENTED —four-noun distinction + `evaluate_learning` conservative gate + exemplar map + axioms; simulation `SIMULATION_VARIANTS` provide 6 labeled reply-to-outcome pairs to train anyone's intuition about `OBSERVATION vs INTERPRETATION`
- 🚧 PLANNED / NOT YET WIRED — automatic `opportunity_weights` flag write on `should_change=true` (currently operator via `flags` control-plane, not auto); seasonal de-averaging; filtering `_fallback_research` rows out of `Observation` source sets; per-`source×vertical` grouping in `evaluate_learning` (current code groups by bare `source`)

**Progressive disclosure contract:** LEARN is the last IETM stage — it hands back to the overview's loop diagram. The next doc (`19-onboarding/`) is where humans rehearse this entire loop without touching production.

---
*Trace: `app/services/learning_loop.py`, `app/services/opportunity.py`, `app/services/scoring.py` — `frontend/src/gtm/canonical.ts:learn` · Simulation `frontend/src/gtm/simulation.ts:226`.*
