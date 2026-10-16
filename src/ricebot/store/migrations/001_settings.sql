-- Heterogeneous by nature (ids, thresholds, dates), so the value is TEXT.
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
