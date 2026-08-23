import pytest

from app.services import state_machine as sm


class TestStateMachine:
    def test_happy_path(self):
        path = ["new", "enriching", "qualified", "outreach_ready", "contacted",
                "responded", "qualified_conversation", "meeting_booked",
                "meeting_held", "proposal", "won"]
        for current, target in zip(path, path[1:]):
            assert sm.can_transition(current, target), f"{current}->{target}"

    def test_cannot_skip_to_won_from_new(self):
        assert not sm.can_transition("new", "won")

    def test_kill_switch_path_always_available_pre_contact(self):
        # contacted can go to responded (kill switch fires there)
        assert sm.can_transition("contacted", "responded")
        assert sm.can_transition("outreach_ready", "contacted")

    def test_terminal_states_have_no_exits(self):
        for s in ("won", "do_not_call"):
            assert sm.TRANSITIONS[s] == set()

    def test_do_not_call_reachable_from_contacted_and_outreach_ready(self):
        assert sm.can_transition("contacted", "do_not_call")
        assert sm.can_transition("outreach_ready", "do_not_call")

    def test_transition_enforced_in_db(self, db_url, workspace):
        """Optimistic guard: transition only applies if status matches."""
        ws, _ = workspace
        import psycopg

        conn = psycopg.connect(db_url, autocommit=True)
        company = conn.execute(
            "INSERT INTO companies (workspace_id, business_name) VALUES (%s,'T') RETURNING id",
            (ws,),
        ).fetchone()[0]
        lead = conn.execute(
            "INSERT INTO leads (workspace_id, company_id) VALUES (%s,%s) RETURNING id",
            (ws, company),
        ).fetchone()[0]
        assert sm.transition(conn, str(lead), str(ws), "new", "enriching")
        # stale expectation fails silently (returns False), no double-apply
        assert not sm.transition(conn, str(lead), str(ws), "new", "enriching")
        status = conn.execute("SELECT status FROM leads WHERE id=%s", (lead,)).fetchone()[0]
        assert status == "enriching"
        conn.close()

    def test_invalid_transition_raises_http409(self, db_url, workspace):
        ws, _ = workspace
        import psycopg

        from fastapi import HTTPException

        conn = psycopg.connect(db_url, autocommit=True)
        company = conn.execute(
            "INSERT INTO companies (workspace_id, business_name) VALUES (%s,'T') RETURNING id",
            (ws,),
        ).fetchone()[0]
        lead = str(conn.execute(
            "INSERT INTO leads (workspace_id, company_id) VALUES (%s,%s) RETURNING id",
            (ws, company),
        ).fetchone()[0])
        with pytest.raises(HTTPException) as exc:
            sm.transition(conn, lead, str(ws), "new", "won")
        assert exc.value.status_code == 409
        conn.close()
