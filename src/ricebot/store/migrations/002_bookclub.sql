-- A session row exists only once something is recorded about it; the schedule
-- itself is derived from the anchor date.
CREATE TABLE sessions (
    id                  INTEGER PRIMARY KEY,
    starts_at_utc       TEXT    NOT NULL UNIQUE,
    host_user_id        INTEGER,  -- who actually hosts
    rotation_user_id    INTEGER,  -- whose turn it counts as; differs after a swap
    topic               TEXT,
    event_id            INTEGER,
    announce_message_id INTEGER,
    cancelled_at        TEXT
);

CREATE TABLE session_skips (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    PRIMARY KEY (session_id, user_id)
);

CREATE TABLE bookclub_reminders (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL,
    sent_at    TEXT    NOT NULL,
    PRIMARY KEY (session_id, kind)
);
