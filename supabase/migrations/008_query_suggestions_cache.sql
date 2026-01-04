-- Cache for LLM-generated query suggestions
-- Reduces LLM API costs by reusing suggestions for similar queries

CREATE TABLE IF NOT EXISTS query_suggestions_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_normalized TEXT NOT NULL UNIQUE,
    suggestions JSONB NOT NULL,  -- Array of suggestion strings
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days')
);

-- Index for fast lookups and cleanup
CREATE INDEX IF NOT EXISTS idx_suggestions_cache_query ON query_suggestions_cache(query_normalized);
CREATE INDEX IF NOT EXISTS idx_suggestions_cache_expires ON query_suggestions_cache(expires_at);

-- No RLS needed - this is a shared cache across all users
-- Suggestions are generic (not user-specific data)
