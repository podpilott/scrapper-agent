-- Banned users table for abuse prevention
-- Allows admins to ban users who abuse LLM endpoints

CREATE TABLE IF NOT EXISTS banned_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    banned_by UUID REFERENCES auth.users(id),
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups by user_id + active status
CREATE INDEX IF NOT EXISTS idx_banned_users_user_active ON banned_users(user_id, is_active);

-- Index for finding expired bans
CREATE INDEX IF NOT EXISTS idx_banned_users_expires ON banned_users(expires_at) WHERE is_active = TRUE;

-- RLS policies
ALTER TABLE banned_users ENABLE ROW LEVEL SECURITY;

-- Only service role can read/write banned_users (not accessible to regular users)
CREATE POLICY "Service role full access to banned_users" ON banned_users
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Comment for documentation
COMMENT ON TABLE banned_users IS 'Tracks banned users for abuse prevention. Only accessible via service role.';
COMMENT ON COLUMN banned_users.user_id IS 'The banned user ID';
COMMENT ON COLUMN banned_users.reason IS 'Reason for the ban (e.g., "LLM abuse", "rate limit violations")';
COMMENT ON COLUMN banned_users.banned_by IS 'Admin who issued the ban (optional)';
COMMENT ON COLUMN banned_users.is_active IS 'Whether the ban is currently active';
COMMENT ON COLUMN banned_users.expires_at IS 'Optional expiration time for temporary bans';
