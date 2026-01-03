-- Demo leads table for public sample data
-- This table is accessible without authentication

CREATE TABLE IF NOT EXISTS demo_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    whatsapp TEXT,
    website TEXT,
    address TEXT,
    category TEXT,
    rating DECIMAL(2,1),
    review_count INTEGER DEFAULT 0,
    score DECIMAL(4,1) DEFAULT 0,
    tier VARCHAR(10),
    maps_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- No RLS on this table - it's public demo data

-- Insert sample demo data
INSERT INTO demo_leads (name, category, rating, review_count, score, tier, address, phone, website, whatsapp) VALUES
('Kopi Kenangan Menteng', 'Coffee Shop', 4.5, 1250, 75.0, 'hot', 'Jl. Menteng Raya No.12, Jakarta', '+62218765432', 'https://kopikenangan.id', '62218765432'),
('Warung Makan Sederhana', 'Restaurant', 4.2, 856, 65.0, 'warm', 'Jl. Sudirman No.45, Bandung', '+62227654321', NULL, '62227654321'),
('Salon Cantik Sejati', 'Beauty Salon', 4.8, 2100, 80.0, 'hot', 'Jl. Raya Kuta No.88, Bali', '+62361876543', 'https://saloncantik.co.id', '62361876543'),
('Bengkel Motor Jaya', 'Auto Repair', 4.3, 432, 60.0, 'warm', 'Jl. Ahmad Yani No.22, Surabaya', '+62318765123', NULL, '62318765123'),
('Apotek Sehat Selalu', 'Pharmacy', 4.6, 780, 70.0, 'warm', 'Jl. Gatot Subroto No.15, Semarang', '+62247891234', 'https://apoteksehat.com', '62247891234');
