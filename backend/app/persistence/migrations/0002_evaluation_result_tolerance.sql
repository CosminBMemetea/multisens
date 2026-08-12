-- Phase 14: an EvaluationResult must record the tolerance_ms that produced
-- its matched/unmatched split - otherwise the numbers aren't reproducible
-- or auditable later. DEFAULT 0 only matters for a pre-existing row from
-- before this column existed (none in practice yet, v0.2 is unreleased).
ALTER TABLE evaluation_results ADD COLUMN tolerance_ms REAL NOT NULL DEFAULT 0;
