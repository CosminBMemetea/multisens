-- Phase 65: v0.7 resource-observation persistence.
--
-- One row per (session, configuration, metric, time window) - already a
-- small pre-aggregated summary, not a raw sample (see
-- app/domain/resources.py's own module docstring for why: this is a
-- deliberate, narrow exception to this project's "recompute, never
-- persist" norm, since a resource-measurement window cannot be
-- recomputed once it has passed). configuration_id is nullable - a
-- genuinely unattributed/system-wide reading is reported explicitly,
-- never guessed at.

CREATE TABLE resource_observations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    configuration_id TEXT,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    quality TEXT NOT NULL,
    source TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_resobs_session_cfg_metric ON resource_observations(session_id, configuration_id, metric);
