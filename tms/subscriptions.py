"""Subscription and billing management for SaaS monetization."""
import sqlite3, os, json
from datetime import datetime, timedelta

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_subscription_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscription_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_key TEXT NOT NULL UNIQUE,
            plan_name TEXT NOT NULL,
            price_monthly REAL NOT NULL,
            price_annual REAL DEFAULT 0,
            description TEXT DEFAULT '',
            features TEXT DEFAULT '[]',
            is_base INTEGER DEFAULT 0,
            is_addon INTEGER DEFAULT 0,
            category TEXT DEFAULT 'core',
            stripe_price_id TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tenant_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            plan_key TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trial_ends_at TIMESTAMP DEFAULT NULL,
            current_period_start TEXT DEFAULT '',
            current_period_end TEXT DEFAULT '',
            cancelled_at TIMESTAMP DEFAULT NULL,
            stripe_subscription_id TEXT DEFAULT '',
            UNIQUE(tenant_id, plan_key)
        );

        CREATE TABLE IF NOT EXISTS saas_tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL UNIQUE,
            company_name TEXT NOT NULL,
            owner_email TEXT NOT NULL,
            owner_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            plan_tier TEXT DEFAULT 'base',
            status TEXT DEFAULT 'active',
            trial_ends_at TIMESTAMP DEFAULT NULL,
            stripe_customer_id TEXT DEFAULT '',
            user_count INTEGER DEFAULT 1,
            shipment_count INTEGER DEFAULT 0,
            storage_mb REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP DEFAULT NULL,
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS billing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'paid',
            description TEXT DEFAULT '',
            stripe_invoice_id TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        _seed_plans(conn)
    finally:
        conn.close()

def _seed_plans(conn):
    if conn.execute("SELECT COUNT(*) FROM subscription_plans").fetchone()[0] > 0:
        return

    plans = [
        # BASE PLAN
        ('base', 'Base', 9.99, 99.00, 'Core TMS — shipments, dispatch, drivers, fleet, documents, basic tracking',
         json.dumps(['Shipment Management', 'Dispatch Board', 'Drivers & Fleet', 'BOL / Invoice / POD', 'Customer Tracking Portal', 'Basic Analytics']),
         1, 0, 'core', '', 1, 0),

        # INTEGRATIONS
        ('dat', 'DAT Rate Intelligence', 4.99, 49.00, 'Live spot rates + lane history from DAT RateView',
         json.dumps(['Live spot rates', 'Lane history', 'Market benchmarking']), 0, 1, 'integration', '', 1, 10),
        ('project44', 'project44 Visibility', 6.99, 69.00, 'Real-time multimodal tracking via project44 network',
         json.dumps(['Live GPS tracking', 'ETA predictions', 'Exception alerts']), 0, 1, 'integration', '', 1, 11),
        ('fourkites', 'FourKites Visibility', 6.99, 69.00, 'Supply chain visibility platform',
         json.dumps(['Predictive ETAs', 'Live tracking', 'Customer notifications']), 0, 1, 'integration', '', 1, 12),
        ('maersk_api', 'Maersk API', 3.99, 39.00, 'Live ocean booking, tracking and schedule data from Maersk',
         json.dumps(['Ocean bookings', 'Container tracking', 'Schedule data']), 0, 1, 'integration', '', 1, 20),
        ('samsara', 'Samsara ELD', 4.99, 49.00, 'ELD + HOS data sync from Samsara fleet',
         json.dumps(['HOS sync', 'Live GPS', 'Driver behavior']), 0, 1, 'integration', '', 1, 30),
        ('motive', 'Motive ELD', 4.99, 49.00, 'ELD + HOS data sync from Motive (KeepTruckin)',
         json.dumps(['HOS sync', 'Live GPS', 'IFTA mileage']), 0, 1, 'integration', '', 1, 31),
        ('sap', 'SAP S/4HANA', 14.99, 149.00, 'Bidirectional sync with SAP S/4HANA ERP',
         json.dumps(['Order sync', 'Invoice sync', 'GL coding']), 0, 1, 'integration', '', 1, 40),
        ('netsuite', 'Oracle NetSuite', 14.99, 149.00, 'Bidirectional sync with Oracle NetSuite',
         json.dumps(['Order sync', 'Invoice posting', 'Customer sync']), 0, 1, 'integration', '', 1, 41),
        ('dynamics', 'Microsoft Dynamics 365', 12.99, 129.00, 'Bidirectional sync with Dynamics 365',
         json.dumps(['Order sync', 'Invoice sync', 'Contact sync']), 0, 1, 'integration', '', 1, 42),

        # INTELLIGENCE
        ('ai_matching', 'AI Load Matching', 2.99, 29.00, 'AI-powered driver/load assignment recommendations',
         json.dumps(['Smart matching', 'Score ranking', 'Auto-suggest']), 0, 1, 'intelligence', '', 1, 50),
        ('market_rates', 'Market Rate Benchmark', 2.99, 29.00, 'Compare your rates to live spot market',
         json.dumps(['Rate comparison', 'Lane trends', 'Overpay alerts']), 0, 1, 'intelligence', '', 1, 51),
        ('predictive_eta', 'Predictive ETA', 1.99, 19.00, 'AI-adjusted ETAs based on historical data',
         json.dumps(['ML-adjusted ETAs', 'Delay prediction', 'Customer alerts']), 0, 1, 'intelligence', '', 1, 52),

        # COMPLIANCE
        ('soc2', 'SOC 2 Compliance Pack', 4.99, 49.00, 'Audit log, security monitoring, GDPR/CCPA tools',
         json.dumps(['Full audit trail', 'Brute force protection', 'GDPR requests', 'Security dashboard']), 0, 1, 'compliance', '', 1, 60),
        ('customs', 'Customs & Compliance', 3.99, 39.00, 'HS codes, duty estimates, OFAC checks',
         json.dumps(['HS code lookup', 'Duty calculator', 'OFAC screening', 'Customs docs']), 0, 1, 'compliance', '', 1, 61),

        # OPERATIONS
        ('ltl_builder', 'LTL Load Builder', 2.99, 29.00, 'Build and consolidate LTL loads with FTL conversion',
         json.dumps(['LTL consolidation', 'Weight tracker', 'FTL conversion']), 0, 1, 'operations', '', 1, 70),
        ('route_planner', 'Multi-Stop Route Planner', 2.99, 29.00, 'Plan routes with up to 10 pickups + 10 drops',
         json.dumps(['Multi-stop routes', 'Drag reorder', 'Driver assignment']), 0, 1, 'operations', '', 1, 71),
        ('ifta', 'IFTA Reporting', 3.99, 39.00, 'Quarterly IFTA fuel tax reports for all 50 states + Canada',
         json.dumps(['Fuel purchase log', 'Mileage tracking', 'Quarterly reports', 'All 50 states + CA provinces']), 0, 1, 'operations', '', 1, 72),
        ('carrier_scorecard', 'Carrier Scorecard', 1.99, 19.00, 'Rank and track carrier performance per lane',
         json.dumps(['Performance scoring', 'Lane rankings', 'Damage tracking']), 0, 1, 'operations', '', 1, 73),
        ('auto_invoicing', 'Auto Invoicing', 2.99, 29.00, 'POD-triggered automatic invoice generation',
         json.dumps(['Auto-generate invoices', 'POD trigger', 'Email delivery']), 0, 1, 'operations', '', 1, 74),
        ('ocr', 'Document OCR', 2.99, 29.00, 'Scan any paper BOL and auto-fill shipment fields',
         json.dumps(['BOL scanning', 'Auto field extraction', 'PDF support']), 0, 1, 'operations', '', 1, 75),
    ]

    conn.executemany(
        """INSERT INTO subscription_plans
           (plan_key, plan_name, price_monthly, price_annual, description, features,
            is_base, is_addon, category, stripe_price_id, active, sort_order)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        plans
    )
    conn.commit()

init_subscription_tables()

import random, string

def generate_saas_tenant_id():
    return "TEN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def create_saas_tenant(company_name, owner_email, owner_name="", phone="", trial_days=14):
    conn = get_db()
    try:
        tid = generate_saas_tenant_id()
        trial_end = (datetime.now() + timedelta(days=trial_days)).isoformat()
        conn.execute(
            """INSERT INTO saas_tenants (tenant_id, company_name, owner_email, owner_name, phone, status, trial_ends_at)
               VALUES (?,?,?,?,?,'trialing',?)""",
            (tid, company_name, owner_email, owner_name, phone, trial_end)
        )
        conn.execute(
            "INSERT INTO tenant_subscriptions (tenant_id, plan_key, status, trial_ends_at) VALUES (?,?,?,?)",
            (tid, 'base', 'trialing', trial_end)
        )
        conn.commit()
        return tid
    finally:
        conn.close()

def get_tenant_addons(tenant_id):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT ts.*, sp.plan_name, sp.price_monthly, sp.description, sp.features, sp.category
               FROM tenant_subscriptions ts
               JOIN subscription_plans sp ON sp.plan_key = ts.plan_key
               WHERE ts.tenant_id=? AND ts.status='active'""",
            (tenant_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def tenant_has_addon(tenant_id, plan_key):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM tenant_subscriptions WHERE tenant_id=? AND plan_key=? AND status='active'",
            (tenant_id, plan_key)
        ).fetchone()
        return row is not None
    finally:
        conn.close()

def add_tenant_addon(tenant_id, plan_key):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO tenant_subscriptions (tenant_id, plan_key, status) VALUES (?,?,'active')",
            (tenant_id, plan_key)
        )
        conn.commit()
    finally:
        conn.close()

def remove_tenant_addon(tenant_id, plan_key):
    if plan_key == 'base':
        return False
    conn = get_db()
    try:
        conn.execute(
            "UPDATE tenant_subscriptions SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP WHERE tenant_id=? AND plan_key=?",
            (tenant_id, plan_key)
        )
        conn.commit()
        return True
    finally:
        conn.close()

def get_tenant_monthly_total(tenant_id):
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(sp.price_monthly), 0) as total
               FROM tenant_subscriptions ts
               JOIN subscription_plans sp ON sp.plan_key = ts.plan_key
               WHERE ts.tenant_id=? AND ts.status='active'""",
            (tenant_id,)
        ).fetchone()
        return round(row['total'], 2) if row else 0
    finally:
        conn.close()

def get_all_saas_tenants():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM saas_tenants ORDER BY created_at DESC").fetchall()
        tenants = []
        for r in rows:
            t = dict(r)
            t['monthly_revenue'] = get_tenant_monthly_total(t['tenant_id'])
            t['addon_count'] = conn.execute(
                "SELECT COUNT(*) FROM tenant_subscriptions WHERE tenant_id=? AND status='active' AND plan_key != 'base'",
                (t['tenant_id'],)
            ).fetchone()[0]
            tenants.append(t)
        return tenants
    finally:
        conn.close()

def get_all_plans():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM subscription_plans WHERE active=1 ORDER BY sort_order, category").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_platform_revenue_summary():
    conn = get_db()
    try:
        active = conn.execute("SELECT COUNT(*) FROM saas_tenants WHERE status='active'").fetchone()[0]
        trialing = conn.execute("SELECT COUNT(*) FROM saas_tenants WHERE status='trialing'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM saas_tenants").fetchone()[0]
        mrr = conn.execute(
            """SELECT COALESCE(SUM(sp.price_monthly), 0)
               FROM tenant_subscriptions ts
               JOIN subscription_plans sp ON sp.plan_key = ts.plan_key
               WHERE ts.status='active'"""
        ).fetchone()[0]
        arr = round((mrr or 0) * 12, 2)
        avg_revenue = round((mrr or 0) / active, 2) if active else 0
        top_addon = conn.execute(
            """SELECT sp.plan_name, COUNT(*) as cnt
               FROM tenant_subscriptions ts
               JOIN subscription_plans sp ON sp.plan_key = ts.plan_key
               WHERE ts.status='active' AND sp.is_addon=1
               GROUP BY ts.plan_key ORDER BY cnt DESC LIMIT 1"""
        ).fetchone()
        return {
            'active_tenants': active,
            'trialing_tenants': trialing,
            'total_tenants': total,
            'mrr': round(mrr or 0, 2),
            'arr': arr,
            'avg_revenue_per_tenant': avg_revenue,
            'top_addon': dict(top_addon) if top_addon else None,
        }
    finally:
        conn.close()

def suspend_saas_tenant(tenant_id):
    conn = get_db()
    try:
        conn.execute("UPDATE saas_tenants SET status='suspended' WHERE tenant_id=?", (tenant_id,))
        conn.commit()
    finally:
        conn.close()

def activate_saas_tenant(tenant_id):
    conn = get_db()
    try:
        conn.execute("UPDATE saas_tenants SET status='active' WHERE tenant_id=?", (tenant_id,))
        conn.commit()
    finally:
        conn.close()

def get_saas_tenant(tenant_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM saas_tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row:
            return None
        t = dict(row)
        t['subscriptions'] = get_tenant_addons(tenant_id)
        t['monthly_total'] = get_tenant_monthly_total(tenant_id)
        return t
    finally:
        conn.close()
