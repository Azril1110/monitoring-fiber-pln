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

-- 5. TABEL USERS (Autentikasi & Hak Akses Pengguna NOC / Viewer)
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    must_change_password INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Buat Index untuk performa query cepat
CREATE INDEX IF NOT EXISTS idx_nodes_ring_order ON nodes(ring_id, position_order);
CREATE INDEX IF NOT EXISTS idx_segments_ring_order ON segments(ring_id, position_order);
CREATE INDEX IF NOT EXISTS idx_issues_ring ON issues(ring_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- Disable Row Level Security (RLS) untuk kemudahan akses API server, atau aktifkan policy public
ALTER TABLE rings ENABLE ROW LEVEL SECURITY;
ALTER TABLE nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

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
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Public Access Users' AND tablename = 'users') THEN
        CREATE POLICY "Public Access Users" ON users FOR ALL USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Seed Akun Default (admin / admin123 & viewer / viewer123)
INSERT INTO users (username, password_hash, full_name, role, must_change_password)
VALUES 
    ('admin', 'scrypt:32768:8:1$an4EtXds1BND4BnQ$12838ce1722a0ef376d89274ff1a34178927c1253ac37b3272f02a021b497d58b78319e1334794de74bec1cc661fd06b97aa53d92931bef16ecf068d72516404', 'Administrator NOC', 'admin', 0),
    ('viewer', 'scrypt:32768:8:1$MjLVLJg93BLiM2Lu$06f5016a23d83c010de96c2f34afbd00e45b8ab82f70a810ac1802f26ccc9dd1fc7860b66c59052402e32bb30ff2bbb8a3f31fec1e8ca68c51ddf5ec750823bd', 'Viewer Monitoring', 'viewer', 0)
ON CONFLICT (username) DO NOTHING;

