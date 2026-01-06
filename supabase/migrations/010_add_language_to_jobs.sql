-- Migration: Add language column to jobs table
-- Created: 2026-01-06

-- Add language column to jobs table with default 'en'
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'en' NOT NULL;

-- Create index for filtering by language (useful for analytics)
CREATE INDEX IF NOT EXISTS idx_jobs_language ON jobs(language);

-- Update existing jobs to have 'en' language (redundant but explicit)
UPDATE jobs SET language = 'en' WHERE language IS NULL;

-- Add constraint to ensure valid language codes
ALTER TABLE jobs
ADD CONSTRAINT check_language_valid CHECK (language IN ('en', 'id'));

-- Add comment for documentation
COMMENT ON COLUMN jobs.language IS 'Language for AI-generated outreach messages (en=English, id=Indonesian)';
