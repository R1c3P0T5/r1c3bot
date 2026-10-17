-- The channel is told once that the contest is over and when it closes.
ALTER TABLE ctf_events ADD COLUMN finish_notice_at TEXT;
