-- Phase 78 (v0.8): EvaluationResult gains explicit evaluator identity and a
-- generic structured-details slot, so a future DetectionEvaluator/
-- RegressionEvaluator result can be told apart from a classification one
-- and can carry evaluator-specific structured evidence (e.g. a per-class
-- breakdown) beyond the flat metrics dict. DEFAULT 'classification'
-- applies to every pre-v0.8 row automatically - the same
-- "no manual backfill needed" pattern migration 0002 already used for
-- tolerance_ms.
ALTER TABLE evaluation_results ADD COLUMN evaluator_type TEXT NOT NULL DEFAULT 'classification';
ALTER TABLE evaluation_results ADD COLUMN details TEXT;
