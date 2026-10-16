-- Values the community adjusts without a redeploy. The keys are heterogeneous
-- by nature (ids, thresholds, dates), so the column is TEXT and the repository
-- converts.
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
