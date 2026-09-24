import os
import sys

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database

def set_all_cables_putus():
    mode = database.get_storage_mode()
    print(f"Current Storage Mode: {mode}")

    # 1. Update Supabase
    if database.supabase_client:
        print("Updating all segments in Supabase to 'PUTUS'...")
        try:
            # Update all segments
            res = database.supabase_client.table('segments').update({'status': 'PUTUS'}).neq('id', 0).execute()
            print(f"Supabase update executed.")
        except Exception as e:
            print(f"Error updating Supabase segments: {e}")

    # 2. Update SQLite if database file exists
    sqlite_path = database.SQLITE_PATH
    if os.path.exists(sqlite_path):
        print(f"Updating all segments in SQLite ({sqlite_path}) to 'PUTUS'...")
        try:
            conn = database.get_sqlite()
            cursor = conn.cursor()
            cursor.execute("UPDATE segments SET status = 'PUTUS'")
            conn.commit()
            updated_count = cursor.rowcount
            conn.close()
            print(f"SQLite updated: {updated_count} rows set to 'PUTUS'.")
        except Exception as e:
            print(f"Error updating SQLite segments: {e}")

    # 3. Verification
    print("\n--- VERIFIKASI STATUS KABEL ---")
    if database.supabase_client:
        res = database.supabase_client.table('segments').select('id, status').execute()
        segs = res.data or []
        putus_count = sum(1 for s in segs if s.get('status') == 'PUTUS')
        aman_count = sum(1 for s in segs if s.get('status') == 'AMAN')
        print(f"Supabase Total Segmen: {len(segs)}")
        print(f"  - Segmen PUTUS: {putus_count}")
        print(f"  - Segmen AMAN : {aman_count}")

    dash_data = database.get_dashboard_data()
    print("\n--- DASHBOARD METRICS ---")
    print(f"Total Rings        : {dash_data.get('total_rings')}")
    print(f"Total Jarak (km)   : {dash_data.get('total_distance_km')} km")
    print(f"Jarak Putus (km)   : {dash_data.get('broken_distance_km')} km")
    print(f"Jarak Aman (km)    : {dash_data.get('safe_distance_km')} km")
    print(f"Overall Health     : {dash_data.get('overall_health_pct')}%")
    print(f"Ring Gangguan      : {dash_data.get('rings_with_issues')}")

if __name__ == '__main__':
    set_all_cables_putus()
