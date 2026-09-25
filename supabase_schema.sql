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

-- Seed Sample Data (Rings, Nodes, Segments, Issues) Jika Tabel Rings Masih Kosong
DO $$
DECLARE
    ring1_id BIGINT;
    ring2_id BIGINT;
    node1_id BIGINT;
    node2_id BIGINT;
    node3_id BIGINT;
    node4_id BIGINT;
    node21_id BIGINT;
    node22_id BIGINT;
    node23_id BIGINT;
    seg2_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM rings) THEN
        -- Ring 1
        INSERT INTO rings (name, code, description)
        VALUES ('Ring 1 - Gandul ke Karet Tengsin', 'RING-01', 'Jalur transmisi backbone utama Jakarta Selatan - Jakarta Pusat')
        RETURNING id INTO ring1_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring1_id, 'POP_START', 'POP 1 - Gandul 150kV (MULAI)', 'GARDU POP-GDL', 'Jl. Raya Gandul No. 1, Depok', '-6.3312, 106.7891', '{"kapasitas": "96 Core", "pic": "Budi Santoso", "kontak": "0812-3456-7890", "tipe_daya": "DC 48V Redundant"}'::jsonb, 1)
        RETURNING id INTO node1_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring1_id, 'DCU', 'DCU 01 - Pondok Labu', 'GARDU DCU-PL-01', 'Gardu Hubung Pondok Labu, Jaksel', '-6.3150, 106.7980', '{"tipe": "DCU Smart Metering", "gardu": "GH PL-04", "kapasitas": "24 Core"}'::jsonb, 2)
        RETURNING id INTO node2_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring1_id, 'DCU', 'DCU 02 - Kebayoran Baru', 'GARDU DCU-KB-02', 'Kebayoran Baru, Jakarta Selatan', '-6.2440, 106.8000', '{"tipe": "DCU AMR & SCADA", "gardu": "GH KB-12", "kapasitas": "24 Core"}'::jsonb, 3)
        RETURNING id INTO node3_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring1_id, 'POP_END', 'POP 2 - Karet Tengsin (AKHIR)', 'GARDU POP-KRT', 'Jl. KH Mas Mansyur, Karet Tengsin, Jakpus', '-6.2088, 106.8184', '{"kapasitas": "96 Core", "pic": "Ahmad Fauzi", "kontak": "0813-9876-5432", "tipe_daya": "Dual UPS 10kVA"}'::jsonb, 4)
        RETURNING id INTO node4_id;

        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (ring1_id, node1_id, node2_id, 4500.00, 'AMAN', 'ADSS 24 Core', 'Jalur udara melintasi Jl. Fatmawati aman normal', 1);

        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (ring1_id, node2_id, node3_id, 6200.00, 'PUTUS', 'ADSS 24 Core', 'Indikasi putus total di KM 3.8 arah Blok M', 2)
        RETURNING id INTO seg2_id;

        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (ring1_id, node3_id, node4_id, 5100.00, 'AMAN', 'ADSS 24 Core', 'Jalur under-ground Sudirman - Karet normal', 3);

        INSERT INTO issues (ring_id, segment_id, title, description, category, severity, status, pic)
        VALUES (ring1_id, seg2_id, 'Kabel Fiber Cut KM 3.8 Jl. Panglima Polim', 'Kabel ADSS 24 Core terputus akibat terkena alat berat proyek galian drainase PUPR. Loss signal 100%.', 'Kabel Putus', 'CRITICAL', 'DALAM PENANGANAN', 'Tim Reaksi Cepat Icon+ Jaksel (Dedi / 0811-2233-4455)');

        INSERT INTO issues (ring_id, segment_id, title, description, category, severity, status, pic)
        VALUES (ring1_id, NULL, 'Pohon Tumbang Mendekati Span Kabel Tiang 45', 'Ditemukan dahan pohon beringin menindih kabel FO di dekat Gardu Hubung Pondok Labu, redaman mulai naik 3 dB.', 'Redaman Tinggi', 'MEDIUM', 'OPEN', 'Tim Har Ring 1');

        -- Ring 2
        INSERT INTO rings (name, code, description)
        VALUES ('Ring 2 - Cawang Sentral ke Pulogadung', 'RING-02', 'Jalur transmisi SCADA dan telekomunikasi industri Jakarta Timur')
        RETURNING id INTO ring2_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring2_id, 'POP_START', 'POP 1 - Cawang Sentral (MULAI)', 'GARDU POP-CWG', 'Gardu Induk Cawang 150kV, Jaksel', '-6.2514, 106.8682', '{"kapasitas": "48 Core", "pic": "Hendro"}'::jsonb, 1)
        RETURNING id INTO node21_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring2_id, 'DCU', 'DCU 01 - Jatinegara', 'GARDU DCU-JTN-01', 'Gardu Distribusi Jatinegara Barat', '-6.2230, 106.8700', '{"tipe": "DCU Smart Metering Industri"}'::jsonb, 2)
        RETURNING id INTO node22_id;

        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (ring2_id, 'POP_END', 'POP 2 - Pulogadung Industri (AKHIR)', 'GARDU POP-PGD', 'Kawasan Industri Pulogadung, Jaktim', '-6.1820, 106.9120', '{"kapasitas": "72 Core", "pic": "Rian Wibowo"}'::jsonb, 3)
        RETURNING id INTO node23_id;

        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (ring2_id, node21_id, node22_id, 3800.00, 'AMAN', 'ADSS 24 Core', 'Kondisi aman optimal', 1);

        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (ring2_id, node22_id, node23_id, 4200.00, 'AMAN', 'ADSS 24 Core', 'Kondisi aman optimal', 2);
    END IF;
END $$;

