-- Event outbox: Postgres pushes state changes to n8n via LISTEN/NOTIFY.
-- n8n owns everything that happens in response (LLM, scraping, email transport).

CREATE TABLE event_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid,
    event_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

CREATE INDEX ix_event_outbox_unprocessed ON event_outbox (created_at DESC)
    WHERE processed_at IS NULL;

CREATE FUNCTION notify_event_outbox() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('orbit_events', NEW.event_type || '|' || NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_notify_event_outbox
    AFTER INSERT ON event_outbox
    FOR EACH ROW EXECUTE FUNCTION notify_event_outbox();
