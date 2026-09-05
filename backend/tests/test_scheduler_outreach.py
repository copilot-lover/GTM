"""Tests for WS-E: Outreach Scheduler — health scoring, scheduler, followups, approval."""

import json
from datetime import datetime, timedelta, date as date_type, timezone
from unittest.mock import patch, MagicMock

import psycopg
import psycopg.rows
import pytest

from conftest import make_lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn(db_url: str):
    """Open a connection with dict_row factory."""
    conn = psycopg.connect(db_url, autocommit=True)
    conn.row_factory = psycopg.rows.dict_row
    return conn

def _insert_domain(conn, ws_id: str, domain: str = "send.test.dev") -> str:
    row = conn.execute(
        """INSERT INTO sending_domains (workspace_id, domain, status, daily_cap)
           VALUES (%s,%s,'active',600) RETURNING id""",
        (ws_id, domain),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_mailbox(conn, ws_id: str, domain_id: str, email: str = "out@test.dev",
                    health_state: str = "healthy", daily_limit: int = 30,
                    status: str = "ready") -> str:
    row = conn.execute(
        """INSERT INTO mailboxes
           (workspace_id, domain_id, email, status, health_state, daily_send_limit,
            sent_today, sent_today_date, timezone)
           VALUES (%s,%s,%s,%s,%s,%s,0,now(),'America/New_York')
           RETURNING id""",
        (ws_id, domain_id, email, status, health_state, daily_limit),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_outbound(conn, ws_id: str, lead_id: str, *,
                     kind: str = "initial", priority: int = 3,
                     status: str = "queued", mailbox_id: str = None,
                     campaign_id: str = None, sequence_id: str = None,
                     eligible_at: datetime = None, deadline: datetime = None,
                     shadow: bool = False) -> str:
    ea = eligible_at or datetime.now(timezone.utc)
    dl = deadline
    row = conn.execute(
        """INSERT INTO outbound_messages
           (workspace_id, lead_id, kind, priority, status, assigned_mailbox_id,
            campaign_id, sequence_id, eligible_at, deadline, shadow)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (ws_id, lead_id, kind, priority, status, mailbox_id,
         campaign_id, sequence_id, ea, dl, shadow),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_mailbox_event(conn, mailbox_id: str, event_type: str,
                          created_at: datetime = None) -> None:
    conn.execute(
        """INSERT INTO mailbox_events (mailbox_id, event_type, metrics, created_at)
           VALUES (%s,%s,%s,%s)""",
        (mailbox_id, event_type, "{}", created_at or datetime.now(timezone.utc)),
    )


def _insert_sequence(conn, ws_id: str, name: str = "Test Seq",
                     status: str = "active") -> str:
    row = conn.execute(
        """INSERT INTO sequences (workspace_id, name, status, steps_config)
           VALUES (%s,%s,%s,'[]') RETURNING id""",
        (ws_id, name, status),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_sequence_step(conn, seq_id: str, step_no: int,
                          offset_days: int, angle: str = "test") -> str:
    row = conn.execute(
        """INSERT INTO sequence_steps (sequence_id, step_no, offset_days, angle)
           VALUES (%s,%s,%s,%s) RETURNING id""",
        (seq_id, step_no, offset_days, angle),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_message(conn, ws_id: str, lead_id: str, *,
                    direction: str = "inbound", status: str = "replied") -> str:
    row = conn.execute(
        """INSERT INTO messages (workspace_id, lead_id, channel, direction, status)
           VALUES (%s,%s,'email',%s,%s) RETURNING id""",
        (ws_id, lead_id, direction, status),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


def _insert_score(conn, ws_id: str, lead_id: str, tier: str = "B") -> str:
    row = conn.execute(
        """INSERT INTO scores (workspace_id, lead_id, score_type, score, tier)
           VALUES (%s,%s,'opportunity',50,%s) RETURNING id""",
        (ws_id, lead_id, tier),
    ).fetchone()
    return str(row[0]) if not isinstance(row, dict) else str(row["id"])


# ===========================================================================
# Tests
# ===========================================================================


class TestHealthScore:
    def test_health_score_computation(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)

        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)

        # Insert events: 10 sent, 1 bounce, 1 complaint, 8 delivered
        now = datetime.now(timezone.utc)
        for i in range(10):
            _insert_mailbox_event(conn, mb_id, "send", now - timedelta(hours=i))
        _insert_mailbox_event(conn, mb_id, "bounce", now - timedelta(hours=1))
        _insert_mailbox_event(conn, mb_id, "complaint", now - timedelta(hours=2))

        # Set up outbound_messages to represent sends/deliveries/bounces
        for i in range(10):
            conn.execute(
                """INSERT INTO outbound_messages
                   (workspace_id, lead_id, kind, status, assigned_mailbox_id, created_at)
                   VALUES (%s,%s,'initial','sent',%s,%s)""",
                (ws_id, lead_id, mb_id, now - timedelta(hours=i)),
            )
        # Mark 1 as failed
        conn.execute(
            """UPDATE outbound_messages SET status='failed'
               WHERE id IN (
                   SELECT id FROM outbound_messages
                   WHERE assigned_mailbox_id=%s AND status='sent' LIMIT 1
               )""",
            (mb_id,),
        )
        conn.close()

        from app.services.mailbox_health import compute_health_score, map_score_to_state
        score = compute_health_score(mb_id)
        state = map_score_to_state(score)

        assert 0 <= score <= 100
        assert state in ("healthy", "normal", "reduced", "restricted", "paused")

    def test_state_mapping(self):
        from app.services.mailbox_health import map_score_to_state
        assert map_score_to_state(95) == "healthy"
        assert map_score_to_state(80) == "normal"
        assert map_score_to_state(65) == "reduced"
        assert map_score_to_state(50) == "restricted"
        assert map_score_to_state(30) == "paused"

    def test_health_score_zero_bounces_perfect(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)

        # 20 sends, all delivered, no bounces/complaints/failures
        now = datetime.now(timezone.utc)
        for i in range(20):
            conn.execute(
                """INSERT INTO outbound_messages
                   (workspace_id, lead_id, kind, status, assigned_mailbox_id, created_at)
                   VALUES (%s,%s,'initial','sent',%s,%s)""",
                (ws_id, lead_id, mb_id, now - timedelta(hours=i)),
            )
        conn.close()

        from app.services.mailbox_health import compute_health_score, map_score_to_state
        score = compute_health_score(mb_id)
        state = map_score_to_state(score)
        assert score >= 90
        assert state == "healthy"

    def test_health_score_high_bounces_low_score(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)

        # 10 sends: 3 bounces, 3 complaints, 4 delivered, 1 failed
        now = datetime.now(timezone.utc)
        for i in range(10):
            _insert_mailbox_event(conn, mb_id, "send", now - timedelta(hours=i))
        for _ in range(3):
            _insert_mailbox_event(conn, mb_id, "bounce", now - timedelta(hours=1))
        for _ in range(3):
            _insert_mailbox_event(conn, mb_id, "complaint", now - timedelta(hours=1))

        for i in range(10):
            conn.execute(
                """INSERT INTO outbound_messages
                   (workspace_id, lead_id, kind, status, assigned_mailbox_id, created_at)
                   VALUES (%s,%s,'initial','sent',%s,%s)""",
                (ws_id, lead_id, mb_id, now - timedelta(hours=i)),
            )
        conn.execute(
            """UPDATE outbound_messages SET status='failed'
               WHERE id IN (
                   SELECT id FROM outbound_messages
                   WHERE assigned_mailbox_id=%s AND status='sent' LIMIT 3
               )""",
            (mb_id,),
        )
        conn.close()

        from app.services.mailbox_health import compute_health_score, map_score_to_state
        score = compute_health_score(mb_id)
        state = map_score_to_state(score)
        assert state in ("restricted", "paused", "reduced")


class TestSchedulerCapacity:
    def test_daily_capacity_per_mailbox(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)

        domain_id = _insert_domain(conn, ws_id)
        mb1 = _insert_mailbox(conn, ws_id, domain_id, email="healthy@test.dev",
                              health_state="healthy", daily_limit=30)
        mb2 = _insert_mailbox(conn, ws_id, domain_id, email="reduced@test.dev",
                              health_state="reduced", daily_limit=30)
        mb3 = _insert_mailbox(conn, ws_id, domain_id, email="restricted@test.dev",
                              health_state="restricted", daily_limit=30)
        conn.close()

        from app.services.scheduler import get_daily_capacity
        cap = get_daily_capacity()

        # Find our mailboxes
        all_mbs = []
        for dom in cap["domains"].values():
            all_mbs.extend(dom["mailboxes"])

        mb1_info = next((m for m in all_mbs if m["id"] == mb1), None)
        mb2_info = next((m for m in all_mbs if m["id"] == mb2), None)
        mb3_info = next((m for m in all_mbs if m["id"] == mb3), None)

        assert mb1_info is not None
        assert mb1_info["effective_limit"] == 30  # 30 * 1.0

        assert mb2_info is not None
        assert mb2_info["effective_limit"] == 18  # 30 * 0.6

        assert mb3_info is not None
        assert mb3_info["effective_limit"] == 8  # 30 * 0.25

    def test_paused_mailbox_zero_capacity(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id, email="paused@test.dev",
                             health_state="paused", daily_limit=30)
        conn.close()

        from app.services.scheduler import get_daily_capacity
        cap = get_daily_capacity()
        all_mbs = []
        for dom in cap["domains"].values():
            all_mbs.extend(dom["mailboxes"])

        mb_info = next((m for m in all_mbs if m["id"] == mb), None)
        assert mb_info is not None
        assert mb_info["effective_limit"] == 0


class TestSchedulerTick:
    def test_tick_returns_correct_counts(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id, email="tick@test.dev")
        lead_id = make_lead(db_url, ws_id)
        _insert_outbound(conn, ws_id, lead_id)
        _insert_outbound(conn, ws_id, lead_id)
        conn.close()

        from app.services.scheduler import tick
        result = tick()
        assert "assigned" in result
        assert "deferred" in result
        assert result["assigned"] + result["deferred"] >= 2


class TestPacingSlots:
    def test_pacing_slots_business_days(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)
        msg_id = _insert_outbound(conn, ws_id, lead_id, mailbox_id=mb_id)
        conn.close()

        from app.services.scheduler import next_available_slot
        mailbox = {"id": mb_id, "window_start": "08:30", "window_end": "16:30",
                   "timezone": "America/New_York", "health_state": "healthy"}

        # Monday morning → slot should be same day
        monday = datetime(2026, 8, 24, 9, 0)  # Monday
        slot = next_available_slot(mailbox, monday)
        assert slot.weekday() < 5
        assert slot.hour >= 8

        # Friday afternoon → slot should be Monday
        friday_pm = datetime(2026, 8, 28, 17, 0)  # Friday 5pm
        slot = next_available_slot(mailbox, friday_pm)
        assert slot.weekday() == 0  # Monday

    def test_slot_respects_window(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        conn.close()

        from app.services.scheduler import next_available_slot
        mailbox = {"id": mb_id, "window_start": "09:00", "window_end": "17:00",
                   "timezone": "America/New_York", "health_state": "healthy"}
        now = datetime(2026, 8, 24, 9, 0)  # Monday 9am
        slot = next_available_slot(mailbox, now)
        assert slot.hour >= 9


class TestCampaignAllocation:
    def test_campaign_allocation_enforced(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        conn.close()

        # Set allocation flags
        from app.services import flags
        flags.set_flag("campaign_allocation", {
            "new_prospects_pct": 40,
            "followups_pct": 30,
            "min_new": 50,
            "max_followup": 30,
        })

        # Create 100 messages: 60 initial, 40 followup
        messages = []
        for i in range(60):
            messages.append({"id": f"m{i}", "kind": "initial", "priority": 3})
        for i in range(40):
            messages.append({"id": f"f{i}", "kind": "followup", "priority": 2})

        from app.services.scheduler import campaign_allocation_filter
        allowed, deferred = campaign_allocation_filter(messages)

        # Should be capped: initial ≤ ~50, followup ≤ ~30
        assert len(allowed) <= 80  # 50 + 30
        assert len(deferred) > 0


class TestFollowupStateMachine:
    def test_followup_created_on_initial_sent(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        seq_id = _insert_sequence(conn, ws_id)
        _insert_sequence_step(conn, seq_id, 1, offset_days=3, angle="followup1")
        _insert_sequence_step(conn, seq_id, 2, offset_days=7, angle="followup2")

        # Create a sent initial message
        msg_id = _insert_outbound(conn, ws_id, lead_id, status="sent",
                                  sequence_id=seq_id)
        # Set sent_at
        conn.execute(
            "UPDATE outbound_messages SET sent_at=now() WHERE id=%s", (msg_id,)
        )
        conn.close()

        from app.services.scheduler import on_initial_sent
        created = on_initial_sent(msg_id, lead_id, seq_id)
        assert created == 2

        # Verify followup messages exist
        conn = _conn(db_url)
        followups = conn.execute(
            """SELECT * FROM outbound_messages
               WHERE lead_id=%s AND kind='followup'
               ORDER BY eligible_at""",
            (lead_id,),
        ).fetchall()
        conn.close()
        assert len(followups) == 2
        assert followups[0]["priority"] == 2
        assert followups[1]["priority"] == 2

    def test_followup_cancelled_on_reply(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        seq_id = _insert_sequence(conn, ws_id)
        _insert_sequence_step(conn, seq_id, 1, offset_days=3)

        # Create pending followups
        _insert_outbound(conn, ws_id, lead_id, kind="followup",
                         status="queued", sequence_id=seq_id)
        _insert_outbound(conn, ws_id, lead_id, kind="followup",
                         status="scheduled", sequence_id=seq_id)

        # Create inbound reply
        _insert_message(conn, ws_id, lead_id, direction="inbound")
        conn.close()

        from app.services.scheduler import check_followup_cancellation
        result = check_followup_cancellation(lead_id)
        assert result is True

        # Verify followups cancelled
        conn = _conn(db_url)
        cancelled = conn.execute(
            """SELECT status FROM outbound_messages
               WHERE lead_id=%s AND kind='followup'""",
            (lead_id,),
        ).fetchall()
        conn.close()
        assert all(r["status"] == "cancelled" for r in cancelled)

    def test_followup_cancelled_on_terminal_status(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        seq_id = _insert_sequence(conn, ws_id)
        _insert_sequence_step(conn, seq_id, 1, offset_days=3)

        _insert_outbound(conn, ws_id, lead_id, kind="followup",
                         status="queued", sequence_id=seq_id)

        # Set lead to terminal status
        conn.execute("UPDATE leads SET status='won' WHERE id=%s", (lead_id,))
        conn.close()

        from app.services.scheduler import check_followup_cancellation
        result = check_followup_cancellation(lead_id)
        assert result is True


class TestHybridApproval:
    def test_hybrid_approval_mode(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id)
        lead_a = make_lead(db_url, ws_id)
        lead_b = make_lead(db_url, ws_id, name="Another Co")

        _insert_score(conn, ws_id, lead_a, tier="A+")
        _insert_score(conn, ws_id, lead_b, tier="B")

        msg_a = _insert_outbound(conn, ws_id, lead_a, status="queued")
        msg_b = _insert_outbound(conn, ws_id, lead_b, status="queued")
        conn.close()

        from app.services import flags
        flags.set_flag("approval_mode", "hybrid")

        from app.services.scheduler import _needs_approval
        assert _needs_approval({"id": msg_a, "lead_id": lead_a}) is True
        assert _needs_approval({"id": msg_b, "lead_id": lead_b}) is False


class TestShadowMode:
    def test_shadow_mode_blocks_sends(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)
        msg_id = _insert_outbound(conn, ws_id, lead_id, status="queued")
        conn.close()

        from app.services import flags
        flags.set_flag("shadow_mode", True)

        from app.services.scheduler import tick
        result = tick()
        # Shadow mode: messages get claimed but not actually scheduled for real send
        assert result["assigned"] >= 1

        # Verify message is shadow-claimed
        conn = _conn(db_url)
        msg = conn.execute(
            "SELECT status, shadow FROM outbound_messages WHERE id=%s", (msg_id,)
        ).fetchone()
        conn.close()
        assert msg["shadow"] is True


class TestKillSwitch:
    def test_kill_switch_pause_all(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)
        _insert_outbound(conn, ws_id, lead_id, status="queued")
        _insert_outbound(conn, ws_id, lead_id, status="queued")
        conn.close()

        from app.services import flags
        flags.set_flag("kill_switches", {
            "pause_all_sending": True,
            "pause_followups": False,
            "pause_ai_replies": False,
            "pause_hiring_campaigns": False,
            "pause_domain": {},
            "pause_mailbox": {},
            "pause_campaign": {},
        })

        from app.services.scheduler import tick
        result = tick()
        assert result["assigned"] == 0

    def test_pause_mailbox(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)
        _insert_outbound(conn, ws_id, lead_id, status="queued")
        conn.close()

        from app.services import flags
        flags.set_flag("kill_switches", {
            "pause_all_sending": False,
            "pause_followups": False,
            "pause_ai_replies": False,
            "pause_hiring_campaigns": False,
            "pause_domain": {},
            "pause_mailbox": {mb: True},
            "pause_campaign": {},
        })

        from app.services.scheduler import tick
        result = tick()
        assert result["assigned"] == 0

    def test_pause_followups_only(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb = _insert_mailbox(conn, ws_id, domain_id)
        lead_id = make_lead(db_url, ws_id)
        _insert_outbound(conn, ws_id, lead_id, kind="initial", status="queued")
        _insert_outbound(conn, ws_id, lead_id, kind="followup", status="queued")
        conn.close()

        from app.services import flags
        flags.set_flag("kill_switches", {
            "pause_all_sending": False,
            "pause_followups": True,
            "pause_ai_replies": False,
            "pause_hiring_campaigns": False,
            "pause_domain": {},
            "pause_mailbox": {},
            "pause_campaign": {},
        })

        from app.services.scheduler import tick
        result = tick()
        # Only initial should be assigned
        assert result["assigned"] >= 1


class TestReplyClassification:
    def test_classify_reply_escalation(self):
        from app.services.scheduler import classify_reply
        result = classify_reply("I am very angry and want to speak to a human about this spam")
        assert result["needs_human"] is True
        assert result["classification"] == "HUMAN_REQUIRED"

    def test_classify_reply_normal(self):
        from app.services.scheduler import classify_reply
        result = classify_reply("Thanks for reaching out, I'd love to learn more")
        assert result["needs_human"] is False

    def test_create_human_task(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        conn.close()

        from app.services.scheduler import create_human_task
        result = create_human_task(lead_id, "HUMAN_REQUIRED", "Draft response here")
        assert "task_id" in result
        assert result["classification"] == "HUMAN_REQUIRED"


class TestEligibleMessages:
    def test_eligible_messages_respects_deadline(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)

        # Eligible message
        _insert_outbound(conn, ws_id, lead_id, status="queued",
                         eligible_at=datetime.now(timezone.utc) - timedelta(hours=1))

        # Expired deadline
        _insert_outbound(conn, ws_id, lead_id, status="queued",
                         eligible_at=datetime.now(timezone.utc) - timedelta(hours=1),
                         deadline=datetime.now(timezone.utc) - timedelta(hours=2))

        # Shadow message (should not appear)
        _insert_outbound(conn, ws_id, lead_id, status="queued", shadow=True)
        conn.close()

        from app.services.scheduler import get_eligible_messages
        eligible = get_eligible_messages()
        assert len(eligible) == 1

    def test_eligible_messages_priority_order(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)

        _insert_outbound(conn, ws_id, lead_id, status="queued", priority=5)
        _insert_outbound(conn, ws_id, lead_id, status="queued", priority=1)
        _insert_outbound(conn, ws_id, lead_id, status="queued", priority=3)
        conn.close()

        from app.services.scheduler import get_eligible_messages
        eligible = get_eligible_messages()
        priorities = [m["priority"] for m in eligible]
        assert priorities == sorted(priorities)


class TestDatabaseIntegration:
    def test_health_check_event_written(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        domain_id = _insert_domain(conn, ws_id)
        mb_id = _insert_mailbox(conn, ws_id, domain_id)
        conn.close()

        from app.services.mailbox_health import compute_health_score
        compute_health_score(mb_id)

        conn = _conn(db_url)
        events = conn.execute(
            """SELECT event_type FROM mailbox_events
               WHERE mailbox_id=%s AND event_type='health_check'""",
            (mb_id,),
        ).fetchall()
        conn.close()
        assert len(events) >= 1

    def test_followup_persistence(self, db_url, workspace):
        ws_id, _ = workspace
        conn = _conn(db_url)
        lead_id = make_lead(db_url, ws_id)
        seq_id = _insert_sequence(conn, ws_id)
        _insert_sequence_step(conn, seq_id, 1, offset_days=5)
        _insert_sequence_step(conn, seq_id, 2, offset_days=10)

        msg_id = _insert_outbound(conn, ws_id, lead_id, status="sent",
                                  sequence_id=seq_id)
        conn.execute(
            "UPDATE outbound_messages SET sent_at=now() WHERE id=%s", (msg_id,)
        )
        conn.close()

        from app.services.scheduler import on_initial_sent
        created = on_initial_sent(msg_id, lead_id, seq_id)
        assert created == 2

        conn = _conn(db_url)
        followups = conn.execute(
            "SELECT kind, status FROM outbound_messages WHERE lead_id=%s AND kind='followup'",
            (lead_id,),
        ).fetchall()
        conn.close()
        assert all(f["kind"] == "followup" and f["status"] == "queued" for f in followups)
