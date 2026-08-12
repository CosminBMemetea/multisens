-- Phase 11: evaluation persistence schema.
--
-- JSON-shaped fields (tags, metadata, value, metrics, confusion_matrix,
-- sensor_ids) are stored as TEXT and (de)serialized in repository.py -
-- SQLite has no native JSON column type, and a real one buys nothing at
-- this scale.

CREATE TABLE scenarios (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE ground_truth (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    timestamp_ms REAL NOT NULL,
    task TEXT NOT NULL,
    value TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_gt_session_task_ts ON ground_truth(session_id, task, timestamp_ms);

CREATE TABLE predictions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    timestamp_ms REAL NOT NULL,
    source_id TEXT NOT NULL,
    sensor_ids TEXT NOT NULL,
    configuration_id TEXT NOT NULL,
    task TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL,
    latency_ms REAL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_pred_session_cfg_task_ts ON predictions(session_id, configuration_id, task, timestamp_ms);

CREATE TABLE evaluation_results (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    configuration_id TEXT NOT NULL,
    task TEXT NOT NULL,
    format_version TEXT NOT NULL DEFAULT '1.0',
    sample_count INTEGER NOT NULL,
    matched_samples INTEGER NOT NULL,
    unmatched_predictions INTEGER NOT NULL,
    unmatched_ground_truth INTEGER NOT NULL,
    metrics TEXT NOT NULL,
    confusion_matrix TEXT,
    computed_at TEXT NOT NULL,
    UNIQUE(session_id, configuration_id, task)
);
