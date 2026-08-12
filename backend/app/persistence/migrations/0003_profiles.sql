-- Phase 32: v0.4 requirement profile persistence.
--
-- One validated JSON document per profile, not normalized group/
-- requirement tables - see the architecture review on issue #31: a
-- profile is always read whole (coverage needs the entire hierarchy),
-- never queried partially, and every other structured field in this
-- schema is already "TEXT, (de)serialized in repository.py" - a profile
-- document is just a bigger instance of the same pattern.
--
-- name/version are pulled out as real columns (not just fields inside
-- `document`) purely so list_profiles can sort/display without parsing
-- every document - id remains the sole identity key, there is no
-- separate uniqueness constraint on (name, version).

CREATE TABLE evaluation_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL
);
