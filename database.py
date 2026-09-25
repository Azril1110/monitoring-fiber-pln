import os
import json
from datetime import datetime
from dotenv import load_dotenv
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

# Check if Supabase is properly configured
def is_supabase_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY and not SUPABASE_URL.startswith('https://your-project'))

supabase_client = None
if is_supabase_configured():
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Warning: Failed to initialize Supabase client: {e}")
        supabase_client = None

# Check if running in Vercel / serverless environment
IS_VERCEL = bool(os.getenv('VERCEL') or os.getenv('AWS_LAMBDA_FUNCTION_NAME'))

# SQLite fallback path (Use /tmp on Vercel to avoid Read-Only filesystem crash)
if IS_VERCEL:
    SQLITE_PATH = '/tmp/monitoring_pln.db'
    ORIGINAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitoring_pln.db')
    if not os.path.exists(SQLITE_PATH) and os.path.exists(ORIGINAL_DB):
        try:
            import shutil
            shutil.copy2(ORIGINAL_DB, SQLITE_PATH)
        except Exception as e:
            print(f"Warning: Failed to copy DB to /tmp: {e}")
else:
    SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitoring_pln.db')

def get_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn

import time

# Cache for storage mode to eliminate redundant network round-trips
_storage_mode_cache = None
_storage_mode_cache_time = 0.0
_STORAGE_MODE_CACHE_TTL = 60.0  # Cache for 60 seconds

def invalidate_storage_mode_cache():
    global _storage_mode_cache, _storage_mode_cache_time
    _storage_mode_cache = None
    _storage_mode_cache_time = 0.0

# Check if Supabase tables are created and ready
def check_supabase_tables():
    if not supabase_client:
        return False
    try:
        supabase_client.table('rings').select('id').limit(1).execute()
        return True
    except Exception:
        return False

def get_storage_mode():
    global _storage_mode_cache, _storage_mode_cache_time
    now = time.time()
    if _storage_mode_cache is not None and (now - _storage_mode_cache_time) < _STORAGE_MODE_CACHE_TTL:
        return _storage_mode_cache

    if supabase_client and check_supabase_tables():
        mode = 'SUPABASE'
    elif supabase_client:
        mode = 'SUPABASE_PENDING_SCHEMA'
    else:
        mode = 'SQLITE'

    _storage_mode_cache = mode
    _storage_mode_cache_time = now
    return mode

# ==============================================================================
# INITIALIZATION & SEEDING
# ==============================================================================

def ensure_sqlite_tables():
    try:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ring_id INTEGER NOT NULL,
            node_type TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT,
            location TEXT,
            coordinates TEXT,
            detail_json TEXT DEFAULT '{}',
            position_order INTEGER NOT NULL,
            FOREIGN KEY (ring_id) REFERENCES rings(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ring_id INTEGER NOT NULL,
            from_node_id INTEGER NOT NULL,
            to_node_id INTEGER NOT NULL,
            distance_m REAL NOT NULL DEFAULT 1000.0,
            status TEXT NOT NULL DEFAULT 'AMAN',
            cable_type TEXT DEFAULT 'ADSS 24 Core',
            notes TEXT,
            position_order INTEGER NOT NULL,
            FOREIGN KEY (ring_id) REFERENCES rings(id) ON DELETE CASCADE,
            FOREIGN KEY (from_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (to_node_id) REFERENCES nodes(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ring_id INTEGER NOT NULL,
            segment_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT DEFAULT 'Kabel Putus',
            severity TEXT DEFAULT 'HIGH',
            status TEXT DEFAULT 'OPEN',
            pic TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (ring_id) REFERENCES rings(id) ON DELETE CASCADE,
            FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            must_change_password INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        cursor.execute("SELECT COUNT(*) as count FROM rings")
        if cursor.fetchone()['count'] == 0:
            seed_sqlite_data(conn)
        conn.close()
    except Exception as e:
        print(f"Notice during SQLite tables setup: {e}")

def init_db():
    ensure_sqlite_tables()
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            # Check if rings table exists in Supabase
            res = supabase_client.table('rings').select('id').limit(1).execute()
            # If empty, seed initial data to Supabase
            count_res = supabase_client.table('rings').select('id', count='exact').execute()
            if count_res.count == 0 or len(count_res.data) == 0:
                seed_supabase_data()
        except Exception as e:
            print(f"Notice during Supabase check: {e}")
            print("If tables are not created yet, please run supabase_schema.sql in Supabase SQL Editor.")
    
    seed_default_users()

def seed_sqlite_data(conn):
    cursor = conn.cursor()
    # Ring 1
    cursor.execute("""
        INSERT INTO rings (name, code, description)
        VALUES ('Ring 1 - Gandul ke Karet Tengsin', 'RING-01', 'Jalur transmisi backbone utama Jakarta Selatan - Jakarta Pusat')
    """)
    ring1_id = cursor.lastrowid
    nodes_ring1 = [
        (ring1_id, 'POP_START', 'POP 1 - Gandul 150kV (MULAI)', 'GARDU POP-GDL', 'Jl. Raya Gandul No. 1, Depok', '-6.3312, 106.7891', json.dumps({'kapasitas': '96 Core', 'pic': 'Budi Santoso', 'kontak': '0812-3456-7890', 'tipe_daya': 'DC 48V Redundant'}), 1),
        (ring1_id, 'DCU', 'DCU 01 - Pondok Labu', 'GARDU DCU-PL-01', 'Gardu Hubung Pondok Labu, Jaksel', '-6.3150, 106.7980', json.dumps({'tipe': 'DCU Smart Metering', 'gardu': 'GH PL-04', 'kapasitas': '24 Core'}), 2),
        (ring1_id, 'DCU', 'DCU 02 - Kebayoran Baru', 'GARDU DCU-KB-02', 'Kebayoran Baru, Jakarta Selatan', '-6.2440, 106.8000', json.dumps({'tipe': 'DCU AMR & SCADA', 'gardu': 'GH KB-12', 'kapasitas': '24 Core'}), 3),
        (ring1_id, 'POP_END', 'POP 2 - Karet Tengsin (AKHIR)', 'GARDU POP-KRT', 'Jl. KH Mas Mansyur, Karet Tengsin, Jakpus', '-6.2088, 106.8184', json.dumps({'kapasitas': '96 Core', 'pic': 'Ahmad Fauzi', 'kontak': '0813-9876-5432', 'tipe_daya': 'Dual UPS 10kVA'}), 4)
    ]
    cursor.executemany("""
        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, nodes_ring1)

    cursor.execute("SELECT id, position_order FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring1_id,))
    r1_node_rows = cursor.fetchall()
    segments_ring1 = [
        (ring1_id, r1_node_rows[0]['id'], r1_node_rows[1]['id'], 4500.0, 'AMAN', 'ADSS 24 Core', 'Jalur udara melintasi Jl. Fatmawati aman normal', 1),
        (ring1_id, r1_node_rows[1]['id'], r1_node_rows[2]['id'], 6200.0, 'PUTUS', 'ADSS 24 Core', 'Indikasi putus total di KM 3.8 arah Blok M', 2),
        (ring1_id, r1_node_rows[2]['id'], r1_node_rows[3]['id'], 5100.0, 'AMAN', 'ADSS 24 Core', 'Jalur under-ground Sudirman - Karet normal', 3)
    ]
    cursor.executemany("""
        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, segments_ring1)

    cursor.execute("SELECT id FROM segments WHERE ring_id = ? AND position_order = 2", (ring1_id,))
    seg_cut = cursor.fetchone()
    seg_cut_id = seg_cut['id'] if seg_cut else None

    cursor.execute("""
        INSERT INTO issues (ring_id, segment_id, title, description, category, severity, status, pic)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ring1_id, seg_cut_id,
        'Kabel Fiber Cut KM 3.8 Jl. Panglima Polim',
        'Kabel ADSS 24 Core terputus akibat terkena alat berat proyek galian drainase PUPR. Loss signal 100%.',
        'Kabel Putus', 'CRITICAL', 'DALAM PENANGANAN',
        'Tim Reaksi Cepat Icon+ Jaksel (Dedi / 0811-2233-4455)'
    ))
    cursor.execute("""
        INSERT INTO issues (ring_id, segment_id, title, description, category, severity, status, pic)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ring1_id, None,
        'Pohon Tumbang Mendekati Span Kabel Tiang 45',
        'Ditemukan dahan pohon beringin menindih kabel FO di dekat Gardu Hubung Pondok Labu, redaman mulai naik 3 dB.',
        'Redaman Tinggi', 'MEDIUM', 'OPEN', 'Tim Har Ring 1'
    ))

    # Ring 2
    cursor.execute("""
        INSERT INTO rings (name, code, description)
        VALUES ('Ring 2 - Cawang Sentral ke Pulogadung', 'RING-02', 'Jalur distribusi SCADA dan telekomunikasi industri Jakarta Timur')
    """)
    ring2_id = cursor.lastrowid
    nodes_ring2 = [
        (ring2_id, 'POP_START', 'POP 1 - Cawang Sentral (MULAI)', 'GARDU POP-CWG', 'Gardu Induk Cawang 150kV, Jaksel', '-6.2514, 106.8682', json.dumps({'kapasitas': '48 Core', 'pic': 'Hendro'}), 1),
        (ring2_id, 'DCU', 'DCU 01 - Jatinegara', 'GARDU DCU-JTN-01', 'Gardu Distribusi Jatinegara Barat', '-6.2230, 106.8700', json.dumps({'tipe': 'DCU Smart Metering Industri'}), 2),
        (ring2_id, 'DCU', 'DCU 02 - Rawamangun', 'GARDU DCU-RWM-02', 'Jl. Pemuda Rawamangun, Jaktim', '-6.1950, 106.8830', json.dumps({'tipe': 'DCU AMR'}), 3),
        (ring2_id, 'POP_END', 'POP 2 - Pulogadung Industri (AKHIR)', 'GARDU POP-PGD', 'Kawasan Industri Pulogadung, Jaktim', '-6.1820, 106.9120', json.dumps({'kapasitas': '72 Core', 'pic': 'Rian Wibowo'}), 4)
    ]
    cursor.executemany("""
        INSERT INTO nodes (ring_id, node_type, name, code, location, coordinates, detail_json, position_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, nodes_ring2)
    cursor.execute("SELECT id, position_order FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring2_id,))
    r2_node_rows = cursor.fetchall()
    segments_ring2 = [
        (ring2_id, r2_node_rows[0]['id'], r2_node_rows[1]['id'], 3800.0, 'AMAN', 'ADSS 24 Core', 'Kondisi aman optimal', 1),
        (ring2_id, r2_node_rows[1]['id'], r2_node_rows[2]['id'], 4200.0, 'AMAN', 'ADSS 24 Core', 'Kondisi aman optimal', 2),
        (ring2_id, r2_node_rows[2]['id'], r2_node_rows[3]['id'], 4900.0, 'AMAN', 'ADSS 24 Core', 'Kondisi aman optimal', 3)
    ]
    cursor.executemany("""
        INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, segments_ring2)

    conn.commit()

def seed_supabase_data():
    if not supabase_client:
        return
    try:
        # Ring 1
        r1 = supabase_client.table('rings').insert({
            'name': 'Ring 1 - Gandul ke Karet Tengsin',
            'code': 'RING-01',
            'description': 'Jalur transmisi backbone utama Jakarta Selatan - Jakarta Pusat'
        }).execute()
        ring1_id = r1.data[0]['id']

        nodes_r1_data = [
            {'ring_id': ring1_id, 'node_type': 'POP_START', 'name': 'POP 1 - Gandul 150kV (MULAI)', 'code': 'GARDU POP-GDL', 'location': 'Jl. Raya Gandul No. 1, Depok', 'coordinates': '-6.3312, 106.7891', 'detail_json': {'kapasitas': '96 Core', 'pic': 'Budi Santoso', 'kontak': '0812-3456-7890'}, 'position_order': 1},
            {'ring_id': ring1_id, 'node_type': 'DCU', 'name': 'DCU 01 - Pondok Labu', 'code': 'GARDU DCU-PL-01', 'location': 'Gardu Hubung Pondok Labu, Jaksel', 'coordinates': '-6.3150, 106.7980', 'detail_json': {'tipe': 'DCU Smart Metering', 'gardu': 'GH PL-04'}, 'position_order': 2},
            {'ring_id': ring1_id, 'node_type': 'DCU', 'name': 'DCU 02 - Kebayoran Baru', 'code': 'GARDU DCU-KB-02', 'location': 'Kebayoran Baru, Jakarta Selatan', 'coordinates': '-6.2440, 106.8000', 'detail_json': {'tipe': 'DCU AMR & SCADA'}, 'position_order': 3},
            {'ring_id': ring1_id, 'node_type': 'POP_END', 'name': 'POP 2 - Karet Tengsin (AKHIR)', 'code': 'GARDU POP-KRT', 'location': 'Jl. KH Mas Mansyur, Karet Tengsin, Jakpus', 'coordinates': '-6.2088, 106.8184', 'detail_json': {'kapasitas': '96 Core', 'pic': 'Ahmad Fauzi'}, 'position_order': 4},
        ]
        inserted_nodes_1 = supabase_client.table('nodes').insert(nodes_r1_data).execute()
        r1_nodes = sorted(inserted_nodes_1.data, key=lambda x: x['position_order'])

        segments_r1_data = [
            {'ring_id': ring1_id, 'from_node_id': r1_nodes[0]['id'], 'to_node_id': r1_nodes[1]['id'], 'distance_m': 4500.0, 'status': 'AMAN', 'cable_type': 'ADSS 24 Core', 'notes': 'Aman normal', 'position_order': 1},
            {'ring_id': ring1_id, 'from_node_id': r1_nodes[1]['id'], 'to_node_id': r1_nodes[2]['id'], 'distance_m': 6200.0, 'status': 'PUTUS', 'cable_type': 'ADSS 24 Core', 'notes': 'Putus total KM 3.8 galian PUPR', 'position_order': 2},
            {'ring_id': ring1_id, 'from_node_id': r1_nodes[2]['id'], 'to_node_id': r1_nodes[3]['id'], 'distance_m': 5100.0, 'status': 'AMAN', 'cable_type': 'ADSS 24 Core', 'notes': 'Underground aman', 'position_order': 3},
        ]
        inserted_segments_1 = supabase_client.table('segments').insert(segments_r1_data).execute()

        supabase_client.table('issues').insert([
            {
                'ring_id': ring1_id,
                'segment_id': inserted_segments_1.data[1]['id'],
                'title': 'Kabel Fiber Cut KM 3.8 Jl. Panglima Polim',
                'description': 'Kabel ADSS 24 Core terputus akibat terkena alat berat proyek galian PUPR. Loss 100%.',
                'category': 'Kabel Putus',
                'severity': 'CRITICAL',
                'status': 'DALAM PENANGANAN',
                'pic': 'Tim Reaksi Cepat Icon+ Jaksel'
            },
            {
                'ring_id': ring1_id,
                'segment_id': None,
                'title': 'Pohon Tumbang Mendekati Span Kabel Tiang 45',
                'description': 'Dahan beringin menindih kabel di Pondok Labu, redaman mulai naik.',
                'category': 'Redaman Tinggi',
                'severity': 'MEDIUM',
                'status': 'OPEN',
                'pic': 'Tim Har Ring 1'
            }
        ]).execute()

        # Ring 2
        r2 = supabase_client.table('rings').insert({
            'name': 'Ring 2 - Cawang Sentral ke Pulogadung',
            'code': 'RING-02',
            'description': 'Jalur transmisi SCADA dan telekomunikasi industri Jakarta Timur'
        }).execute()
        ring2_id = r2.data[0]['id']

        nodes_r2_data = [
            {'ring_id': ring2_id, 'node_type': 'POP_START', 'name': 'POP 1 - Cawang Sentral (MULAI)', 'code': 'GARDU POP-CWG', 'location': 'GI Cawang 150kV, Jaksel', 'coordinates': '-6.2514, 106.8682', 'detail_json': {'kapasitas': '48 Core'}, 'position_order': 1},
            {'ring_id': ring2_id, 'node_type': 'DCU', 'name': 'DCU 01 - Jatinegara', 'code': 'GARDU DCU-JTN-01', 'location': 'Gardu Jatinegara Barat', 'coordinates': '-6.2230, 106.8700', 'detail_json': {}, 'position_order': 2},
            {'ring_id': ring2_id, 'node_type': 'POP_END', 'name': 'POP 2 - Pulogadung (AKHIR)', 'code': 'GARDU POP-PGD', 'location': 'Kawasan Industri Pulogadung', 'coordinates': '-6.1820, 106.9120', 'detail_json': {'kapasitas': '72 Core'}, 'position_order': 3},
        ]
        inserted_nodes_2 = supabase_client.table('nodes').insert(nodes_r2_data).execute()
        r2_nodes = sorted(inserted_nodes_2.data, key=lambda x: x['position_order'])

        supabase_client.table('segments').insert([
            {'ring_id': ring2_id, 'from_node_id': r2_nodes[0]['id'], 'to_node_id': r2_nodes[1]['id'], 'distance_m': 3800.0, 'status': 'AMAN', 'cable_type': 'ADSS 24 Core', 'notes': 'Normal', 'position_order': 1},
            {'ring_id': ring2_id, 'from_node_id': r2_nodes[1]['id'], 'to_node_id': r2_nodes[2]['id'], 'distance_m': 4200.0, 'status': 'AMAN', 'cable_type': 'ADSS 24 Core', 'notes': 'Normal', 'position_order': 2},
        ]).execute()
        print("Successfully seeded sample data into Supabase!")
    except Exception as e:
        print(f"Error seeding Supabase: {e}")

# ==============================================================================
# DATA ACCESS FUNCTIONS
# ==============================================================================

def get_all_rings():
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('rings').select('*').order('id', desc=False).execute()
            if res.data is not None:
                return res.data
        except Exception as e:
            print(f"Supabase error in get_all_rings: {e}")
            pass
            
    try:
        ensure_sqlite_tables()
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rings ORDER BY id ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"SQLite error in get_all_rings: {e}")
        return []

def get_dashboard_data():
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            # Batch fetch all data in 4 single parallel/bulk queries instead of looping N+1 queries
            rings_res = supabase_client.table('rings').select('*').order('id', desc=False).execute()
            rings = rings_res.data or []

            segs_res = supabase_client.table('segments').select('*').order('position_order').execute()
            all_segments = segs_res.data or []

            nodes_res = supabase_client.table('nodes').select('*').order('position_order').execute()
            all_nodes = nodes_res.data or []

            issues_res = supabase_client.table('issues').select('*').neq('status', 'SELESAI').execute()
            all_open_issues = issues_res.data or []

            # Map in-memory by ring_id
            segs_by_ring = {}
            for s in all_segments:
                segs_by_ring.setdefault(s['ring_id'], []).append(s)

            nodes_by_ring = {}
            for n in all_nodes:
                nodes_by_ring.setdefault(n['ring_id'], []).append(n)

            issues_by_ring = {}
            for i in all_open_issues:
                issues_by_ring.setdefault(i['ring_id'], []).append(i)

            grand_total_distance_m = 0.0
            grand_safe_distance_m = 0.0
            total_segments_all = 0
            total_broken_segments_all = 0
            total_issues_all = 0
            ring_summaries = []

            for r in rings:
                rid = r['id']
                segments = segs_by_ring.get(rid, [])
                nodes = nodes_by_ring.get(rid, [])
                open_issues = issues_by_ring.get(rid, [])

                total_dist = sum(float(s['distance_m']) for s in segments)
                safe_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'AMAN')
                broken_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'PUTUS')
                broken_count = sum(1 for s in segments if s['status'] == 'PUTUS')
                safe_count = sum(1 for s in segments if s['status'] == 'AMAN')

                grand_total_distance_m += total_dist
                grand_safe_distance_m += safe_dist
                total_segments_all += len(segments)
                total_broken_segments_all += broken_count
                total_issues_all += len(open_issues)

                progress_pct = round((safe_dist / total_dist * 100), 1) if total_dist > 0 else 100.0

                pop1 = next((n for n in nodes if n['node_type'] == 'POP_START'), None)
                pop2 = next((n for n in nodes if n['node_type'] == 'POP_END'), None)
                dcu_count = sum(1 for n in nodes if n['node_type'] not in ('POP_START', 'POP_END'))

                ring_summaries.append({
                    'ring': r,
                    'total_distance_m': total_dist,
                    'total_distance_km': round(total_dist / 1000.0, 2),
                    'safe_distance_km': round(safe_dist / 1000.0, 2),
                    'broken_distance_km': round(broken_dist / 1000.0, 2),
                    'total_segments': len(segments),
                    'safe_segments': safe_count,
                    'broken_segments': broken_count,
                    'progress_pct': progress_pct,
                    'open_issues_count': len(open_issues),
                    'dcu_count': dcu_count,
                    'pop1_name': pop1['name'] if pop1 else 'POP 1',
                    'pop2_name': pop2['name'] if pop2 else 'POP 2',
                    'status_label': 'CRITICAL / PUTUS' if broken_count > 0 else 'NORMAL / AMAN'
                })

            overall_health_pct = round((grand_safe_distance_m / grand_total_distance_m * 100), 1) if grand_total_distance_m > 0 else 100.0

            # Recent issues with ring info
            issues_query = supabase_client.table('issues').select('*, rings(name, code)').neq('status', 'SELESAI').order('created_at', desc=True).limit(10).execute()
            recent_issues = []
            for item in issues_query.data:
                ring_info = item.get('rings') or {}
                item['ring_name'] = ring_info.get('name', 'Ring')
                item['ring_code'] = ring_info.get('code', '-')
                recent_issues.append(item)

            return {
                'storage_mode': 'SUPABASE',
                'total_rings': len(rings),
                'total_distance_m': grand_total_distance_m,
                'total_distance_km': round(grand_total_distance_m / 1000.0, 2),
                'overall_health_pct': overall_health_pct,
                'total_broken_segments': total_broken_segments_all,
                'total_safe_segments': total_segments_all - total_broken_segments_all,
                'total_segments': total_segments_all,
                'total_issues_count': total_issues_all,
                'rings': ring_summaries,
                'recent_issues': recent_issues
            }
        except Exception as e:
            print(f"Supabase error in get_dashboard_data: {e}")
            # Fallback to local if error
            pass

    # SQLite fallback
    try:
        ensure_sqlite_tables()
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rings ORDER BY id ASC")
        rings = [dict(row) for row in cursor.fetchall()]

        grand_total_distance_m = 0.0
        grand_safe_distance_m = 0.0
        total_segments_all = 0
        total_broken_segments_all = 0
        total_issues_all = 0
        ring_summaries = []

        for r in rings:
            ring_id = r['id']
            cursor.execute("SELECT * FROM segments WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
            segments = [dict(s) for s in cursor.fetchall()]
            cursor.execute("SELECT * FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
            nodes = [dict(n) for n in cursor.fetchall()]
            cursor.execute("SELECT COUNT(*) as count FROM issues WHERE ring_id = ? AND status != 'SELESAI'", (ring_id,))
            open_issues_count = cursor.fetchone()['count']
            total_issues_all += open_issues_count

            total_dist = sum(s['distance_m'] for s in segments)
            safe_dist = sum(s['distance_m'] for s in segments if s['status'] == 'AMAN')
            broken_dist = sum(s['distance_m'] for s in segments if s['status'] == 'PUTUS')
            broken_count = sum(1 for s in segments if s['status'] == 'PUTUS')
            safe_count = sum(1 for s in segments if s['status'] == 'AMAN')

            grand_total_distance_m += total_dist
            grand_safe_distance_m += safe_dist
            total_segments_all += len(segments)
            total_broken_segments_all += broken_count

            progress_pct = round((safe_dist / total_dist * 100), 1) if total_dist > 0 else 100.0
            pop1 = next((n for n in nodes if n['node_type'] == 'POP_START'), None)
            pop2 = next((n for n in nodes if n['node_type'] == 'POP_END'), None)
            dcu_count = sum(1 for n in nodes if n['node_type'] not in ('POP_START', 'POP_END'))

            ring_summaries.append({
                'ring': r,
                'total_distance_m': total_dist,
                'total_distance_km': round(total_dist / 1000.0, 2),
                'safe_distance_km': round(safe_dist / 1000.0, 2),
                'broken_distance_km': round(broken_dist / 1000.0, 2),
                'total_segments': len(segments),
                'safe_segments': safe_count,
                'broken_segments': broken_count,
                'progress_pct': progress_pct,
                'open_issues_count': open_issues_count,
                'dcu_count': dcu_count,
                'pop1_name': pop1['name'] if pop1 else 'POP 1',
                'pop2_name': pop2['name'] if pop2 else 'POP 2',
                'status_label': 'CRITICAL / PUTUS' if broken_count > 0 else 'NORMAL / AMAN'
            })

        overall_health_pct = round((grand_safe_distance_m / grand_total_distance_m * 100), 1) if grand_total_distance_m > 0 else 100.0
        cursor.execute("""
            SELECT i.*, r.name as ring_name, r.code as ring_code
            FROM issues i
            JOIN rings r ON i.ring_id = r.id
            WHERE i.status != 'SELESAI'
            ORDER BY i.created_at DESC
            LIMIT 10
        """)
        recent_issues = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {
            'storage_mode': 'SQLITE',
            'total_rings': len(rings),
            'total_distance_m': grand_total_distance_m,
            'total_distance_km': round(grand_total_distance_m / 1000.0, 2),
            'overall_health_pct': overall_health_pct,
            'total_broken_segments': total_broken_segments_all,
            'total_safe_segments': total_segments_all - total_broken_segments_all,
            'total_segments': total_segments_all,
            'total_issues_count': total_issues_all,
            'rings': ring_summaries,
            'recent_issues': recent_issues
        }
    except Exception as e:
        print(f"SQLite error in get_dashboard_data: {e}")
        return {
            'storage_mode': 'SQLITE',
            'total_rings': 0,
            'total_distance_m': 0.0,
            'total_distance_km': 0.0,
            'overall_health_pct': 100.0,
            'total_broken_segments': 0,
            'total_safe_segments': 0,
            'total_segments': 0,
            'total_issues_count': 0,
            'rings': [],
            'recent_issues': []
        }

def get_ring_detail(ring_id):
    ring_id = int(ring_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            r_res = supabase_client.table('rings').select('*').eq('id', ring_id).execute()
            if not r_res.data:
                return None
            ring = r_res.data[0]

            nodes_res = supabase_client.table('nodes').select('*').eq('ring_id', ring_id).order('position_order').execute()
            nodes = nodes_res.data
            for n in nodes:
                if isinstance(n.get('detail_json'), str):
                    try:
                        n['detail'] = json.loads(n['detail_json'])
                    except Exception:
                        n['detail'] = {}
                elif isinstance(n.get('detail_json'), dict):
                    n['detail'] = n['detail_json']
                else:
                    n['detail'] = {}

            # Map nodes by id
            node_map = {n['id']: n for n in nodes}

            segs_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).order('position_order').execute()
            segments = segs_res.data
            for s in segments:
                fn = node_map.get(s['from_node_id'], {})
                tn = node_map.get(s['to_node_id'], {})
                s['from_node_name'] = fn.get('name', 'Node')
                s['from_node_type'] = fn.get('node_type', '')
                s['to_node_name'] = tn.get('name', 'Node')
                s['to_node_type'] = tn.get('node_type', '')

            issues_res = supabase_client.table('issues').select('*').eq('ring_id', ring_id).order('created_at', desc=True).execute()
            issues = issues_res.data

            total_dist = sum(float(s['distance_m']) for s in segments)
            safe_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'AMAN')
            broken_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'PUTUS')
            broken_count = sum(1 for s in segments if s['status'] == 'PUTUS')
            safe_count = sum(1 for s in segments if s['status'] == 'AMAN')
            progress_pct = round((safe_dist / total_dist * 100), 1) if total_dist > 0 else 100.0

            return {
                'storage_mode': 'SUPABASE',
                'ring': ring,
                'nodes': nodes,
                'segments': segments,
                'issues': issues,
                'stats': {
                    'total_distance_m': total_dist,
                    'total_distance_km': round(total_dist / 1000.0, 2),
                    'safe_distance_km': round(safe_dist / 1000.0, 2),
                    'broken_distance_km': round(broken_dist / 1000.0, 2),
                    'total_segments': len(segments),
                    'safe_segments': safe_count,
                    'broken_segments': broken_count,
                    'progress_pct': progress_pct,
                    'is_healthy': broken_count == 0
                }
            }
        except Exception as e:
            print(f"Supabase error get_ring_detail: {e}")

    # SQLite fallback
    conn = get_sqlite()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rings WHERE id = ?", (ring_id,))
    ring_row = cursor.fetchone()
    if not ring_row:
        conn.close()
        return None

    ring = dict(ring_row)
    cursor.execute("SELECT * FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
    nodes = []
    for n in cursor.fetchall():
        nd = dict(n)
        try:
            nd['detail'] = json.loads(nd.get('detail_json') or '{}')
        except Exception:
            nd['detail'] = {}
        nodes.append(nd)

    cursor.execute("""
        SELECT s.*,
               fn.name as from_node_name, fn.node_type as from_node_type,
               tn.name as to_node_name, tn.node_type as to_node_type
        FROM segments s
        JOIN nodes fn ON s.from_node_id = fn.id
        JOIN nodes tn ON s.to_node_id = tn.id
        WHERE s.ring_id = ?
        ORDER BY s.position_order ASC
    """, (ring_id,))
    segments = [dict(s) for s in cursor.fetchall()]

    cursor.execute("""
        SELECT i.*, s.position_order as segment_order
        FROM issues i
        LEFT JOIN segments s ON i.segment_id = s.id
        WHERE i.ring_id = ?
        ORDER BY i.created_at DESC
    """, (ring_id,))
    issues = [dict(i) for i in cursor.fetchall()]

    total_dist = sum(s['distance_m'] for s in segments)
    safe_dist = sum(s['distance_m'] for s in segments if s['status'] == 'AMAN')
    broken_dist = sum(s['distance_m'] for s in segments if s['status'] == 'PUTUS')
    broken_count = sum(1 for s in segments if s['status'] == 'PUTUS')
    safe_count = sum(1 for s in segments if s['status'] == 'AMAN')
    progress_pct = round((safe_dist / total_dist * 100), 1) if total_dist > 0 else 100.0
    conn.close()

    return {
        'storage_mode': 'SQLITE',
        'ring': ring,
        'nodes': nodes,
        'segments': segments,
        'issues': issues,
        'stats': {
            'total_distance_m': total_dist,
            'total_distance_km': round(total_dist / 1000.0, 2),
            'safe_distance_km': round(safe_dist / 1000.0, 2),
            'broken_distance_km': round(broken_dist / 1000.0, 2),
            'total_segments': len(segments),
            'safe_segments': safe_count,
            'broken_segments': broken_count,
            'progress_pct': progress_pct,
            'is_healthy': broken_count == 0
        }
    }

def create_new_ring(name, code, description, pop1_name='POP 1 (MULAI)', pop2_name='POP 2 (AKHIR)', initial_distance_m=5000.0):
    name = (name or '').strip()
    code = (code or '').strip().upper()
    if not name or not code:
        raise ValueError("Nama dan Kode Ring wajib diisi!")

    mode = get_storage_mode()
    if mode == 'SUPABASE':
        check = supabase_client.table('rings').select('id, name').eq('code', code).execute()
        if check.data:
            existing_name = check.data[0].get('name', 'ring lain')
            raise ValueError(f"Kode Ring '{code}' sudah terdaftar pada {existing_name}. Silakan gunakan kode unik yang berbeda.")

        r = supabase_client.table('rings').insert({'name': name, 'code': code, 'description': description}).execute()
        ring_id = r.data[0]['id']

        p1 = supabase_client.table('nodes').insert({
            'ring_id': ring_id, 'node_type': 'POP_START', 'name': pop1_name,
            'code': f"GARDU POP-START-{ring_id}", 'location': 'Lokasi Awal Jaringan',
            'detail_json': {}, 'position_order': 1
        }).execute()
        pop1_id = p1.data[0]['id']

        p2 = supabase_client.table('nodes').insert({
            'ring_id': ring_id, 'node_type': 'POP_END', 'name': pop2_name,
            'code': f"GARDU POP-END-{ring_id}", 'location': 'Lokasi Akhir Jaringan',
            'detail_json': {}, 'position_order': 2
        }).execute()
        pop2_id = p2.data[0]['id']

        supabase_client.table('segments').insert({
            'ring_id': ring_id, 'from_node_id': pop1_id, 'to_node_id': pop2_id,
            'distance_m': float(initial_distance_m), 'status': 'AMAN',
            'cable_type': 'ADSS 24 Core', 'notes': 'Segmen awal', 'position_order': 1
        }).execute()
        return ring_id
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO rings (name, code, description) VALUES (?, ?, ?)", (name, code, description))
        ring_id = cursor.lastrowid
        cursor.execute("INSERT INTO nodes (ring_id, node_type, name, code, location, detail_json, position_order) VALUES (?, 'POP_START', ?, ?, 'Lokasi Awal Jaringan', '{}', 1)", (ring_id, pop1_name, f"GARDU POP-START-{ring_id}"))
        pop1_id = cursor.lastrowid
        cursor.execute("INSERT INTO nodes (ring_id, node_type, name, code, location, detail_json, position_order) VALUES (?, 'POP_END', ?, ?, 'Lokasi Akhir Jaringan', '{}', 2)", (ring_id, pop2_name, f"GARDU POP-END-{ring_id}"))
        pop2_id = cursor.lastrowid
        cursor.execute("INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order) VALUES (?, ?, ?, ?, 'AMAN', 'ADSS 24 Core', 'Segmen awal', 1)", (ring_id, pop1_id, pop2_id, float(initial_distance_m)))
        conn.commit()
        conn.close()
        return ring_id

def update_node(node_id, name, code, location, coordinates, detail_dict):
    node_id = int(node_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('nodes').update({
            'name': name,
            'code': code,
            'location': location,
            'coordinates': coordinates,
            'detail_json': detail_dict
        }).eq('id', node_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE nodes
            SET name = ?, code = ?, location = ?, coordinates = ?, detail_json = ?
            WHERE id = ?
        """, (name, code, location, coordinates, json.dumps(detail_dict), node_id))
        conn.commit()
        conn.close()

def get_segment_after_node(ring_id, node_id):
    """Mengambil segmen kabel yang keluar dari kotak/node sebelumnya."""
    if not ring_id or not node_id:
        return None
    ring_id = int(ring_id)
    node_id = int(node_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).eq('from_node_id', node_id).execute()
            return res.data[0] if res.data else None
        except Exception:
            return None
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM segments WHERE ring_id = ? AND from_node_id = ?", (ring_id, node_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

def add_intermediate_node(ring_id, name, node_type='DCU', after_node_id=None, code='', location='', detail_dict=None, distance_before=None, distance_after=2000.0):
    ring_id = int(ring_id)
    if detail_dict is None:
        detail_dict = {}

    mode = get_storage_mode()
    if mode == 'SUPABASE':
        nodes_res = supabase_client.table('nodes').select('*').eq('ring_id', ring_id).order('position_order').execute()
        nodes = nodes_res.data
        if not nodes:
            return None

        after_node = None
        if after_node_id:
            for n in nodes:
                if n['id'] == int(after_node_id):
                    after_node = n
                    break
        if not after_node:
            after_node = nodes[0]

        # Auto-inherit distance_before dari segmen sesudah kotak sebelumnya jika tidak diisi
        if distance_before is None:
            old_seg = get_segment_after_node(ring_id, after_node['id'])
            if old_seg and old_seg.get('distance_m') is not None:
                distance_before = float(old_seg['distance_m'])
            else:
                distance_before = 2000.0

        new_order = after_node['position_order'] + 1
        # Shift subsequent nodes
        for n in reversed(nodes):
            if n['position_order'] >= new_order:
                supabase_client.table('nodes').update({'position_order': n['position_order'] + 1}).eq('id', n['id']).execute()

        new_node_res = supabase_client.table('nodes').insert({
            'ring_id': ring_id,
            'node_type': node_type,
            'name': name,
            'code': code,
            'location': location,
            'detail_json': detail_dict,
            'position_order': new_order
        }).execute()
        new_node_id = new_node_res.data[0]['id']

        # Surgical segment split: find segment leaving after_node
        seg_after_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).eq('from_node_id', after_node['id']).execute()
        existing_seg = seg_after_res.data[0] if seg_after_res.data else None

        if existing_seg:
            target_next_node_id = existing_seg['to_node_id']
            seg_pos = existing_seg.get('position_order', 1)

            # Shift position_order of all subsequent segments by 1
            subsequent_segs = supabase_client.table('segments').select('id, position_order').eq('ring_id', ring_id).gt('position_order', seg_pos).order('position_order', desc=True).execute()
            for s in (subsequent_segs.data or []):
                supabase_client.table('segments').update({'position_order': s['position_order'] + 1}).eq('id', s['id']).execute()

            # Update existing segment (after_node -> new_node) preserving its ID and other fields
            supabase_client.table('segments').update({
                'to_node_id': new_node_id,
                'distance_m': float(distance_before)
            }).eq('id', existing_seg['id']).execute()

            # Insert second segment (new_node -> target_next_node_id)
            supabase_client.table('segments').insert({
                'ring_id': ring_id,
                'from_node_id': new_node_id,
                'to_node_id': target_next_node_id,
                'distance_m': float(distance_after),
                'status': 'AMAN',
                'cable_type': existing_seg.get('cable_type', 'ADSS 24 Core'),
                'notes': '',
                'position_order': seg_pos + 1
            }).execute()
        else:
            rebuild_segments_supabase(ring_id, new_node_id, distance_before, distance_after)
        return new_node_id
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
        nodes = cursor.fetchall()
        if not nodes:
            conn.close()
            return None

        after_node = None
        if after_node_id:
            for n in nodes:
                if n['id'] == int(after_node_id):
                    after_node = n
                    break
        if not after_node:
            after_node = nodes[0]

        # Auto-inherit distance_before dari segmen sesudah kotak sebelumnya jika tidak diisi
        if distance_before is None:
            cursor.execute("SELECT distance_m FROM segments WHERE ring_id = ? AND from_node_id = ?", (ring_id, after_node['id']))
            old_seg = cursor.fetchone()
            if old_seg and old_seg['distance_m'] is not None:
                distance_before = float(old_seg['distance_m'])
            else:
                distance_before = 2000.0

        new_order = after_node['position_order'] + 1
        cursor.execute("UPDATE nodes SET position_order = position_order + 1 WHERE ring_id = ? AND position_order >= ?", (ring_id, new_order))
        cursor.execute("INSERT INTO nodes (ring_id, node_type, name, code, location, detail_json, position_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (ring_id, node_type, name, code, location, json.dumps(detail_dict), new_order))
        new_node_id = cursor.lastrowid

        cursor.execute("SELECT * FROM segments WHERE ring_id = ? AND from_node_id = ?", (ring_id, after_node['id']))
        existing_seg = cursor.fetchone()
        if existing_seg:
            existing_seg = dict(existing_seg)
            target_next_node_id = existing_seg['to_node_id']
            seg_pos = existing_seg.get('position_order', 1)

            # Shift subsequent segments
            cursor.execute("UPDATE segments SET position_order = position_order + 1 WHERE ring_id = ? AND position_order > ?", (ring_id, seg_pos))
            # Update existing segment
            cursor.execute("UPDATE segments SET to_node_id = ?, distance_m = ? WHERE id = ?", (new_node_id, float(distance_before), existing_seg['id']))
            # Insert second segment
            cursor.execute("""
                INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
                VALUES (?, ?, ?, ?, 'AMAN', ?, '', ?)
            """, (ring_id, new_node_id, target_next_node_id, float(distance_after), existing_seg.get('cable_type', 'ADSS 24 Core'), seg_pos + 1))
        else:
            rebuild_ring_segments_internal(cursor, ring_id, new_node_id, distance_before, distance_after, after_node['id'])

        conn.commit()
        conn.close()
        return new_node_id

def rebuild_segments_supabase(ring_id, new_node_id=None, dist_before=None, dist_after=None):
    nodes_res = supabase_client.table('nodes').select('*').eq('ring_id', ring_id).order('position_order').execute()
    ordered_nodes = nodes_res.data
    if len(ordered_nodes) < 2:
        return

    old_segs_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).execute()
    old_segs = old_segs_res.data or []
    seg_map = {(s['from_node_id'], s['to_node_id']): s for s in old_segs}

    # Delete existing
    supabase_client.table('segments').delete().eq('ring_id', ring_id).execute()

    new_segs = []
    for idx in range(len(ordered_nodes) - 1):
        u = ordered_nodes[idx]
        v = ordered_nodes[idx + 1]
        u_id = u['id']
        v_id = v['id']
        pos = idx + 1

        dist = 2000.0
        status = 'AMAN'
        cable_type = 'ADSS 24 Core'
        notes = ''

        if (u_id, v_id) in seg_map:
            old = seg_map[(u_id, v_id)]
            dist = float(old['distance_m'])
            status = old['status']
            cable_type = old['cable_type']
            notes = old['notes'] or ''
        elif new_node_id and (u_id == new_node_id or v_id == new_node_id):
            if v_id == new_node_id and dist_before is not None:
                dist = float(dist_before)
            elif u_id == new_node_id and dist_after is not None:
                dist = float(dist_after)
        else:
            cand = next((s for s in old_segs if s['from_node_id'] == u_id or s['to_node_id'] == v_id), None)
            if cand and cand.get('distance_m') is not None:
                dist = float(cand['distance_m'])

        new_segs.append({
            'ring_id': ring_id,
            'from_node_id': u_id,
            'to_node_id': v_id,
            'distance_m': dist,
            'status': status,
            'cable_type': cable_type,
            'notes': notes,
            'position_order': pos
        })

    if new_segs:
        supabase_client.table('segments').insert(new_segs).execute()

def rebuild_ring_segments_internal(cursor, ring_id, new_node_id=None, dist_before=None, dist_after=None, after_node_id=None):
    cursor.execute("SELECT * FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
    ordered_nodes = cursor.fetchall()
    if len(ordered_nodes) < 2:
        return

    cursor.execute("SELECT * FROM segments WHERE ring_id = ?", (ring_id,))
    existing_segs = cursor.fetchall()
    seg_map = {(s['from_node_id'], s['to_node_id']): s for s in existing_segs}
    cursor.execute("DELETE FROM segments WHERE ring_id = ?", (ring_id,))

    for idx in range(len(ordered_nodes) - 1):
        u = ordered_nodes[idx]
        v = ordered_nodes[idx + 1]
        u_id = u['id']
        v_id = v['id']
        pos = idx + 1
        dist = 2000.0
        status = 'AMAN'
        cable_type = 'ADSS 48 Core'
        notes = ''

        if (u_id, v_id) in seg_map:
            old = seg_map[(u_id, v_id)]
            dist = old['distance_m']
            status = old['status']
            cable_type = old['cable_type']
            notes = old['notes'] or ''
        elif new_node_id and (u_id == new_node_id or v_id == new_node_id):
            if v_id == new_node_id and dist_before is not None:
                dist = float(dist_before)
            elif u_id == new_node_id and dist_after is not None:
                dist = float(dist_after)
        else:
            cand = next((dict(s) for s in existing_segs if s['from_node_id'] == u_id or s['to_node_id'] == v_id), None)
            if cand and cand.get('distance_m') is not None:
                dist = float(cand['distance_m'])

        cursor.execute("""
            INSERT INTO segments (ring_id, from_node_id, to_node_id, distance_m, status, cable_type, notes, position_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ring_id, u_id, v_id, dist, status, cable_type, notes, pos))

def delete_node(node_id):
    node_id = int(node_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        n_res = supabase_client.table('nodes').select('*').eq('id', node_id).execute()
        if not n_res.data:
            return False
        node = n_res.data[0]
        if node['node_type'] in ('POP_START', 'POP_END'):
            return False
        ring_id = node['ring_id']

        # Find incoming and outgoing segments before deleting
        in_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).eq('to_node_id', node_id).execute()
        out_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).eq('from_node_id', node_id).execute()
        in_seg = in_res.data[0] if in_res.data else None
        out_seg = out_res.data[0] if out_res.data else None

        if in_seg and out_seg:
            # Merged distance preserves both segment lengths (no resetting to 3000!)
            merged_dist = float(in_seg.get('distance_m', 0)) + float(out_seg.get('distance_m', 0))
            supabase_client.table('segments').update({
                'to_node_id': out_seg['to_node_id'],
                'distance_m': merged_dist
            }).eq('id', in_seg['id']).execute()
            supabase_client.table('segments').delete().eq('id', out_seg['id']).execute()

            out_pos = out_seg.get('position_order', 1)
            sub_segs = supabase_client.table('segments').select('id, position_order').eq('ring_id', ring_id).gt('position_order', out_pos).order('position_order').execute()
            for s in (sub_segs.data or []):
                supabase_client.table('segments').update({'position_order': s['position_order'] - 1}).eq('id', s['id']).execute()
        else:
            rebuild_segments_supabase(ring_id)

        supabase_client.table('nodes').delete().eq('id', node_id).execute()
        # Re-order
        rem_res = supabase_client.table('nodes').select('id').eq('ring_id', ring_id).order('position_order').execute()
        for idx, r in enumerate(rem_res.data, start=1):
            supabase_client.table('nodes').update({'position_order': idx}).eq('id', r['id']).execute()
        return True
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        node = cursor.fetchone()
        if not node:
            conn.close()
            return False
        if node['node_type'] in ('POP_START', 'POP_END'):
            conn.close()
            return False
        ring_id = node['ring_id']

        cursor.execute("SELECT * FROM segments WHERE ring_id = ? AND to_node_id = ?", (ring_id, node_id))
        in_seg = cursor.fetchone()
        cursor.execute("SELECT * FROM segments WHERE ring_id = ? AND from_node_id = ?", (ring_id, node_id))
        out_seg = cursor.fetchone()

        if in_seg and out_seg:
            in_seg = dict(in_seg)
            out_seg = dict(out_seg)
            merged_dist = float(in_seg.get('distance_m', 0)) + float(out_seg.get('distance_m', 0))
            cursor.execute("UPDATE segments SET to_node_id = ?, distance_m = ? WHERE id = ?", (out_seg['to_node_id'], merged_dist, in_seg['id']))
            cursor.execute("DELETE FROM segments WHERE id = ?", (out_seg['id'],))
            out_pos = out_seg.get('position_order', 1)
            cursor.execute("UPDATE segments SET position_order = position_order - 1 WHERE ring_id = ? AND position_order > ?", (ring_id, out_pos))
        else:
            rebuild_ring_segments_internal(cursor, ring_id)

        cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        cursor.execute("SELECT id FROM nodes WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
        remaining = cursor.fetchall()
        for idx, r in enumerate(remaining, start=1):
            cursor.execute("UPDATE nodes SET position_order = ? WHERE id = ?", (idx, r['id']))
        conn.commit()
        conn.close()
        return True

def get_node_ring_id(node_id):
    """Mengambil ring_id dari sebuah node."""
    if not node_id:
        return None
    try:
        node_id = int(node_id)
        mode = get_storage_mode()
        if mode == 'SUPABASE':
            res = supabase_client.table('nodes').select('ring_id').eq('id', node_id).execute()
            return res.data[0]['ring_id'] if res.data else None
        else:
            conn = get_sqlite()
            cursor = conn.cursor()
            cursor.execute("SELECT ring_id FROM nodes WHERE id = ?", (node_id,))
            row = cursor.fetchone()
            conn.close()
            return row['ring_id'] if row else None
    except Exception:
        return None

def get_ring_stats(ring_id):
    if not ring_id:
        return None
    ring_id = int(ring_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        segs_res = supabase_client.table('segments').select('distance_m, status').eq('ring_id', ring_id).execute()
        segments = segs_res.data or []
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT distance_m, status FROM segments WHERE ring_id = ?", (ring_id,))
        segments = [dict(s) for s in cursor.fetchall()]
        conn.close()

    total_dist = sum(float(s['distance_m']) for s in segments)
    safe_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'AMAN')
    broken_dist = sum(float(s['distance_m']) for s in segments if s['status'] == 'PUTUS')
    broken_count = sum(1 for s in segments if s['status'] == 'PUTUS')
    safe_count = sum(1 for s in segments if s['status'] == 'AMAN')
    progress_pct = round((safe_dist / total_dist * 100), 1) if total_dist > 0 else 100.0

    return {
        'total_distance_m': total_dist,
        'total_distance_km': round(total_dist / 1000.0, 2),
        'safe_distance_km': round(safe_dist / 1000.0, 2),
        'broken_distance_km': round(broken_dist / 1000.0, 2),
        'total_segments': len(segments),
        'safe_segments': safe_count,
        'broken_segments': broken_count,
        'progress_pct': progress_pct,
        'is_healthy': broken_count == 0
    }

def get_ring_live_state(ring_id):
    ring_id = int(ring_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        segs_res = supabase_client.table('segments').select('*').eq('ring_id', ring_id).order('position_order').execute()
        segments = segs_res.data or []
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM segments WHERE ring_id = ? ORDER BY position_order ASC", (ring_id,))
        segments = [dict(s) for s in cursor.fetchall()]
        conn.close()

    stats = get_ring_stats(ring_id)
    return {
        'ring_id': ring_id,
        'segments': segments,
        'stats': stats,
        'timestamp': datetime.now().isoformat()
    }

def update_segment(segment_id, distance_m, status, notes=None, from_node_id=None, to_node_id=None, ring_id=None):
    mode = get_storage_mode()
    actual_segment_id = int(segment_id) if segment_id else None
    actual_ring_id = int(ring_id) if ring_id else None

    if mode == 'SUPABASE':
        payload = {'distance_m': float(distance_m), 'status': status}
        if notes is not None:
            payload['notes'] = notes
        
        upd_res = None
        if actual_segment_id:
            try:
                upd_res = supabase_client.table('segments').update(payload).eq('id', actual_segment_id).execute()
            except Exception:
                upd_res = None

        # Fallback: jika id tidak ditemukan / 0 rows terupdate, cocokkan berdasarkan from_node_id & to_node_id
        if (not upd_res or not upd_res.data) and from_node_id and to_node_id:
            try:
                query = supabase_client.table('segments').update(payload).eq('from_node_id', int(from_node_id)).eq('to_node_id', int(to_node_id))
                if actual_ring_id:
                    query = query.eq('ring_id', actual_ring_id)
                upd_res = query.execute()
            except Exception:
                pass

        if upd_res and upd_res.data:
            actual_segment_id = upd_res.data[0].get('id', actual_segment_id)
            actual_ring_id = upd_res.data[0].get('ring_id', actual_ring_id)

        if not actual_ring_id and actual_segment_id:
            try:
                s_res = supabase_client.table('segments').select('ring_id').eq('id', actual_segment_id).execute()
                if s_res.data:
                    actual_ring_id = s_res.data[0]['ring_id']
            except Exception:
                pass
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        updated_rows = 0
        if actual_segment_id:
            if notes is not None:
                cursor.execute("UPDATE segments SET distance_m = ?, status = ?, notes = ? WHERE id = ?", (float(distance_m), status, notes, actual_segment_id))
            else:
                cursor.execute("UPDATE segments SET distance_m = ?, status = ? WHERE id = ?", (float(distance_m), status, actual_segment_id))
            updated_rows = cursor.rowcount

        # Fallback SQLite
        if updated_rows == 0 and from_node_id and to_node_id:
            if actual_ring_id:
                if notes is not None:
                    cursor.execute("UPDATE segments SET distance_m = ?, status = ?, notes = ? WHERE from_node_id = ? AND to_node_id = ? AND ring_id = ?", (float(distance_m), status, notes, int(from_node_id), int(to_node_id), actual_ring_id))
                else:
                    cursor.execute("UPDATE segments SET distance_m = ?, status = ? WHERE from_node_id = ? AND to_node_id = ? AND ring_id = ?", (float(distance_m), status, int(from_node_id), int(to_node_id), actual_ring_id))
            else:
                if notes is not None:
                    cursor.execute("UPDATE segments SET distance_m = ?, status = ?, notes = ? WHERE from_node_id = ? AND to_node_id = ?", (float(distance_m), status, notes, int(from_node_id), int(to_node_id)))
                else:
                    cursor.execute("UPDATE segments SET distance_m = ?, status = ? WHERE from_node_id = ? AND to_node_id = ?", (float(distance_m), status, int(from_node_id), int(to_node_id)))

            cursor.execute("SELECT id, ring_id FROM segments WHERE from_node_id = ? AND to_node_id = ?", (int(from_node_id), int(to_node_id)))
            row = cursor.fetchone()
            if row:
                actual_segment_id = row['id']
                actual_ring_id = row['ring_id']

        if not actual_ring_id and actual_segment_id:
            cursor.execute("SELECT ring_id FROM segments WHERE id = ?", (actual_segment_id,))
            row = cursor.fetchone()
            if row:
                actual_ring_id = row['ring_id']

        conn.commit()
        conn.close()

    stats = get_ring_stats(actual_ring_id) if actual_ring_id else None
    return {'segment_id': actual_segment_id, 'ring_id': actual_ring_id, 'stats': stats}

def add_issue(ring_id, segment_id, title, description, category, severity, status, pic):
    ring_id = int(ring_id)
    seg_id = int(segment_id) if segment_id else None
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        res = supabase_client.table('issues').insert({
            'ring_id': ring_id,
            'segment_id': seg_id,
            'title': title,
            'description': description,
            'category': category,
            'severity': severity,
            'status': status,
            'pic': pic
        }).execute()
        return res.data[0]['id'] if res.data else None
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO issues (ring_id, segment_id, title, description, category, severity, status, pic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ring_id, seg_id, title, description, category, severity, status, pic))
        issue_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return issue_id

def update_issue_status(issue_id, status):
    issue_id = int(issue_id)
    mode = get_storage_mode()
    resolved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'SELESAI' else None
    if mode == 'SUPABASE':
        supabase_client.table('issues').update({
            'status': status,
            'resolved_at': resolved_at
        }).eq('id', issue_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("UPDATE issues SET status = ?, resolved_at = ? WHERE id = ?", (status, resolved_at, issue_id))
        conn.commit()
        conn.close()

def update_issue(issue_id, title, description, category, severity, status, pic):
    issue_id = int(issue_id)
    mode = get_storage_mode()
    resolved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'SELESAI' else None
    if mode == 'SUPABASE':
        supabase_client.table('issues').update({
            'title': title,
            'description': description,
            'category': category,
            'severity': severity,
            'status': status,
            'pic': pic,
            'resolved_at': resolved_at
        }).eq('id', issue_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE issues
            SET title = ?, description = ?, category = ?, severity = ?, status = ?, pic = ?, resolved_at = ?
            WHERE id = ?
        """, (title, description, category, severity, status, pic, resolved_at, issue_id))
        conn.commit()
        conn.close()

def delete_issue(issue_id):
    issue_id = int(issue_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('issues').delete().eq('id', issue_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
        conn.commit()
        conn.close()

def delete_ring(ring_id):
    ring_id = int(ring_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('rings').delete().eq('id', ring_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rings WHERE id = ?", (ring_id,))
        conn.commit()
        conn.close()

def update_ring(ring_id, name, code, description=''):
    ring_id = int(ring_id)
    name = (name or '').strip()
    code = (code or '').strip().upper()
    description = (description or '').strip()

    if not name or not code:
        raise ValueError("Nama dan Kode Ring wajib diisi!")

    mode = get_storage_mode()
    if mode == 'SUPABASE':
        # Cek apakah kode sudah digunakan oleh ring lain
        check_res = supabase_client.table('rings').select('id, name').eq('code', code).neq('id', ring_id).execute()
        if check_res.data:
            existing_name = check_res.data[0].get('name', 'ring lain')
            raise ValueError(f"Kode Ring '{code}' sudah digunakan oleh {existing_name}. Silakan gunakan kode yang berbeda.")

        upd = supabase_client.table('rings').update({
            'name': name,
            'code': code,
            'description': description
        }).eq('id', ring_id).execute()
        return upd.data[0] if upd.data else {'id': ring_id, 'name': name, 'code': code, 'description': description}
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM rings WHERE code = ? AND id != ?", (code, ring_id))
        row = cursor.fetchone()
        if row:
            existing_name = row['name']
            conn.close()
            raise ValueError(f"Kode Ring '{code}' sudah digunakan oleh {existing_name}. Silakan gunakan kode yang berbeda.")

        cursor.execute("UPDATE rings SET name = ?, code = ?, description = ? WHERE id = ?", (name, code, description, ring_id))
        conn.commit()
        conn.close()
        return {'id': ring_id, 'name': name, 'code': code, 'description': description}

# ==============================================================================
# USER MANAGEMENT & AUTHENTICATION DATA ACCESS
# ==============================================================================

def seed_default_users():
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('users').select('id').limit(1).execute()
            if not res.data:
                supabase_client.table('users').insert([
                    {
                        'username': 'admin',
                        'password_hash': generate_password_hash('admin123'),
                        'full_name': 'Administrator NOC',
                        'role': 'admin',
                        'must_change_password': 0
                    },
                    {
                        'username': 'viewer',
                        'password_hash': generate_password_hash('viewer123'),
                        'full_name': 'Viewer Monitoring',
                        'role': 'viewer',
                        'must_change_password': 0
                    }
                ]).execute()
        except Exception as e:
            print(f"Supabase users seed notice: {e}")
    
    # Always ensure SQLite users table is seeded for local fallback
    try:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            must_change_password INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        if cursor.fetchone()['count'] == 0:
            admin_hash = generate_password_hash('admin123')
            viewer_hash = generate_password_hash('viewer123')
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, must_change_password)
                VALUES ('admin', ?, 'Administrator NOC', 'admin', 0)
            """, (admin_hash,))
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, must_change_password)
                VALUES ('viewer', ?, 'Viewer Monitoring', 'viewer', 0)
            """, (viewer_hash,))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite users seed notice: {e}")

def get_user_by_username(username):
    username = (username or '').strip().lower()
    if not username:
        return None
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('users').select('*').eq('username', username).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
    
    try:
        ensure_sqlite_tables()
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def get_user_by_id(user_id):
    if not user_id:
        return None
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return None
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('users').select('*').eq('id', user_id).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
            
    try:
        ensure_sqlite_tables()
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def get_all_users():
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        try:
            res = supabase_client.table('users').select('id, username, full_name, role, must_change_password, created_at').order('id').execute()
            if res.data is not None:
                return res.data
        except Exception:
            pass
            
    try:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, full_name, role, must_change_password, created_at FROM users ORDER BY id ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []

def create_user(username, password, full_name, role='viewer', must_change_password=0):
    username = (username or '').strip().lower()
    full_name = (full_name or '').strip()
    role = (role or 'viewer').strip().lower()
    if role not in ('admin', 'viewer'):
        role = 'viewer'
    if not username or not password or not full_name:
        raise ValueError("Username, Password, dan Nama Lengkap wajib diisi!")

    existing = get_user_by_username(username)
    if existing:
        raise ValueError(f"Username '{username}' sudah digunakan oleh pengguna lain!")

    pwd_hash = generate_password_hash(password)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        res = supabase_client.table('users').insert({
            'username': username,
            'password_hash': pwd_hash,
            'full_name': full_name,
            'role': role,
            'must_change_password': int(must_change_password)
        }).execute()
        return res.data[0]['id'] if res.data else None
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, must_change_password)
            VALUES (?, ?, ?, ?, ?)
        """, (username, pwd_hash, full_name, role, int(must_change_password)))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return new_id

def update_user_password(user_id, new_password, must_change_password=0):
    user_id = int(user_id)
    if not new_password:
        raise ValueError("Password baru tidak boleh kosong!")
    pwd_hash = generate_password_hash(new_password)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('users').update({
            'password_hash': pwd_hash,
            'must_change_password': int(must_change_password)
        }).eq('id', user_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?
        """, (pwd_hash, int(must_change_password), user_id))
        conn.commit()
        conn.close()

def update_user(user_id, full_name, role):
    user_id = int(user_id)
    full_name = (full_name or '').strip()
    role = (role or 'viewer').strip().lower()
    if role not in ('admin', 'viewer'):
        role = 'viewer'
    if not full_name:
        raise ValueError("Nama lengkap wajib diisi!")

    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('users').update({
            'full_name': full_name,
            'role': role
        }).eq('id', user_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users SET full_name = ?, role = ? WHERE id = ?
        """, (full_name, role, user_id))
        conn.commit()
        conn.close()

def delete_user(user_id):
    user_id = int(user_id)
    mode = get_storage_mode()
    if mode == 'SUPABASE':
        supabase_client.table('users').delete().eq('id', user_id).execute()
    else:
        conn = get_sqlite()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
