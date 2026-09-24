import unittest
from app import app
import database

class TestPLNMonitoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        database.seed_default_users()
        # Create an isolated temporary test ring so user production rings are NEVER touched
        cls.test_ring_id = database.create_new_ring(
            name="TEMP_TEST_SUITE_RING",
            code="UNIT-TEST",
            description="Isolated test ring",
            pop1_name="TEST POP 1",
            pop2_name="TEST POP 2",
            initial_distance_m=5000.0
        )

    @classmethod
    def tearDownClass(cls):
        # Clean up temporary test ring
        if hasattr(cls, 'test_ring_id') and cls.test_ring_id:
            try:
                database.delete_ring(cls.test_ring_id)
            except Exception:
                pass

    def login_as(self, client, username="admin"):
        user = database.get_user_by_username(username)
        with client.session_transaction() as sess:
            sess['user_id'] = user['id']
            sess['username'] = user['username']
            sess['role'] = user['role']
            sess['full_name'] = user['full_name']

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        self.login_as(self.client, "admin")

    def test_01_dashboard_page(self):
        # 1. Test Public Landing Portal (/)
        response_landing = self.client.get('/')
        self.assertEqual(response_landing.status_code, 200)
        self.assertIn(b'PLN Icon+', response_landing.data)

        # 2. Test Dashboard Monitoring (/dashboard)
        response_dash = self.client.get('/dashboard')
        self.assertEqual(response_dash.status_code, 200)
        self.assertIn(b'Dashboard Monitoring', response_dash.data)
        print("[OK] Test 1: Public Landing Portal (/) & Dashboard Monitoring (/dashboard) load successfully")

    def test_02_monitoring_page(self):
        response = self.client.get(f'/monitoring/{self.test_ring_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'TEST POP 1', response.data)
        self.assertIn(b'TEST POP 2', response.data)
        self.assertIn(b'Catatan Kendala', response.data)
        print(f"[OK] Test 2: Monitoring page for test ring {self.test_ring_id} loads properly")

    def test_03_api_dashboard(self):
        response = self.client.get('/api/dashboard')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('total_rings', data)
        self.assertIn('total_distance_km', data)
        self.assertIn('overall_health_pct', data)
        print(f"[OK] Test 3: API Dashboard returns valid metrics: {data['total_rings']} rings, {data['total_distance_km']} km")

    def test_04_api_segment_update(self):
        r_detail = database.get_ring_detail(self.test_ring_id)
        seg = r_detail['segments'][0]
        seg_id = seg['id']

        # Update segment to PUTUS with new distance
        response = self.client.put(f'/api/segments/{seg_id}', json={
            'distance_m': 4600,
            'status': 'PUTUS',
            'notes': 'Test Kabel Putus'
        })
        self.assertEqual(response.status_code, 200)

        # Verify updated
        updated_detail = database.get_ring_detail(self.test_ring_id)
        updated_seg = next(s for s in updated_detail['segments'] if s['id'] == seg_id)
        self.assertEqual(updated_seg['status'], 'PUTUS')
        self.assertEqual(float(updated_seg['distance_m']), 4600.0)

        # Restore to AMAN
        self.client.put(f'/api/segments/{seg_id}', json={
            'distance_m': 5000,
            'status': 'AMAN',
            'notes': 'Normal kembali'
        })
        print("[OK] Test 4: Segment status toggle to PUTUS/AMAN and distance manual update works accurately")

    def test_05_settings_page(self):
        response = self.client.get('/settings')
        self.assertEqual(response.status_code, 404)
        print("[OK] Test 5: Verified Settings page (/settings) has been removed and returns 404 Not Found")

    def test_06_dcu_auto_inherit_distance(self):
        ring_id = self.test_ring_id
        r_detail = database.get_ring_detail(ring_id)
        first_node = r_detail['nodes'][0]
        outgoing_seg = next(s for s in r_detail['segments'] if s['from_node_id'] == first_node['id'])
        expected_inherited_dist = float(outgoing_seg['distance_m'])

        # Add DCU without distance_before (simulating untouched form)
        res = self.client.post('/api/nodes', json={
            'ring_id': ring_id,
            'node_type': 'DCU',
            'name': 'Test Inherit DCU',
            'after_node_id': first_node['id'],
            'distance_before': '',
            'distance_after': 1500
        })
        self.assertEqual(res.status_code, 200)
        res_data = res.get_json()
        self.assertTrue(res_data['success'])
        new_node_id = res_data['node_id']

        # Verify segment before DCU inherited expected_inherited_dist
        updated_detail = database.get_ring_detail(ring_id)
        seg_before_dcu = next((s for s in updated_detail['segments'] if s['from_node_id'] == first_node['id'] and s['to_node_id'] == new_node_id), None)
        self.assertIsNotNone(seg_before_dcu)
        self.assertEqual(float(seg_before_dcu['distance_m']), expected_inherited_dist)

        # Clean up test node
        del_res = self.client.delete(f'/api/nodes/{new_node_id}')
        self.assertEqual(del_res.status_code, 200)
        print(f"[OK] Test 6: DCU insertion auto-inherits preceding segment distance ({expected_inherited_dist} m) accurately")

    def test_07_sse_realtime_stream(self):
        response = self.client.get(f'/api/rings/{self.test_ring_id}/events')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/event-stream')
        first_chunk = next(response.response)
        self.assertIn(b'CONNECTED', first_chunk)
        print(f"[OK] Test 7: SSE Event-Stream endpoint connects successfully and yields initial event")

    def test_08_edit_ring(self):
        # 1. Update test ring info
        res = self.client.put(f'/api/rings/{self.test_ring_id}', json={
            'name': 'UPDATED TEST RING',
            'code': 'GARDU UNIT-TEST-UPD',
            'description': 'Updated test ring description'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('UPDATED TEST RING', data['ring']['name'])

        # Verify queried back from DB
        detail = database.get_ring_detail(self.test_ring_id)
        self.assertEqual(detail['ring']['name'], 'UPDATED TEST RING')

        # 2. Test duplicate code validation using an isolated second test ring
        second_ring_id = database.create_new_ring(
            name="SECOND_TEST_RING",
            code="UNIT-TEST-DUP-TARGET",
            description="Target for collision test"
        )
        try:
            dup_res = self.client.put(f'/api/rings/{self.test_ring_id}', json={
                'name': 'DUPLICATE CODE ATTEMPT',
                'code': 'UNIT-TEST-DUP-TARGET',
                'description': 'Should fail gracefully'
            })
            self.assertEqual(dup_res.status_code, 400)
            dup_data = dup_res.get_json()
            self.assertFalse(dup_data['success'])
            self.assertIn('sudah digunakan', dup_data['error'].lower())
        finally:
            database.delete_ring(second_ring_id)

        # 3. Restore test ring code
        self.client.put(f'/api/rings/{self.test_ring_id}', json={
            'name': 'TEMP_TEST_SUITE_RING',
            'code': 'UNIT-TEST',
            'description': 'Isolated test ring'
        })
        print("[OK] Test 8: Ring editing (PUT /api/rings/<id>) and duplicate code validation work accurately")

    def test_09_viewer_role_protection(self):
        # Create a new client logged in as viewer
        viewer_client = app.test_client()
        self.login_as(viewer_client, "viewer")

        # GET pages should succeed (200 OK)
        res_dash = viewer_client.get('/')
        self.assertEqual(res_dash.status_code, 200)

        res_ring = viewer_client.get(f'/monitoring/{self.test_ring_id}')
        self.assertEqual(res_ring.status_code, 200)

        # Accessing /users (Admin page) as viewer should redirect to dashboard (302)
        res_users = viewer_client.get('/users')
        self.assertEqual(res_users.status_code, 302)

        # Attempting write API action (e.g. create ring) as viewer should return 403 Forbidden
        res_write = viewer_client.post('/api/rings', json={
            'name': 'FORBIDDEN RING',
            'code': 'GARDU FORBIDDEN'
        })
        self.assertEqual(res_write.status_code, 403)
        print("[OK] Test 9: Viewer role protection verified (Read-only access allowed, admin page redirects and write API returns 403 Forbidden)")

    def test_10_unauthenticated_guest_access(self):
        guest_client = app.test_client()

        # Public Landing Page (/) should succeed without login (200 OK)
        res_landing = guest_client.get('/')
        self.assertEqual(res_landing.status_code, 200)

        # Protected pages (/dashboard, /monitoring) redirect to /login (302 Redirect)
        res_dash = guest_client.get('/dashboard')
        self.assertEqual(res_dash.status_code, 302)

        res_ring = guest_client.get(f'/monitoring/{self.test_ring_id}')
        self.assertEqual(res_ring.status_code, 302)

        # Admin page access by guest redirects to login (302)
        res_users = guest_client.get('/users')
        self.assertEqual(res_users.status_code, 302)

        # Write API call by guest returns 401 Unauthorized
        res_api = guest_client.post('/api/rings', json={'name': 'GUEST RING', 'code': 'GARDU GUEST'})
        self.assertEqual(res_api.status_code, 401)
        print("[OK] Test 10: Unauthenticated guest access verified (Public landing / returns 200, internal pages redirect to /login with 302, write API returns 401)")

if __name__ == '__main__':
    unittest.main()

