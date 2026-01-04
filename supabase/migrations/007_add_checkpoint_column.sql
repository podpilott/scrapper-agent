-- Add checkpoint column to jobs table for resume functionality
-- Stores: {step, processed_place_ids[], last_index, saved_at}
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS checkpoint JSONB;

-- Add can_resume computed-like flag based on existing leads count
-- This is informational - actual resumability is checked at runtime
COMMENT ON COLUMN jobs.checkpoint IS 'Resume checkpoint: {step, processed_place_ids[], last_index, saved_at}';

-- Add index for faster queries on resumable jobs
CREATE INDEX IF NOT EXISTS idx_jobs_checkpoint ON jobs(checkpoint) WHERE checkpoint IS NOT NULL;
