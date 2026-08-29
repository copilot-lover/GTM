"""GTM agent architecture acceptance tests (spec §24, migration 0008).

Covers: deterministic QA layer + lifecycle stage machine, structural send
gates (outbound_gate + claim_for_send), intent re-evaluation with recency
decay, agent scheduler/ledger roundtrips. All state is real DB rows in
orbit_test; no LLM/network calls.
"""

import psycopg
import pytest

from app.agents import ledger, registry, scheduler as agent_scheduler
from app.services import email_service, gtm_lifecycle, intent_engine, \
    outbound_gate, pipeline, qa_service
from tests.conftest import make_lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verified_contact(db_url, ws, lead_id, email="owner@acme.test",
                      verification_status="verified", opt_out=False):
    conn = psycopg.connect(db_url, autocommit=True)
    contact_id = conn.execute(
        """INSERT INTO contacts (workspace_id, company_id, email,
               email_verification_status, opt_out_flag)
           SELECT %s, company_id, %s, %s, %s FROM leads WHERE id=%s
           RETURNING id""",
        (ws, email, verification_status, opt_out, lead_id),
    ).fetchone()[0]
    conn.execute("UPDATE leads SET contact_id=%s WHERE id=%s", (contact_id, lead_id))
    conn.close()
    return str(contact_id)


def _managed_draft(db_url, ws, lead_id, *, subject, body, claims=None,
                   evidence_refs=None):
    """Insert a message and enroll it in the GTM machine at QA_PENDING."""
    from app.services import gtm_lifecycle

    conn = psycopg.connect(db_url, autocommit=True)
    msg = str(conn.execute(
        """INSERT INTO messages (workspace_id, lead_id, channel, direction,
               subject, body_text, status)
           VALUES (%s,%s,'email','outbound',%s,%s,'pending_approval')
           RETURNING id""",
        (ws, lead_id, subject, body),
    ).fetchone()[0])
    if claims is not None:
        import json
        conn.execute("UPDATE messages SET claims=%s, evidence_refs=%s WHERE id=%s",
                     (json.dumps(claims), json.dumps(evidence_refs or []), msg))
    conn.close()
    gtm_lifecycle.transition_message(ws, msg, "QA_PENDING", actor="GTM_COPY",
                                     reason="draft created")
    return msg


def _set_message_status(db_url, msg, status):
    conn = psycopg.connect(db_url, autocommit=True)
    conn.execute("UPDATE messages SET status=%s WHERE id=%s", (status, msg))
    conn.close()


def _stage_of(db_url, ws, msg):
    conn = psycopg.connect(db_url, autocommit=True)
    stage = conn.execute(
        "SELECT gtm_stage FROM messages WHERE id=%s", (msg,)).fetchone()[0]
    conn.close()
    return stage


CLEAN_PARSED = {
    "subject": "Dispatcher hiring at Acme",
    "first_sentence": "Saw Acme is hiring a dispatcher.",
    "body": ("That usually means calls pile up while crews are on jobs. "
             "An AI receptionist answers every overflow call and books work."),
    "cta": "Worth a quick look this week?",
    "claims": [],
    "evidence_refs": [],
}


def _banned_parsed():
    p = dict(CLEAN_PARSED)
    p["first_sentence"] = "Just following up on my note from last week."
    return {k: v for k, v in p.items() if k not in ("claims", "evidence_refs")}


def _insert_signal(db_url, ws, company_id, *, status="active", age_days=0,
                   signal_score=100):
    conn = psycopg.connect(db_url, autocommit=True)
    sid = str(conn.execute(
        """INSERT INTO hiring_signals (workspace_id, company_id, source,
               source_job_id, role_category, signal_score, freshness_multiplier,
               status, posted_at)
           VALUES (%s,%s,'fixture',%s,'dispatcher',%s,1.0,%s,
                   now() - make_interval(days => %s))
           RETURNING id""",
        (ws, company_id, f"job-{status}-{age_days}", signal_score, status,
         age_days),
    ).fetchone()[0])
    conn.close()
    return sid


# ---------------------------------------------------------------------------
# 1. QA rejection → resubmit → pass
# ---------------------------------------------------------------------------

class TestQARejectionThenPass:
    def test_qa_rejection_then_pass(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id)

        parsed = _banned_parsed()
        msg = pipeline.create_draft_message(ws, lead_id, parsed,
                                            " ".join(filter(None, [
                                                parsed["first_sentence"],
                                                parsed["body"], parsed["cta"]])))
        assert _stage_of(db_url, ws, msg) == "QA_PENDING"

        run = qa_service.run_copy_qa(ws, msg)
        assert run["status"] == "failed"
        assert any(f["rule"] == "GENERIC_COPY" for f in run["findings"])
        assert "GENERIC_COPY" in run["failed_rules"]
        assert _stage_of(db_url, ws, msg) == "QA_FAILED"

        res = qa_service.resubmit_copy(ws, msg, CLEAN_PARSED)
        assert res["requeued"] is True
        assert _stage_of(db_url, ws, msg) == "QA_PENDING"

        run2 = qa_service.run_copy_qa(ws, msg)
        assert run2["status"] == "passed"
        assert run2["failed_rules"] == []
        assert run2["attempt"] == 2
        assert _stage_of(db_url, ws, msg) == "QA_PASSED"


# ---------------------------------------------------------------------------
# 2. Unsupported claim blocks send
# ---------------------------------------------------------------------------

class TestUnsupportedClaimBlocksSend:
    def test_unsupported_claim_blocks_send(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id)
        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]),
            claims=["You're hiring a dispatcher"], evidence_refs=[])

        run = qa_service.run_copy_qa(ws, msg)
        assert run["status"] == "failed"
        assert "UNSUPPORTED_FACT" in run["failed_rules"]

        decision = outbound_gate.can_send(ws, msg)
        assert decision["allowed"] is False
        failed = {c["name"]: c for c in decision["checks"] if not c["passed"]}
        assert "copy_qa_passed" in failed

        _set_message_status(db_url, msg, "approved")
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.claim_for_send(ws, msg)
        assert "copy qa run failed" in str(exc.value)

        # no transport occurred: claim released, nothing sent
        conn = psycopg.connect(db_url, autocommit=True)
        row = conn.execute(
            "SELECT status, provider_message_id FROM messages WHERE id=%s",
            (msg,)).fetchone()
        conn.close()
        assert row[0] == "approved"
        assert row[1] is None


# ---------------------------------------------------------------------------
# 3. Invalid / stale signal handling
# ---------------------------------------------------------------------------

class TestInvalidSignalInvalidates:
    def test_expired_signal_fails_copy_qa(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        company_id = str(conn.execute(
            "SELECT company_id FROM leads WHERE id=%s", (lead_id,)).fetchone()[0])
        conn.close()
        expired_sid = _insert_signal(db_url, ws, company_id, status="expired")

        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]),
            claims=["We saw you are hiring dispatcher staff"],
            evidence_refs=[{"signal_id": expired_sid, "text": "hiring dispatcher"}])

        run = qa_service.run_copy_qa(ws, msg)
        assert run["status"] == "failed"
        assert "WRONG_SIGNAL" in run["failed_rules"]
        assert _stage_of(db_url, ws, msg) == "QA_FAILED"

    def test_stale_signal_contributes_almost_nothing(self, db_url, workspace):
        ws, _ = workspace

        def scored_lead(age_days):
            lead_id = make_lead(db_url, ws, name=f"Signal Co {age_days}")
            conn = psycopg.connect(db_url, autocommit=True)
            conn.execute("UPDATE leads SET lead_score=5 WHERE id=%s", (lead_id,))
            company_id = str(conn.execute(
                "SELECT company_id FROM leads WHERE id=%s",
                (lead_id,)).fetchone()[0])
            conn.close()
            _insert_signal(db_url, ws, company_id, age_days=age_days)
            result = intent_engine.reevaluate_lead(ws, lead_id)
            return lead_id, result

        _, fresh = scored_lead(0)
        stale_lead, stale = scored_lead(29)

        fresh_pts = [c for c in fresh["components"]["contributions"]]
        stale_pts = [c for c in stale["components"]["contributions"]]
        assert all(c["points"] >= 30 for c in fresh_pts)
        assert all(c["points"] <= 5 for c in stale_pts)      # recency ~ 1/30
        assert stale["opportunity_score"] < fresh["opportunity_score"]
        assert stale["priority"] != "P1"

        conn = psycopg.connect(db_url, autocommit=True)
        stored = conn.execute(
            "SELECT priority_score FROM leads WHERE id=%s",
            (stale_lead,)).fetchone()[0]
        conn.close()
        assert stored == stale["opportunity_score"]


# ---------------------------------------------------------------------------
# 4. Compliance failure cannot send
# ---------------------------------------------------------------------------

class TestComplianceFailureCannotSend:
    def test_opted_out_contact_blocks_compliance_and_send(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id, opt_out=True)
        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]))

        passed_run = qa_service.run_copy_qa(ws, msg)
        assert passed_run["status"] == "passed"
        assert _stage_of(db_url, ws, msg) == "QA_PASSED"

        comp = qa_service.run_compliance_qa(ws, msg)
        assert comp["status"] == "failed"
        assert "COMPLIANCE_FAILURE" in comp["failed_rules"]
        assert _stage_of(db_url, ws, msg) == "COMPLIANCE_FAILED"

        decision = outbound_gate.can_send(ws, msg)
        assert decision["allowed"] is False
        failed = {c["name"] for c in decision["checks"] if not c["passed"]}
        assert "compliance_passed" in failed

        _set_message_status(db_url, msg, "approved")
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.claim_for_send(ws, msg)
        assert "compliance" in str(exc.value).lower()

        conn = psycopg.connect(db_url, autocommit=True)
        provider_mid = conn.execute(
            "SELECT provider_message_id FROM messages WHERE id=%s",
            (msg,)).fetchone()[0]
        conn.close()
        assert provider_mid is None


# ---------------------------------------------------------------------------
# 5. Follow-up mailbox mismatch held at the gate
# ---------------------------------------------------------------------------

class TestFollowupWrongMailboxHeld:
    def test_wrong_mailbox_gate_then_held(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)

        conn = psycopg.connect(db_url, autocommit=True)
        mb_a = str(conn.execute(
            "INSERT INTO mailboxes (workspace_id, email) VALUES (%s,'a@test.dev') "
            "RETURNING id", (ws,)).fetchone()[0])
        mb_b = str(conn.execute(
            "INSERT INTO mailboxes (workspace_id, email) VALUES (%s,'b@test.dev') "
            "RETURNING id", (ws,)).fetchone()[0])
        original = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status, sequence_step,
                   originating_mailbox_id)
               VALUES (%s,%s,'email','outbound','step 0','hi','sent',0,%s)
               RETURNING id""", (ws, lead_id, mb_a)).fetchone()[0])
        followup = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status, sequence_step,
                   originating_mailbox_id)
               VALUES (%s,%s,'email','outbound','Re: step 0','follow-up',
                       'approved',1,%s) RETURNING id""",
            (ws, lead_id, mb_b)).fetchone()[0])
        conn.close()

        gtm_lifecycle.transition_message(ws, followup, "SCHEDULED",
                                         actor="system", reason="enrolled")
        assert gtm_lifecycle.can_transition(None, "SCHEDULED")

        decision = outbound_gate.can_send(ws, followup)
        assert decision["allowed"] is False
        failed = {c["name"]: c for c in decision["checks"] if not c["passed"]}
        assert "followup_mailbox_correct" in failed
        assert str(mb_a) in failed["followup_mailbox_correct"]["detail"]

        moved = gtm_lifecycle.transition_message(ws, followup, "HELD",
                                                 actor="gatekeeper",
                                                 reason="mailbox mismatch")
        assert moved["from_stage"] == "SCHEDULED"
        history = gtm_lifecycle.stage_history(ws, followup)
        assert [(e["from_stage"], e["to_stage"]) for e in history][-1] == \
            ("SCHEDULED", "HELD")
        assert history[-1]["actor"] == "gatekeeper"

        # sanity: matching mailbox passes the check
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute(
            "UPDATE messages SET originating_mailbox_id=%s WHERE id=%s",
            (mb_a, followup))
        conn.execute("UPDATE messages SET gtm_stage='SCHEDULED' WHERE id=%s "
                     "AND gtm_stage='HELD'", (followup,))
        conn.close()
        ok_decision = outbound_gate.can_send(ws, followup)
        check = {c["name"]: c for c in ok_decision["checks"]}
        assert check["followup_mailbox_correct"]["passed"] is True


# ---------------------------------------------------------------------------
# 6. Fresh hot signal reprioritizes; cooling after aging
# ---------------------------------------------------------------------------

class TestFreshHotSignalReprioritizes:
    def test_job_posted_reprioritizes_then_cools(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute("UPDATE leads SET lead_score=5 WHERE id=%s", (lead_id,))
        company_id = str(conn.execute(
            "SELECT company_id FROM leads WHERE id=%s",
            (lead_id,)).fetchone()[0])
        conn.close()

        intent_engine.ingest_event(ws, event_type="JOB_POSTED",
                                   company_id=company_id,
                                   payload={"role": "dispatcher"})
        processed = intent_engine.process_pending_events(ws)
        assert processed["processed"] >= 1
        assert processed["leads_reevaluated"] >= 1

        hot = intent_engine.reevaluate_lead(ws, lead_id)
        assert hot["opportunity_score"] >= 70
        assert hot["priority"] == "P1"
        assert hot["components"]["source"] == "GTM_INTENT"
        assert hot["components"]["contributions"]

        conn = psycopg.connect(db_url, autocommit=True)
        stored = conn.execute(
            "SELECT priority_score FROM leads WHERE id=%s",
            (lead_id,)).fetchone()[0]
        scores_rows = conn.execute(
            """SELECT components FROM scores WHERE lead_id=%s
               AND score_type='opportunity'""", (lead_id,)).fetchall()
        conn.close()
        assert stored == hot["opportunity_score"]
        assert scores_rows
        comp = scores_rows[-1][0]
        assert comp["source"] == "GTM_INTENT"
        assert comp["contributions"]

        # age the event to 29 days → cooling
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute(
            "UPDATE intent_events SET occurred_at = now() - interval '29 days' "
            "WHERE company_id=%s AND workspace_id=%s", (company_id, ws))
        conn.close()

        cooled = intent_engine.reevaluate_lead(ws, lead_id)
        assert cooled["opportunity_score"] < hot["opportunity_score"]
        assert cooled["opportunity_score"] < 70
        assert cooled["priority"] != "P1"
        ages = [c["age_days"] for c in cooled["components"]["contributions"]]
        assert ages and max(ages) > 28


# ---------------------------------------------------------------------------
# 7. Structural gates
# ---------------------------------------------------------------------------

class TestStructuralGates:
    def test_invalid_stage_jump_rejected(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]))
        # walk legally to COPY_GENERATED first
        conn = psycopg.connect(db_url, autocommit=True)
        conn.execute("UPDATE messages SET gtm_stage=NULL WHERE id=%s", (msg,))
        conn.close()
        gtm_lifecycle.transition_message(ws, msg, "COPY_GENERATED")
        with pytest.raises(gtm_lifecycle.InvalidTransition):
            gtm_lifecycle.transition_message(ws, msg, "SENT")

    def test_claim_blocked_at_unauthorized_stage(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id)
        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]))
        assert _stage_of(db_url, ws, msg) == "QA_PENDING"
        _set_message_status(db_url, msg, "approved")
        with pytest.raises(email_service.SendBlocked) as exc:
            email_service.claim_for_send(ws, msg)
        assert "QA_PENDING" in str(exc.value)

    def test_registry_boundaries(self):
        with pytest.raises(registry.PermissionDenied):
            registry.assert_can_send("GTM_COPY")
        registry.assert_can_send("GTM_OUTBOUND")  # must not raise
        with pytest.raises(registry.PermissionDenied):
            registry.assert_not_self_approval("GTM_QA", "GTM_QA")
        registry.assert_not_self_approval("GTM_QA", "GTM_COPY")  # fine
        with pytest.raises(registry.PermissionDenied):
            registry.assert_capability("GTM_INTENT", "schedule_send")

    def test_unknown_event_type_rejected(self, workspace):
        ws, _ = workspace
        with pytest.raises(ValueError):
            intent_engine.ingest_event(ws, event_type="NOT_A_REAL_EVENT")


# ---------------------------------------------------------------------------
# 8. Agent scheduler + run ledger
# ---------------------------------------------------------------------------

class TestAgentSchedulerAndLedger:
    def test_default_schedules_tick_and_ledger(self, db_url, workspace):
        ws, _ = workspace

        agent_scheduler.ensure_default_schedules()
        conn = psycopg.connect(db_url, autocommit=True)
        conn.row_factory = psycopg.rows.dict_row
        schedules = conn.execute("SELECT * FROM agent_schedules").fetchall()
        conn.close()
        assert len(schedules) == 5
        assert len({s["agent"] for s in schedules}) == 5

        r1 = agent_scheduler.tick()
        assert r1["scheduled"] >= 1

        conn = psycopg.connect(db_url, autocommit=True)
        job_types = {r[0] for r in conn.execute("SELECT type FROM jobs").fetchall()}
        next_runs = dict(conn.execute(
            "SELECT task_type, next_run FROM agent_schedules").fetchall())
        jobs_after_first = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        conn.close()
        expected_tasks = {t for t, _ in agent_scheduler.DEFAULT_TASKS.values()}
        assert job_types & expected_tasks, f"no mapped jobs enqueued: {job_types}"
        assert all(nr is not None for nr in next_runs.values())

        r2 = agent_scheduler.tick()
        assert r2["scheduled"] == 0
        conn = psycopg.connect(db_url, autocommit=True)
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == \
            jobs_after_first
        conn.close()

        # ledger roundtrip
        run_id = ledger.record_run("GTM_QA", "test-trigger", workspace_id=ws)
        ledger.complete_run(run_id, status="success",
                            output_ref={"done": True}, latency_ms=42)
        conn = psycopg.connect(db_url, autocommit=True)
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute("SELECT * FROM agent_runs WHERE id=%s",
                           (run_id,)).fetchone()
        conn.close()
        assert row["agent_name"] == "GTM_QA"
        assert row["status"] == "success"
        assert row["latency_ms"] == 42
        assert row["started_at"] is not None
        assert row["finished_at"] is not None


# ---------------------------------------------------------------------------
# 9. Retry ceiling holds the draft for human review
# ---------------------------------------------------------------------------

class TestRetryCeilingHolds:
    def test_retry_ceiling_holds_for_human_review(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id)

        parsed = _banned_parsed()
        msg = pipeline.create_draft_message(ws, lead_id, parsed,
                                            " ".join(filter(None, [
                                                parsed["first_sentence"],
                                                parsed["body"], parsed["cta"]])))
        ceiling = qa_service.max_attempts()
        for _ in range(ceiling - 1):
            run = qa_service.run_copy_qa(ws, msg)
            assert run["status"] == "failed"
            res = qa_service.resubmit_copy(ws, msg, parsed)
            assert res.get("requeued") is True

        run = qa_service.run_copy_qa(ws, msg)
        assert run["status"] == "failed"
        res = qa_service.resubmit_copy(ws, msg, parsed)
        assert res["held"] is True

        assert _stage_of(db_url, ws, msg) == "HELD"
        history = gtm_lifecycle.stage_history(ws, msg)
        assert "max QA attempts exceeded" in history[-1]["reason"]

        decision = outbound_gate.can_send(ws, msg)
        assert decision["allowed"] is False
        _set_message_status(db_url, msg, "approved")
        with pytest.raises(email_service.SendBlocked):
            email_service.claim_for_send(ws, msg)


# ---------------------------------------------------------------------------
# 10. Follow-ups enrolled structurally on the original mailbox
# ---------------------------------------------------------------------------

class TestFollowupsEnrolledStructurally:
    def test_followup_inherits_mailbox_and_stage(self, db_url, workspace):
        ws, _ = workspace
        lead_id = make_lead(db_url, ws)

        conn = psycopg.connect(db_url, autocommit=True)
        mb = str(conn.execute(
            "INSERT INTO mailboxes (workspace_id, email) VALUES (%s,'seq@test.dev') "
            "RETURNING id", (ws,)).fetchone()[0])
        original = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction,
                   subject, body_text, status, sequence_step,
                   originating_mailbox_id)
               VALUES (%s,%s,'email','outbound','step 0','hi','sent',0,%s)
               RETURNING id""", (ws, lead_id, mb)).fetchone()[0])
        conn.close()

        assert email_service.schedule_followups(ws, lead_id, None, original) == 1

        conn = psycopg.connect(db_url, autocommit=True)
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT id, gtm_stage, originating_mailbox_id FROM messages
               WHERE lead_id=%s AND sequence_step=1""", (lead_id,)).fetchone()
        conn.close()
        assert row["gtm_stage"] == "SEND_READY"
        assert str(row["originating_mailbox_id"]) == mb

        history = gtm_lifecycle.stage_history(ws, str(row["id"]))
        assert [(e["from_stage"], e["to_stage"]) for e in history] == \
            [(None, "SEND_READY")]


# ---------------------------------------------------------------------------
# 11. Scheduled QA sweep advances the pipeline
# ---------------------------------------------------------------------------

class TestQASweepAdvancesPipeline:
    def test_sweep_moves_clean_draft_to_send_ready(self, db_url, workspace):
        from app.services import job_queue

        import app.agents.scheduler  # noqa: F401 - registers handlers

        ws, _ = workspace
        lead_id = make_lead(db_url, ws)
        _verified_contact(db_url, ws, lead_id)
        msg = _managed_draft(
            db_url, ws, lead_id,
            subject=CLEAN_PARSED["subject"],
            body=" ".join([CLEAN_PARSED["first_sentence"], CLEAN_PARSED["body"],
                           CLEAN_PARSED["cta"]]))
        assert _stage_of(db_url, ws, msg) == "QA_PENDING"

        result = job_queue._HANDLERS[("ai", "gtm_qa_audit")]({"payload": {}})

        assert result["audited"] >= 1
        assert result["copy_passed"] >= 1
        assert result["compliance_passed"] >= 1
        assert result["failed"] == 0
        assert _stage_of(db_url, ws, msg) == "SEND_READY"
