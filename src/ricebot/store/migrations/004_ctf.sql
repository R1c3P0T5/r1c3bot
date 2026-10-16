-- CTFtime owns the contest's facts, so they are refreshed on every pass; the
-- columns below them are ricebot's own and survive that refresh.
CREATE TABLE ctf_events (
    ctftime_id          INTEGER PRIMARY KEY,
    title               TEXT    NOT NULL,
    starts_at_utc       TEXT    NOT NULL,
    finishes_at_utc     TEXT    NOT NULL,
    weight              REAL    NOT NULL,
    format              TEXT    NOT NULL,
    url                 TEXT    NOT NULL,
    page                TEXT    NOT NULL,
    announce_message_id INTEGER,
    channel_id          INTEGER,
    event_id            INTEGER,
    archived_at         TEXT
);

-- The archive sweep asks for contests that have finished and are still open.
CREATE INDEX ctf_events_unarchived ON ctf_events (finishes_at_utc) WHERE archived_at IS NULL;
