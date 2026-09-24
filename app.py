from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response, session, g
import os
import queue
import json
import threading
from functools import wraps
import database
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'pln-icon-monitoring-secret-key-2026')

# Real-time event subscriber queues per ring_id (Server-Sent Events)
ring_subscribers_lock = threading.Lock()
ring_subscribers = {}

def notify_ring_subscribers(ring_id, data):
    """Kirim event secara instan ke seluruh browser yang terhubung ke ring_id ini."""
    if not ring_id:
        return
    try:
        ring_id = int(ring_id)
        with ring_subscribers_lock:
            queues = list(ring_subscribers.get(ring_id, []))
        for q in queues:
            try:
                q.put_nowait(data)
            except Exception:
                pass
    except Exception as e:
        print(f"Error notifying ring subscribers: {e}")

# Initialize DB on startup
with app.app_context():
    try:
        database.init_db()
    except Exception as e:
        print(f"Database init notice: {e}")

# ==============================================================================
# AUTHENTICATION & ACCESS CONTROL HELPERS
# ==============================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Silakan login terlebih dahulu!'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Silakan login terlebih dahulu!'}), 401
            return redirect(url_for('login', next=request.url))
        if session.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Akses ditolak: Hanya pengguna dengan peran Admin yang memiliki hak akses ini!'}), 403
            flash('Akses ditolak: Hanya Admin yang dapat mengakses halaman tersebut!', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_global_vars():
    storage_mode = database.get_storage_mode()
    supabase_configured = database.is_supabase_configured()
    rings = database.get_all_rings()
    
    current_user = None
    if session.get('user_id'):
        current_user = database.get_user_by_id(session['user_id'])
        if current_user:
            current_user['is_authenticated'] = True
        else:
            session.clear()

    if not current_user:
        current_user = {
            'id': None,
            'username': 'tamu',
            'full_name': 'Pengunjung',
            'role': 'viewer',
            'is_authenticated': False
        }

    return {
        'current_storage_mode': storage_mode,
        'supabase_configured': supabase_configured,
        'all_nav_rings': rings,
        'current_user': current_user
    }

# ==============================================================================
# AUTHENTICATION ROUTES
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
        
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user = database.get_user_by_username(username)
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            error = 'Username atau Password salah! Silakan periksa kembali kredensial Anda.'
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('Anda telah berhasil keluar dari sistem.', 'info')
    return redirect(url_for('landing'))

@app.route('/users', methods=['GET', 'POST'])
@admin_required
def users_page():
    message = None
    status_type = 'info'
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', 'viewer').strip()
        
        try:
            database.create_user(username, password, full_name, role)
            message = f"Pengguna baru '{username}' ({role.upper()}) berhasil dibuat!"
            status_type = 'success'
        except ValueError as ve:
            message = str(ve)
            status_type = 'error'
        except Exception as e:
            message = f"Gagal membuat akun: {e}"
            status_type = 'error'
            
    users = database.get_all_users()
    return render_template('users.html', users=users, message=message, status_type=status_type)

@app.route('/api/users/<int:user_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_manage_user(user_id):
    if request.method == 'DELETE':
        if user_id == session.get('user_id'):
            return jsonify({'success': False, 'error': 'Anda tidak dapat menghapus akun Anda sendiri yang sedang aktif!'}), 400
        try:
            database.delete_user(user_id)
            return jsonify({'success': True, 'message': 'Pengguna berhasil dihapus!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    req = request.get_json() or request.form
    full_name = req.get('full_name', '').strip()
    role = req.get('role', '').strip()
    reset_password = req.get('reset_password', '').strip()

    try:
        if full_name or role:
            database.update_user(user_id, full_name, role)
        if reset_password:
            database.update_user_password(user_id, reset_password)
        return jsonify({'success': True, 'message': 'Data akun berhasil diperbarui!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    req = request.get_json() or request.form
    old_password = req.get('old_password', '').strip()
    new_password = req.get('new_password', '').strip()

    if not old_password or not new_password:
        return jsonify({'success': False, 'error': 'Password lama dan password baru wajib diisi!'}), 400

    user = database.get_user_by_id(session['user_id'])
    if not user or not check_password_hash(user['password_hash'], old_password):
        return jsonify({'success': False, 'error': 'Password lama Anda tidak sesuai!'}), 400

    try:
        database.update_user_password(user['id'], new_password, must_change_password=0)
        return jsonify({'success': True, 'message': 'Password Anda berhasil diubah! Gunakan password baru untuk login selanjutnya.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==============================================================================
# HTML ROUTES (Landing Page Public, Dashboard & Monitoring Require Login)
# ==============================================================================

@app.route('/')
def landing():
    data = database.get_dashboard_data()
    return render_template('landing.html', data=data)

@app.route('/dashboard')
@login_required
def dashboard():
    data = database.get_dashboard_data()
    return render_template('dashboard.html', data=data)

@app.route('/monitoring')
@login_required
def monitoring_default():
    rings = database.get_all_rings()
    if rings:
        return redirect(url_for('monitoring_ring', ring_id=rings[0]['id']))
    return render_template('monitoring_empty.html')

@app.route('/monitoring/<int:ring_id>')
@login_required
def monitoring_ring(ring_id):
    ring_data = database.get_ring_detail(ring_id)
    if not ring_data:
        flash(f"Ring dengan ID {ring_id} tidak ditemukan!", "error")
        return redirect(url_for('dashboard'))
    all_rings = database.get_all_rings()
    return render_template('monitoring.html', data=ring_data, all_rings=all_rings, current_ring_id=ring_id)

# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================

@app.route('/api/dashboard', methods=['GET'])
@login_required
def api_dashboard():
    data = database.get_dashboard_data()
    return jsonify(data)

@app.route('/api/rings', methods=['GET', 'POST'])
@login_required
def api_rings():
    if request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Akses ditolak: Hanya pengguna dengan peran Admin yang dapat membuat ring baru!'}), 403
        req = request.get_json() or request.form
        name = req.get('name', '').strip()
        code = req.get('code', '').strip()
        desc = req.get('description', '').strip()
        pop1_name = req.get('pop1_name', 'POP 1 (MULAI)').strip() or 'POP 1 (MULAI)'
        pop2_name = req.get('pop2_name', 'POP 2 (AKHIR)').strip() or 'POP 2 (AKHIR)'
        raw_dist = req.get('initial_distance_m')
        try:
            dist_m = float(raw_dist) if raw_dist not in (None, '') else 5000.0
        except (ValueError, TypeError):
            dist_m = 5000.0

        if not name or not code:
            return jsonify({'success': False, 'error': 'Nama dan Kode Ring wajib diisi!'}), 400

        try:
            new_id = database.create_new_ring(name, code, desc, pop1_name, pop2_name, dist_m)
            return jsonify({'success': True, 'ring_id': new_id, 'message': 'Ring baru berhasil dibuat!'})
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400
        except Exception as e:
            err_msg = str(e)
            if 'duplicate key' in err_msg or 'rings_code_key' in err_msg or 'UNIQUE constraint' in err_msg:
                err_msg = f"Kode Ring '{code}' sudah digunakan oleh ring lain. Silakan gunakan kode yang berbeda."
            return jsonify({'success': False, 'error': err_msg}), 500

    rings = database.get_all_rings()
    return jsonify(rings)

@app.route('/api/rings/<int:ring_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_ring_detail(ring_id):
    if request.method in ('PUT', 'DELETE') and session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Akses ditolak: Hanya pengguna dengan peran Admin yang dapat mengubah/menghapus ring!'}), 403

    if request.method == 'DELETE':
        try:
            database.delete_ring(ring_id)
            return jsonify({'success': True, 'message': 'Ring berhasil dihapus!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    if request.method == 'PUT':
        req = request.get_json() or request.form
        name = (req.get('name') or '').strip()
        code = (req.get('code') or '').strip()
        desc = (req.get('description') or '').strip()

        if not name or not code:
            return jsonify({'success': False, 'error': 'Nama dan Kode Ring wajib diisi!'}), 400

        try:
            updated = database.update_ring(ring_id, name, code, desc)
            notify_ring_subscribers(ring_id, {'type': 'RING_UPDATED', 'ring': updated})
            return jsonify({
                'success': True,
                'message': 'Informasi ring berhasil diperbarui!',
                'ring': updated
            })
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400
        except Exception as e:
            err_msg = str(e)
            if 'duplicate key' in err_msg or 'rings_code_key' in err_msg or 'UNIQUE constraint' in err_msg:
                err_msg = f"Kode Ring '{code}' sudah digunakan oleh ring lain. Silakan gunakan kode yang berbeda."
            return jsonify({'success': False, 'error': err_msg}), 500

    data = database.get_ring_detail(ring_id)
    if not data:
        return jsonify({'success': False, 'error': 'Ring tidak ditemukan'}), 404
    return jsonify(data)

@app.route('/api/nodes', methods=['POST'])
@admin_required
def api_add_node():
    req = request.get_json() or request.form
    ring_id = req.get('ring_id')
    if not ring_id:
        rings = database.get_all_rings()
        if rings:
            ring_id = rings[0]['id']
        else:
            return jsonify({'success': False, 'error': 'Ring belum tersedia!'}), 400

    node_type = (req.get('node_type') or 'DCU').strip()
    if not node_type:
        node_type = 'DCU'

    # Safe float parsing without restrictions (supports any number: 0, decimals, arbitrary integers)
    def parse_float_safe(val, default_val=2000.0):
        if val is None:
            return default_val
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return default_val
        try:
            num = float(val)
            return num if num >= 0 else default_val
        except (ValueError, TypeError):
            return default_val

    # Fetch existing nodes for automatic naming and sequence order
    try:
        ring_detail = database.get_ring_detail(int(ring_id))
        existing_nodes = ring_detail.get('nodes', []) if ring_detail else []
    except Exception:
        existing_nodes = []

    existing_type_count = sum(1 for n in existing_nodes if n.get('node_type') == node_type)
    next_num = existing_type_count + 1

    name = (req.get('name') or '').strip()
    if not name:
        name = f"{node_type} {next_num:02d}"

    code = (req.get('code') or '').strip()
    if not code:
        code = f"GARDU {node_type}-{next_num:02d}"
    elif not code.upper().startswith('GARDU'):
        code = f"GARDU {code}"

    location = (req.get('location') or '').strip()
    if not location:
        location = f"Jalur Lintasan {node_type}"

    after_node_id = req.get('after_node_id')
    if not after_node_id and existing_nodes:
        # Default insertion point: before the last node (POP 2)
        if len(existing_nodes) >= 2:
            after_node_id = existing_nodes[-2]['id']
        else:
            after_node_id = existing_nodes[0]['id']

    # Inherit distance from segment after after_node_id (kotak sebelumnya)
    default_dist_before = 2000.0
    if ring_id and after_node_id:
        try:
            prev_seg = database.get_segment_after_node(int(ring_id), int(after_node_id))
            if prev_seg and prev_seg.get('distance_m') is not None:
                default_dist_before = float(prev_seg['distance_m'])
        except Exception:
            pass

    dist_before = parse_float_safe(req.get('distance_before'), default_dist_before)
    dist_after = parse_float_safe(req.get('distance_after'), 2000.0)

    detail_dict = {}
    if req.get('gardu'):
        gardu_val = str(req.get('gardu')).strip()
        if gardu_val:
            detail_dict['gardu'] = gardu_val
    if req.get('kapasitas'):
        kap_val = str(req.get('kapasitas')).strip()
        if kap_val:
            detail_dict['kapasitas'] = kap_val
    if req.get('tipe'):
        tipe_val = str(req.get('tipe')).strip()
        if tipe_val:
            detail_dict['tipe'] = tipe_val

    try:
        new_node_id = database.add_intermediate_node(
            ring_id=ring_id,
            name=name,
            node_type=node_type,
            after_node_id=after_node_id,
            code=code,
            location=location,
            detail_dict=detail_dict,
            distance_before=dist_before,
            distance_after=dist_after
        )
        notify_ring_subscribers(int(ring_id), {'type': 'TOPOLOGY_CHANGED'})
        return jsonify({'success': True, 'node_id': new_node_id, 'message': f'{node_type} ({name}) berhasil ditambahkan!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/nodes/<int:node_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_manage_node(node_id):
    if request.method == 'DELETE':
        try:
            ring_id = database.get_node_ring_id(node_id)
            ok = database.delete_node(node_id)
            if ok:
                if ring_id:
                    notify_ring_subscribers(ring_id, {'type': 'TOPOLOGY_CHANGED'})
                return jsonify({'success': True, 'message': 'Node berhasil dihapus dan segmen diperbarui!'})
            else:
                return jsonify({'success': False, 'error': 'POP Utama (Mulai/Akhir) tidak dapat dihapus!'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    req = request.get_json() or request.form
    name = req.get('name', '').strip()
    code = req.get('code', '').strip()
    location = req.get('location', '').strip()
    coordinates = req.get('coordinates', '').strip()
    detail_dict = req.get('detail', {})
    if isinstance(detail_dict, str):
        try:
            detail_dict = json.loads(detail_dict)
        except Exception:
            detail_dict = {}

    try:
        ring_id = database.get_node_ring_id(node_id)
        database.update_node(node_id, name, code, location, coordinates, detail_dict)
        if ring_id:
            notify_ring_subscribers(ring_id, {'type': 'TOPOLOGY_CHANGED'})
        return jsonify({'success': True, 'message': 'Detail node berhasil diperbarui!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/segments/<int:segment_id>', methods=['PUT'])
@admin_required
def api_update_segment(segment_id):
    req = request.get_json() or request.form
    distance_m = req.get('distance_m')
    status = req.get('status')
    notes = req.get('notes')
    from_node_id = req.get('from_node_id')
    to_node_id = req.get('to_node_id')
    ring_id = req.get('ring_id')

    if distance_m is None or not status:
        return jsonify({'success': False, 'error': 'Parameter distance_m dan status wajib ada!'}), 400

    if status not in ('AMAN', 'PUTUS'):
        return jsonify({'success': False, 'error': 'Status harus AMAN atau PUTUS!'}), 400

    try:
        res = database.update_segment(
            segment_id=segment_id,
            distance_m=float(distance_m),
            status=status,
            notes=notes,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            ring_id=ring_id
        )
        actual_segment_id = res.get('segment_id', segment_id)
        resolved_ring_id = res.get('ring_id') or ring_id
        stats = res.get('stats')

        # Push instant SSE event to all connected browsers for this ring
        if resolved_ring_id:
            notify_ring_subscribers(resolved_ring_id, {
                'type': 'SEGMENT_UPDATE',
                'segment_id': actual_segment_id,
                'distance_m': float(distance_m),
                'status': status,
                'notes': notes,
                'stats': stats
            })

        return jsonify({
            'success': True,
            'message': f'Status segmen berhasil diubah ke {status}!',
            'segment': {
                'id': actual_segment_id,
                'distance_m': float(distance_m),
                'status': status,
                'notes': notes
            },
            'stats': stats,
            'ring_id': resolved_ring_id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rings/<int:ring_id>/events')
@login_required
def api_ring_events(ring_id):
    """Server-Sent Events (SSE) stream. Browser standby tanpa spamming terminal."""
    def event_stream():
        q = queue.Queue(maxsize=50)
        with ring_subscribers_lock:
            if ring_id not in ring_subscribers:
                ring_subscribers[ring_id] = set()
            ring_subscribers[ring_id].add(q)
        try:
            yield f"data: {json.dumps({'type': 'CONNECTED', 'ring_id': ring_id})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    # Keep-alive heartbeat komentar
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            with ring_subscribers_lock:
                if ring_id in ring_subscribers and q in ring_subscribers[ring_id]:
                    ring_subscribers[ring_id].discard(q)
                    if not ring_subscribers[ring_id]:
                        del ring_subscribers[ring_id]

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/rings/<int:ring_id>/live', methods=['GET'])
@login_required
def api_ring_live(ring_id):
    try:
        live_data = database.get_ring_live_state(ring_id)
        return jsonify({'success': True, 'data': live_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/issues', methods=['POST'])
@admin_required
def api_add_issue():
    req = request.get_json() or request.form
    ring_id = req.get('ring_id')
    segment_id = req.get('segment_id')
    note_text = req.get('note', '').strip()
    title = req.get('title', '').strip()
    if not title and note_text:
        title = note_text

    description = req.get('description', '').strip()
    category = req.get('category', 'Catatan Kendala')
    severity = req.get('severity', 'HIGH')
    status = req.get('status', 'OPEN')
    pic = req.get('pic', '').strip()

    if not ring_id or not title:
        return jsonify({'success': False, 'error': 'Catatan kendala tidak boleh kosong!'}), 400

    try:
        issue_id = database.add_issue(ring_id, segment_id, title, description, category, severity, status, pic)
        return jsonify({'success': True, 'issue_id': issue_id, 'message': 'Kendala berhasil dicatat!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/issues/<int:issue_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_manage_issue(issue_id):
    if request.method == 'DELETE':
        try:
            database.delete_issue(issue_id)
            return jsonify({'success': True, 'message': 'Catatan kendala berhasil dihapus!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    req = request.get_json() or request.form
    status = req.get('status')
    title = req.get('title')

    # If only status is passed (e.g. quick toggle completed)
    if status and not title:
        try:
            database.update_issue_status(issue_id, status)
            return jsonify({'success': True, 'message': 'Status berhasil diperbarui!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    title = req.get('title', '').strip()
    description = req.get('description', '').strip()
    category = req.get('category', 'Catatan Kendala')
    severity = req.get('severity', 'HIGH')
    pic = req.get('pic', '').strip()

    try:
        database.update_issue(issue_id, title, description, category, severity, status or 'OPEN', pic)
        return jsonify({'success': True, 'message': 'Catatan berhasil diperbarui!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/seed-sample', methods=['POST'])
@admin_required
def api_seed_sample():
    try:
        if database.get_storage_mode() == 'SUPABASE':
            database.seed_supabase_data()
        else:
            conn = database.get_sqlite()
            database.seed_sqlite_data(conn)
            conn.close()
        return jsonify({'success': True, 'message': 'Data sampel berhasil diisi!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"🚀 PLN Icon+ Monitoring System running on http://127.0.0.1:{port}")
    print(f"📦 Database Mode: {database.get_storage_mode()}")
    app.run(host='0.0.0.0', port=port, debug=True)
