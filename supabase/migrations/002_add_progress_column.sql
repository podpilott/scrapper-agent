-- Add progress column to jobs table for real-time progress tracking
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress JSONB;

-- Add comment for documentation
COMMENT ON COLUMN jobs.progress IS 'JSON object with step, current, total, message fields for tracking job progress';
