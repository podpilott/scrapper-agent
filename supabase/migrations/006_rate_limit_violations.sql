-- Rate limit violations tracking for auto-ban system
-- Records each 429 response for progressive penalty calculation

CREATE TABLE IF NOT EXISTS rate_limit_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for counting recent violations by user
CREATE INDEX IF NOT EXISTS idx_violations_user_time ON rate_limit_violations(user_id, created_at DESC);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_violations_created ON rate_limit_violations(created_at);

-- RLS policies
ALTER TABLE rate_limit_violations ENABLE ROW LEVEL SECURITY;

-- Only service role can read/write (not accessible to regular users)
CREATE POLICY "Service role full access to rate_limit_violations" ON rate_limit_violations
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Comments for documentation
COMMENT ON TABLE rate_limit_violations IS 'Tracks rate limit violations for auto-ban system';
COMMENT ON COLUMN rate_limit_violations.user_id IS 'The user who hit the rate limit';
COMMENT ON COLUMN rate_limit_violations.endpoint IS 'The API endpoint that was rate limited';
COMMENT ON COLUMN rate_limit_violations.created_at IS 'When the violation occurred';
