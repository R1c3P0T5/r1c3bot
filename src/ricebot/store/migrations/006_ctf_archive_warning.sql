-- Archiving retries every pass, so the warning that it is failing is said
-- once and this is what remembers it.
ALTER TABLE ctf_events ADD COLUMN archive_warned_at TEXT;
