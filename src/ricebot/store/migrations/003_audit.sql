-- Who ran what, so a change made through the bot can be traced to a person.
CREATE TABLE audit_log (
    id        INTEGER PRIMARY KEY,
    at_utc    TEXT    NOT NULL,
    user_id   INTEGER NOT NULL,
    -- A snapshot: the id stops resolving once the member leaves the guild.
    user_name TEXT    NOT NULL,
    command   TEXT    NOT NULL,
    options   TEXT    NOT NULL
);

CREATE INDEX audit_log_at ON audit_log (at_utc DESC);
