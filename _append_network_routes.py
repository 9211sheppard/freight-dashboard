path = r'C:\Users\Owner\Desktop\claude code\contact-dashboard\tms\tms_routes.py'

new_routes = """

# ══════════════════════════════════════════════════════════════════════════════
#  INTEGRATION HUB — Smart Connect
# ══════════════════════════════════════════════════════════════════════════════
@tms.route('/integrations')
def integrations():
    from tms.tms_integrations import INTEGRATIONS, CATEGORY_ORDER
    from collections import OrderedDict
    conn = get_db()
    rows = conn.execute("SELECT integration_key, status, last_tested, last_error FROM integration_connections").fetchall()
    conn.close()
    connected = {r['integration_key']: dict(r) for r in rows}
    grouped = OrderedDict()
    for cat in CATEGORY_ORDER:
        grouped[cat] = []
    for key, data in INTEGRATIONS.items():
        cat = data.get('category', 'Other')
        if cat not in grouped:
            grouped[cat] = []
        item = dict(data)
        item['key'] = key
        conn_data = connected.get(key)
        item['connected'] = conn_data is not None and conn_data['status'] == 'connected'
        item['conn_data'] = conn_data
        grouped[cat].append(item)
    grouped = {k: v for k, v in grouped.items() if v}
    total = len(INTEGRATIONS)
    total_connected = sum(1 for v in connected.values() if v['status'] == 'connected')
    return render_template('tms/integrations.html',
        grouped=grouped, total=total, total_connected=total_connected,
        integrations=INTEGRATIONS)


@tms.route('/integrations/connect', methods=['POST'])
def integrations_connect():
    from tms.tms_integrations import INTEGRATIONS, encrypt_key
    import json as _json
    key = request.form.get('integration_key', '')
    if key not in INTEGRATIONS:
        flash('Unknown integration.', 'danger')
        return redirect(url_for('tms.integrations'))
    integ = INTEGRATIONS[key]
    fields = integ.get('fields', [])
    plain = {f['key']: request.form.get(f['key'], '') for f in fields}
    encrypted = {k: encrypt_key(v) for k, v in plain.items() if v}
    conn = get_db()
    conn.execute(
        \"\"\"INSERT INTO integration_connections (integration_key, encrypted_fields, status, updated_at)
           VALUES (?, ?, 'connected', CURRENT_TIMESTAMP)
           ON CONFLICT(tenant_id, integration_key) DO UPDATE SET
               encrypted_fields=excluded.encrypted_fields,
               status='connected', last_error='', updated_at=CURRENT_TIMESTAMP\"\"\",
        (key, _json.dumps(encrypted)))
    conn.commit()
    conn.close()
    flash(f"{integ['name']} connected.", 'success')
    return redirect(url_for('tms.integrations'))


@tms.route('/integrations/disconnect', methods=['POST'])
def integrations_disconnect():
    from tms.tms_integrations import INTEGRATIONS
    key = request.form.get('integration_key', '')
    conn = get_db()
    conn.execute("DELETE FROM integration_connections WHERE integration_key=?", (key,))
    conn.commit()
    conn.close()
    name = INTEGRATIONS.get(key, {}).get('name', key)
    flash(f"{name} disconnected.", 'info')
    return redirect(url_for('tms.integrations'))


@tms.route('/integrations/test/<key>', methods=['POST'])
def integrations_test(key):
    conn = get_db()
    row = conn.execute("SELECT encrypted_fields FROM integration_connections WHERE integration_key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return jsonify(ok=False, message="Not connected")
    return jsonify(ok=True, message="Connected. Live test requires platform credentials.")


# ══════════════════════════════════════════════════════════════════════════════
#  FLASH NETWORK — Internal Community Load Board
# ══════════════════════════════════════════════════════════════════════════════
@tms.route('/network', methods=['GET', 'POST'])
def flash_network():
    conn = get_db()
    if request.method == 'POST':
        ptype = request.form.get('post_type', 'load')
        company = request.form.get('company_name', 'My Company')
        if ptype == 'load':
            conn.execute(
                \"\"\"INSERT INTO network_loads
                   (posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, cargo_type, weight_kg, volume_cbm,
                    ready_date, equipment_type, rate_usd, rate_type, mode, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)\"\"\",
                (request.form.get('posted_by',''),
                 company,
                 request.form.get('origin_city',''),
                 request.form.get('origin_country',''),
                 request.form.get('dest_city',''),
                 request.form.get('dest_country',''),
                 request.form.get('cargo_type',''),
                 float(request.form.get('weight_kg') or 0),
                 float(request.form.get('volume_cbm') or 0),
                 request.form.get('ready_date',''),
                 request.form.get('equipment_type','any'),
                 float(request.form.get('rate_usd') or 0),
                 request.form.get('rate_type','negotiable'),
                 request.form.get('mode','any'),
                 request.form.get('notes','')))
            flash('Load posted to Flash Network.', 'success')
        elif ptype == 'capacity':
            conn.execute(
                \"\"\"INSERT INTO network_capacity
                   (posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, equipment_type, available_date,
                    capacity_kg, capacity_cbm, mode, rate_usd, rate_type, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)\"\"\",
                (request.form.get('posted_by',''),
                 company,
                 request.form.get('origin_city',''),
                 request.form.get('origin_country',''),
                 request.form.get('dest_city',''),
                 request.form.get('dest_country',''),
                 request.form.get('equipment_type',''),
                 request.form.get('available_date',''),
                 float(request.form.get('capacity_kg') or 0),
                 float(request.form.get('capacity_cbm') or 0),
                 request.form.get('mode','road'),
                 float(request.form.get('rate_usd') or 0),
                 request.form.get('rate_type','negotiable'),
                 request.form.get('notes','')))
            flash('Capacity posted to Flash Network.', 'success')
        conn.commit()
        conn.close()
        return redirect(url_for('tms.flash_network'))

    origin = request.args.get('origin','')
    dest   = request.args.get('dest','')
    mode   = request.args.get('mode','')
    lq = "SELECT * FROM network_loads WHERE status='open'"
    cq = "SELECT * FROM network_capacity WHERE status='available'"
    for val, cols in [(origin, 'origin_city,origin_country'), (dest, 'dest_city,dest_country')]:
        if val:
            c1, c2 = cols.split(',')
            clause = f" AND ({c1} LIKE '%{val}%' OR {c2} LIKE '%{val}%')"
            lq += clause; cq += clause
    if mode:
        lq += f" AND mode='{mode}'"; cq += f" AND mode='{mode}'"
    loads    = conn.execute(lq + " ORDER BY created_at DESC LIMIT 50").fetchall()
    capacity = conn.execute(cq + " ORDER BY created_at DESC LIMIT 50").fetchall()
    stats = {
        'total_loads':    conn.execute("SELECT COUNT(*) FROM network_loads WHERE status='open'").fetchone()[0],
        'total_capacity': conn.execute("SELECT COUNT(*) FROM network_capacity WHERE status='available'").fetchone()[0],
        'countries':      conn.execute("SELECT COUNT(DISTINCT origin_country) FROM network_loads WHERE origin_country!=''").fetchone()[0],
    }
    conn.close()
    return render_template('tms/network.html',
        loads=loads, capacity=capacity, stats=stats,
        filter_origin=origin, filter_dest=dest, filter_mode=mode)


@tms.route('/network/close', methods=['POST'])
def network_close_post():
    ptype   = request.form.get('post_type', 'load')
    post_id = request.form.get('post_id')
    conn = get_db()
    if ptype == 'load':
        conn.execute("UPDATE network_loads SET status='closed' WHERE id=?", (post_id,))
    else:
        conn.execute("UPDATE network_capacity SET status='closed' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash('Post closed.', 'info')
    return redirect(url_for('tms.flash_network'))
"""

with open(path, 'a', encoding='utf-8') as f:
    f.write(new_routes)
print('Routes appended')
