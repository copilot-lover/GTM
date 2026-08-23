-- Send attempt tracking + 'sending' in-flight status for atomic send claims.
ALTER TABLE messages ADD COLUMN send_attempts int NOT NULL DEFAULT 0;

ALTER TABLE messages DROP CONSTRAINT messages_status_check;
ALTER TABLE messages ADD CONSTRAINT messages_status_check CHECK (status IN
    ('drafted','pending_approval','approved','scheduled','sending','sent',
     'delivered','opened','replied','bounced','failed','rejected'));
