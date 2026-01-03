-- Add enhanced lead fields for better deduplication and enrichment
-- These fields come from SerpAPI Google Maps data

-- Add missing columns to leads table
ALTER TABLE leads
ADD COLUMN IF NOT EXISTS place_id TEXT,
ADD COLUMN IF NOT EXISTS price_level TEXT,
ADD COLUMN IF NOT EXISTS photos_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS is_claimed BOOLEAN,
ADD COLUMN IF NOT EXISTS years_in_business INTEGER;

-- Add index for deduplication by place_id (most reliable identifier)
CREATE INDEX IF NOT EXISTS idx_leads_user_place_id ON leads(user_id, place_id);

-- Add index for deduplication by phone (fallback)
CREATE INDEX IF NOT EXISTS idx_leads_user_phone ON leads(user_id, phone);

-- Comment on new columns
COMMENT ON COLUMN leads.place_id IS 'Google Maps place ID for deduplication';
COMMENT ON COLUMN leads.price_level IS 'Price level indicator ($, $$, $$$, $$$$)';
COMMENT ON COLUMN leads.photos_count IS 'Number of photos on Google Maps listing';
COMMENT ON COLUMN leads.is_claimed IS 'Whether the business has claimed their listing';
COMMENT ON COLUMN leads.years_in_business IS 'Years the business has been operating';
