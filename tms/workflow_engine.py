"""
Workflow Automation Engine
No-code rule builder: IF [trigger] AND [conditions] THEN [actions]
Runs every 5 min via notifications scheduler.
"""
import json
from datetime import datetime
from .tms_db import get_db

TRIGGERS = {
    "shipment_status_changed": "Shipment status changes",
    "shipment_delayed":        "Shipment is past ETA",
    "new_shipment":            "New shipment created",
    "invoice_created":         "Invoice generated",
    "claim_opened":            "Freight claim opened",
    "pod_received":            "POD received",
    "carrier_late":            "Carrier late (>1 day past ETA)",
    "detention_started":       "Detention timer started",
    "driver_hos_violation":    "Driver HOS violation detected",
    "quote_request_received":  "Portal quote request received",
    "low_inventory":           "WMS inventory below threshold",
}

CONDITIONS = {
    "status_is":          {"label": "Status equals",          "field": "status",         "type": "select"},
    "origin_is":          {"label": "Origin contains",        "field": "origin_port",    "type": "text"},
    "destination_is":     {"label": "Destination contains",   "field": "destination_port","type": "text"},
    "carrier_is":         {"label": "Carrier name contains",  "field": "carrier_name",   "type": "text"},
    "value_gt":           {"label": "Freight rate greater than","field": "freight_rate", "type": "number"},
    "days_overdue_gt":    {"label": "Days past ETA greater than","field": "days_overdue","type": "number"},
    "always":             {"label": "Always (no condition)",  "field": None,             "type": "none"},
}

ACTIONS = {
    "send_email":          {"label": "Send email notification", "params": ["to_email", "subject", "body"]},
    "update_status":       {"label": "Update shipment status",  "params": ["new_status"]},
    "create_task":         {"label": "Create internal task",    "params": ["task_title", "assigned_to"]},
    "add_shipment_event":  {"label": "Add shipment timeline event", "params": ["event_description"]},
    "webhook":             {"label": "POST to webhook URL",     "params": ["webhook_url"]},
    "flag_for_review":     {"label": "Flag shipment for review","params": []},
}


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            trigger TEXT NOT NULL,
            conditions_json TEXT DEFAULT '[]',
            actions_json TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            run_count INTEGER DEFAULT 0,
            last_run_at TIMESTAMP,
            created_by TEXT DEFAULT 'system',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL,
            trigger_ref TEXT,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actions_taken_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'success',
            error_message TEXT,
            FOREIGN KEY (rule_id) REFERENCES workflow_rules(id)
        )
    """)
    conn.commit()


def get_rules(active_only=False):
    conn = get_db()
    _init_tables(conn)
    q = "SELECT * FROM workflow_rules"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item['conditions'] = json.loads(item.get('conditions_json') or '[]')
            item['actions'] = json.loads(item.get('actions_json') or '[]')
        except Exception:
            item['conditions'] = []
            item['actions'] = []
        result.append(item)
    return result


def create_rule(name, trigger, conditions, actions, created_by='dispatcher'):
    conn = get_db()
    _init_tables(conn)
    conn.execute("""
        INSERT INTO workflow_rules (name, trigger, conditions_json, actions_json, created_by)
        VALUES (?,?,?,?,?)
    """, (name, trigger, json.dumps(conditions), json.dumps(actions), created_by))
    conn.commit()


def toggle_rule(rule_id, active):
    conn = get_db()
    conn.execute("UPDATE workflow_rules SET active=? WHERE id=?", (int(active), rule_id))
    conn.commit()


def delete_rule(rule_id):
    conn = get_db()
    conn.execute("DELETE FROM workflow_rules WHERE id=?", (rule_id,))
    conn.commit()


def _check_conditions(conditions, context):
    for cond in conditions:
        ctype = cond.get('type')
        value = cond.get('value', '')
        if ctype == 'always':
            continue
        field = CONDITIONS.get(ctype, {}).get('field')
        if not field:
            continue
        ctx_val = str(context.get(field, '')).lower()
        if ctype in ('status_is', 'origin_is', 'destination_is', 'carrier_is'):
            if value.lower() not in ctx_val:
                return False
        elif ctype in ('value_gt', 'days_overdue_gt'):
            try:
                if float(context.get(field, 0)) <= float(value):
                    return False
            except (ValueError, TypeError):
                return False
    return True


def _execute_action(action, context, conn):
    atype = action.get('type')
    params = action.get('params', {})
    taken = {"type": atype, "params": params, "result": "ok"}

    if atype == 'send_email':
        try:
            from .notifications import send_email
            send_email(
                params.get('to_email', ''),
                params.get('subject', 'TMS Alert'),
                params.get('body', '').format(**context)
            )
        except Exception as e:
            taken['result'] = f"email_error: {e}"

    elif atype == 'update_status':
        ref = context.get('shipment_ref')
        if ref:
            conn.execute("UPDATE shipments SET status=? WHERE shipment_ref=?",
                         (params.get('new_status', ''), ref))

    elif atype == 'add_shipment_event':
        ref = context.get('shipment_ref')
        if ref:
            ship = conn.execute("SELECT id FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()
            if ship:
                conn.execute("""
                    INSERT INTO shipment_events (shipment_id, event_type, description, created_by)
                    VALUES (?,?,?,?)
                """, (ship['id'], 'workflow', params.get('event_description', '').format(**context), 'workflow_engine'))

    elif atype == 'flag_for_review':
        ref = context.get('shipment_ref')
        if ref:
            conn.execute("UPDATE shipments SET notes=COALESCE(notes,'')||' [FLAGGED FOR REVIEW]' WHERE shipment_ref=?", (ref,))

    elif atype == 'webhook':
        try:
            import urllib.request
            data = json.dumps(context).encode()
            req = urllib.request.Request(params.get('webhook_url', ''), data=data,
                                          headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            taken['result'] = f"webhook_error: {e}"

    return taken


def fire_trigger(trigger_name, context):
    """
    Called when a trigger event occurs.
    context: dict with relevant fields (shipment_ref, status, carrier_name, etc.)
    """
    conn = get_db()
    _init_tables(conn)
    rules = conn.execute(
        "SELECT * FROM workflow_rules WHERE trigger=? AND active=1",
        (trigger_name,)
    ).fetchall()

    for rule in rules:
        try:
            conditions = json.loads(rule['conditions_json'] or '[]')
            actions = json.loads(rule['actions_json'] or '[]')
        except Exception:
            continue

        if not _check_conditions(conditions, context):
            continue

        actions_taken = []
        status = 'success'
        error = None
        try:
            for action in actions:
                taken = _execute_action(action, context, conn)
                actions_taken.append(taken)
            conn.commit()
        except Exception as e:
            status = 'error'
            error = str(e)

        conn.execute("""
            INSERT INTO workflow_runs (rule_id, trigger_ref, actions_taken_json, status, error_message)
            VALUES (?,?,?,?,?)
        """, (rule['id'], context.get('shipment_ref', ''), json.dumps(actions_taken), status, error))
        conn.execute(
            "UPDATE workflow_rules SET run_count=run_count+1, last_run_at=CURRENT_TIMESTAMP WHERE id=?",
            (rule['id'],)
        )
        conn.commit()


def run_scheduled_checks():
    """Called every 5 min by notification scheduler. Fires time-based triggers."""
    conn = get_db()
    _init_tables(conn)

    # Check delayed shipments
    delayed = conn.execute("""
        SELECT shipment_ref, carrier_name, origin_port, destination_port,
               freight_rate, status, eta,
               julianday('now') - julianday(eta) as days_overdue
        FROM shipments
        WHERE status NOT IN ('Delivered','Cancelled','Draft')
          AND eta IS NOT NULL AND eta < date('now')
    """).fetchall()

    for s in delayed:
        ctx = dict(s)
        ctx['days_overdue'] = round(ctx.get('days_overdue') or 0, 1)
        fire_trigger('shipment_delayed', ctx)
        if ctx['days_overdue'] > 1:
            fire_trigger('carrier_late', ctx)


def get_workflow_dashboard():
    conn = get_db()
    _init_tables(conn)
    rules = get_rules()
    total_runs = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
    recent_runs = conn.execute("""
        SELECT wr.*, wrl.name as rule_name
        FROM workflow_runs wr
        JOIN workflow_rules wrl ON wrl.id = wr.rule_id
        ORDER BY wr.triggered_at DESC LIMIT 20
    """).fetchall()
    errors = conn.execute(
        "SELECT COUNT(*) FROM workflow_runs WHERE status='error' AND triggered_at >= datetime('now','-24 hours')"
    ).fetchone()[0]
    return {
        "rules": rules,
        "total_runs": total_runs,
        "errors_24h": errors,
        "recent_runs": [dict(r) for r in recent_runs],
        "triggers": TRIGGERS,
        "conditions": CONDITIONS,
        "actions": ACTIONS,
    }
