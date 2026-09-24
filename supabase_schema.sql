-- ============================================================================
-- SKEMA DATABASE SUPABASE UNTUK SISTEM MONITORING JARINGAN PLN ICON+
-- Jalankan script SQL ini di SQL Editor dashboard Supabase Anda
-- ============================================================================

-- 1. TABEL RINGS (Daftar Ring Jaringan Fiber)
CREATE TABLE IF NOT EXISTS rings (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. TABEL NODES (Titik-titik pada Ring: POP 1 Mulai, DCU/Titik Antara, POP 2 Akhir)
CREATE TABLE IF NOT EXISTS nodes (
    id BIGSERIAL PRIMARY KEY,
    ring_id BIGINT NOT NULL REFERENCES rings(id) ON DELETE CASCADE,
    node_type TEXT NOT NULL, -- 'POP_START', 'POP_END', 'DCU', 'ODC', 'FAT', 'TIANG'
    name TEXT NOT NULL,
    code TEXT,
    location TEXT,
    coordinates TEXT,
    detail_json JSONB DEFAULT '{}'::jsonb,
    position_order INT NOT NULL
);

-- 3. TABEL SEGMENTS (Kabel penghubung antar titik dengan jarak dan status AMAN/PUTUS)
CREATE TABLE IF NOT EXISTS segments (
    id BIGSERIAL PRIMARY KEY,
    ring_id BIGINT NOT NULL REFERENCES rings(id) ON DELETE CASCADE,
    from_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    distance_m NUMERIC(10,2) NOT NULL DEFAULT 1000.00,
    status TEXT NOT NULL DEFAULT 'AMAN', -- 'AMAN' (Hijau), 'PUTUS' (Merah)
    cable_type TEXT DEFAULT 'ADSS 24 Core',
    notes TEXT,
    position_order INT NOT NULL
);

-- 4. TABEL ISSUES (Detail Kendala / Gangguan Jaringan)
CREATE TABLE IF NOT EXISTS issues (
    id BIGSERIAL PRIMARY KEY,
    ring_id BIGINT NOT NULL REFERENCES rings(id) ON DELETE CASCADE,
    segment_id BIGINT REFERENCES segments(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'Kabel Putus', -- 'Kabel Putus', 'Redaman Tinggi', 'Galian Pihak Ketiga', dll
    severity TEXT DEFAULT 'HIGH', -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    status TEXT DEFAULT 'OPEN', -- 'OPEN', 'DALAM PENANGANAN', 'SELESAI'
    pic TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Buat Index untuk performa query cepat
CREATE INDEX IF NOT EXISTS idx_nodes_ring_order ON nodes(ring_id, position_order);
CREATE INDEX IF NOT EXISTS idx_segments_ring_order ON segments(ring_id, position_order);
CREATE INDEX IF NOT EXISTS idx_issues_ring ON issues(ring_id);

-- Disable Row Level Security (RLS) untuk kemudahan akses API server, atau aktifkan policy public
ALTER TABLE rings ENABLE ROW LEVEL SECURITY;
ALTER TABLE nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;

-- Buat Kebijakan Akses Penuh (Anon / Authenticated / Service Role)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Public Access Rings' AND tablename = 'rings') THEN
        CREATE POLICY "Public Access Rings" ON rings FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Public Access Nodes' AND tablename = 'nodes') THEN
        CREATE POLICY "Public Access Nodes" ON nodes FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Public Access Segments' AND tablename = 'segments') THEN
        CREATE POLICY "Public Access Segments" ON segments FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Public Access Issues' AND tablename = 'issues') THEN
        CREATE POLICY "Public Access Issues" ON issues FOR ALL USING (true) WITH CHECK (true);
    END IF;
END $$;
