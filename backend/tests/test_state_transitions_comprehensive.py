"""
State Transition Mapping — map every major GTM state.
For each state determine: WHAT CAN ENTER, WHAT CAN EXIT, WHAT CAN NEVER HAPPEN,
WHAT IF MISSING INFO, WHAT IF REPLY, OPT-OUT, HUMAN TAKEOVER.
Fix impossible/ambiguous states.
"""

import psycopg
import pytest

from app.services import state_machine as sm, gtm_lifecycle as gl
from tests.conftest import make_lead


class TestLeadStateMachineComprehensive:
    def test_every_state_documented(self):
        all_states = set(sm.TRANSITIONS.keys()) | {t for v in sm.TRANSITIONS.values() for t in v}
        assert "new" in all_states
        assert "won" in all_states
        assert "do_not_call" in all_states
        assert "rejected" in all_states

    def test_new_can_enter_only_via_creation(self):
        # new has no incoming in TRANSITIONS (creation only)
        incoming = [k for k,v in sm.TRANSITIONS.items() if "new" in v]
        assert incoming == [], f"new should not be reachable via transition, got {incoming}"

    def test_won_terminal(self):
        assert sm.TRANSITIONS["won"] == set()
        assert "won" in sm.TERMINAL

    def test_do_not_call_reachable_from_all_non_terminal(self):
        for s, targets in sm.TRANSITIONS.items():
            if s not in sm.TERMINAL and s not in ("won","rejected","do_not_call","archived"):
                assert "do_not_call" in targets, f"{s} must allow do_not_call"

    def test_rejected_terminal(self):
        assert sm.TRANSITIONS["rejected"] == set()

    def test_archived_terminal(self):
        assert sm.TRANSITIONS["archived"] == set()

    def test_contacted_self_loop_allowed_for_followups(self):
        assert sm.can_transition("contacted", "contacted")

    def test_meeting_booked_self_loop_reschedule(self):
        assert sm.can_transition("meeting_booked", "meeting_booked")

    def test_invalid_what_can_never_happen(self):
        impossible = [
            ("new","won"),
            ("new","responded"),
            ("enriching","won"),
            ("won","new"),
            ("rejected","qualified"),
            ("do_not_call","contacted"),
            ("archived","new"),
        ]
        for src, dst in impossible:
            assert not sm.can_transition(src,dst), f"IMPOSSIBLE {src}->{dst} should be blocked"

    def test_missing_info_stays_enriching_or_rejected(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="MissingInfo State")
        conn = psycopg.connect(db_url, autocommit=True)
        # new → enriching if AE attempts, or new → rejected if fail-closed
        assert sm.transition(conn, lead, ws, "new", "enriching")
        # enriching with missing info should go to rejected not qualified
        assert sm.transition(conn, lead, ws, "enriching", "rejected")
        conn.close()

    def test_reply_moves_to_responded_and_blocks_outreach(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="ReplyState Co")
        conn = psycopg.connect(db_url, autocommit=True)
        assert sm.transition(conn, lead, ws, "new", "enriching")
        assert sm.transition(conn, lead, ws, "enriching", "qualified")
        assert sm.transition(conn, lead, ws, "qualified", "outreach_ready")
        assert sm.transition(conn, lead, ws, "outreach_ready", "contacted")
        assert sm.transition(conn, lead, ws, "contacted", "responded")
        # after responded, cannot go back to contacted (would be re-Outreach)
        assert not sm.can_transition("responded", "contacted")
        conn.close()

    def test_opt_out_to_do_not_call_from_any(self, db_url, workspace):
        ws,_=workspace
        for start in ["new","enriching","qualified","outreach_ready","contacted"]:
            lead = make_lead(db_url, ws, name=f"OptOut {start}")
            conn = psycopg.connect(db_url, autocommit=True)
            # bring to start state
            if start != "new":
                assert sm.transition(conn, lead, ws, "new", "enriching")
                if start == "qualified":
                    assert sm.transition(conn, lead, ws, "enriching", "qualified")
                elif start == "outreach_ready":
                    assert sm.transition(conn, lead, ws, "enriching", "qualified")
                    assert sm.transition(conn, lead, ws, "qualified", "outreach_ready")
                elif start == "contacted":
                    assert sm.transition(conn, lead, ws, "enriching", "qualified")
                    assert sm.transition(conn, lead, ws, "qualified", "outreach_ready")
                    assert sm.transition(conn, lead, ws, "outreach_ready", "contacted")
            assert sm.can_transition(start, "do_not_call"), f"{start} must allow DNC"
            # actually transition
            assert sm.transition(conn, lead, ws, start, "do_not_call")
            # DNC terminal
            assert not sm.can_transition("do_not_call", "contacted")
            conn.close()

    def test_human_takeover_qualified_conversation(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="HumanTakeover Co")
        conn = psycopg.connect(db_url, autocommit=True)
        for a,b in [("new","enriching"),("enriching","qualified"),("qualified","outreach_ready"),("outreach_ready","contacted"),("contacted","responded"),("responded","qualified_conversation")]:
            assert sm.transition(conn, lead, ws, a,b)
        assert sm.can_transition("qualified_conversation","meeting_booked")
        assert sm.can_transition("qualified_conversation","lost")
        conn.close()

    def test_no_ambiguous_state_multiple_paths_to_won(self):
        # won reachable only from meeting_held or proposal (and proposal from meeting_held)
        preds_won = [k for k,v in sm.TRANSITIONS.items() if "won" in v]
        assert set(preds_won) == {"meeting_held","proposal"}

    def test_signal_holding_loop(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="SignalHold Co")
        conn = psycopg.connect(db_url, autocommit=True)
        assert sm.transition(conn, lead, ws, "new","enriching")
        assert sm.transition(conn, lead, ws, "enriching","signal_holding")
        assert sm.can_transition("signal_holding","outreach_ready")
        assert sm.can_transition("signal_holding","qualified")
        conn.close()

    def test_expired_rejected_from_signal_holding(self):
        assert sm.can_transition("signal_holding","expired_rejected")

class TestMessageLifecycleComprehensive:
    def test_all_stages_defined(self):
        assert "DISCOVERED" in gl.STAGES
        assert "SENT" in gl.STAGES
        assert "HELD" in gl.STAGES
        assert gl.AUTHORIZED_SEND_STAGES == ("SEND_READY","SCHEDULED")

    def test_discovered_only_to_qualified(self):
        assert gl.TRANSITIONS["DISCOVERED"] == {"QUALIFIED"}

    def test_sent_terminal(self):
        assert gl.TRANSITIONS["SENT"] == set()
        assert gl.TRANSITIONS["SUPPRESSED"] == set()

    def test_held_can_cycle_to_qa_pending_or_cancelled(self):
        assert "QA_PENDING" in gl.TRANSITIONS["HELD"]
        assert "CANCELLED" in gl.TRANSITIONS["HELD"]

    def test_qa_failed_to_copy_generated_retry(self):
        assert "COPY_GENERATED" in gl.TRANSITIONS["QA_FAILED"]

    def test_compliance_failed_blocked_from_send_ready_without_retry(self):
        assert "SEND_READY" not in gl.TRANSITIONS["COMPLIANCE_FAILED"]
        assert "COPY_GENERATED" in gl.TRANSITIONS["COMPLIANCE_FAILED"]

    def test_invalid_what_can_never_happen_message(self):
        impossible = [
            ("DISCOVERED","SENT"),
            ("QA_PENDING","SENT"),
            ("SEND_READY","QA_PASSED"),
            ("SENT","HELD"),
            ("SUPPRESSED","SEND_READY"),
        ]
        for src,dst in impossible:
            assert not gl.can_transition(src,dst), f"IMPOSSIBLE message {src}->{dst}"

    def test_missing_info_HELD(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="MsgHold Co")
        import psycopg
        conn = psycopg.connect(db_url, autocommit=True)
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction, subject, body_text, status)
               VALUES (%s,%s,'email','outbound','hi','body','pending_approval') RETURNING id""",(ws,lead)).fetchone()[0])
        conn.close()
        gl.transition_message(ws, msg, "QA_PENDING", actor="test")
        gl.transition_message(ws, msg, "HELD", actor="test", reason="missing info")
        assert gl.can_transition("HELD","QA_PENDING")
        assert not gl.can_transition("HELD","SEND_READY")

    def test_human_escalation_HELD_not_auto_advance(self, db_url, workspace):
        ws,_=workspace
        lead = make_lead(db_url, ws, name="HumanEsc Co")
        conn = psycopg.connect(db_url, autocommit=True)
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction, subject, body_text, status)
               VALUES (%s,%s,'email','outbound','hi','body','pending_approval') RETURNING id""",(ws,lead)).fetchone()[0])
        conn.close()
        gl.transition_message(ws, msg, "QA_PENDING", actor="test")
        gl.transition_message(ws, msg, "HELD", actor="system", reason="needs human")
        # Held requires human to move to QA_PENDING — not auto
        assert not gl.can_transition("HELD","SEND_READY")

    def test_reply_should_suppress_not_continue(self, db_url, workspace):
        # Simulate reply → message should become SUPPRESSED or CANCELLED, not SEND_READY
        ws,_=workspace
        lead = make_lead(db_url, ws, name="ReplySuppr Msg")
        conn = psycopg.connect(db_url, autocommit=True)
        msg = str(conn.execute(
            """INSERT INTO messages (workspace_id, lead_id, channel, direction, subject, body_text, status)
               VALUES (%s,%s,'email','outbound','hi','body','pending_approval') RETURNING id""",(ws,lead)).fetchone()[0])
        conn.close()
        gl.transition_message(ws, msg, "QA_PENDING", actor="test")
        gl.transition_message(ws, msg, "QA_PASSED", actor="qa")
        gl.transition_message(ws, msg, "COMPLIANCE_PENDING", actor="qa")
        gl.transition_message(ws, msg, "SEND_READY", actor="compliance")
        # Now simulate opt-out → should move to SUPPRESSED not SENT
        gl.transition_message(ws, msg, "SUPPRESSED", actor="system", reason="unsubscribe")
        assert not gl.can_transition("SUPPRESSED","SENT")
