"""
GFLN Demo Seed Script — Georgian Freight Lines Inc, Mississauga ON
Seeds realistic demo data using correct TMS Master schema.
"""
import sys, os, random
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
os.environ["TMS_MASTER_DB_PATH"] = os.path.join(os.path.dirname(__file__), "data", "gfln_demo.db")

from tms.tms_db import get_db, init_tms_db

def seed():
    print("Initializing GFLN demo database...")
    init_tms_db()
    conn = get_db()
    today = date.today()

    # ── Branding ──────────────────────────────────────────────────────────────
    conn.execute("""CREATE TABLE IF NOT EXISTS tenant_branding (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        setting_key TEXT NOT NULL,
        setting_value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tenant_id, setting_key))""")
    for k, v in {
        "brand_name":        "Georgian Freight Lines",
        "brand_color":       "#c8a96e",
        "brand_color_dark":  "#0a0c0f",
        "email_from_name":   "Georgian Freight Lines",
        "support_email":     "dispatch@gfln.ca",
        "support_phone":     "905-297-9272",
        "footer_text":       "Georgian Freight Lines Inc — Mississauga, ON",
        "hide_powered_by":   "0",
        "primary_font":      "Inter",
        "sidebar_style":     "dark",
    }.items():
        conn.execute("INSERT INTO tenant_branding (tenant_id,setting_key,setting_value) VALUES ('default',?,?) ON CONFLICT(tenant_id,setting_key) DO UPDATE SET setting_value=excluded.setting_value", (k, v))

    # ── TMS Settings ──────────────────────────────────────────────────────────
    for k, v in {
        "company_name":    "Georgian Freight Lines Inc",
        "company_address": "2411 Drew Road, Mississauga, ON L5S 1A1",
        "company_phone":   "905-297-9272",
        "company_email":   "dispatch@gfln.ca",
        "company_mc":      "MC-748291",
        "company_dot":     "DOT-3847162",
        "currency":        "CAD",
    }.items():
        conn.execute("INSERT OR REPLACE INTO tms_settings (key,value) VALUES (?,?)", (k, v))

    # ── Carriers ──────────────────────────────────────────────────────────────
    carriers = [
        ("Challenger Motor Freight", "CHMF", "CA-291847", "CA", "dispatch@challenger.ca",  "519-653-0101"),
        ("Bison Transport",          "BISN", "CA-384721", "CA", "ops@bisontransport.ca",   "204-633-8068"),
        ("Day & Ross",               "DAYR", "CA-471823", "CA", "freight@dayross.com",     "506-375-4380"),
        ("Mullen Group",             "MULL", "CA-583920", "CA", "logistics@mullen.ca",     "403-995-5200"),
        ("TFI International",        "TFII", "CA-629481", "CA", "dispatch@tfiintl.com",   "514-331-4200"),
        ("XTL Transport",            "XLTL", "CA-714839", "CA", "ops@xtl.com",            "905-875-3500"),
        ("Vitran Express",           "VITR", "CA-802947", "CA", "freight@vitran.ca",       "905-595-5000"),
    ]
    carrier_ids = []
    for c in carriers:
        try:
            r = conn.execute(
                "INSERT INTO tms_carriers (name,scac,dot_number,country,contact_email,contact_phone,active) VALUES (?,?,?,?,?,?,1)",
                c).lastrowid
            carrier_ids.append(r)
        except Exception:
            row = conn.execute("SELECT id FROM tms_carriers WHERE name=?", (c[0],)).fetchone()
            carrier_ids.append(row["id"] if row else 1)

    # ── Drivers ───────────────────────────────────────────────────────────────
    drivers = [
        ("Mike Kowalski",   "ON-CDL-482910", "647-882-1234", "CA", "Active"),
        ("Sarah Tremblay",  "ON-CDL-591827", "905-441-5678", "CA", "Active"),
        ("James Okafor",    "ON-CDL-603841", "416-773-9012", "CA", "Active"),
        ("Luis Fernandez",  "ON-CDL-714829", "905-334-3456", "CA", "Active"),
        ("David Chen",      "ON-CDL-825937", "647-990-7890", "CA", "Active"),
        ("Patricia Nguyen", "ON-CDL-930184", "905-221-1122", "CA", "Off Duty"),
    ]
    driver_ids = []
    for d in drivers:
        try:
            r = conn.execute(
                "INSERT INTO drivers (name,license_number,phone,country,status) VALUES (?,?,?,?,?)",
                d).lastrowid
            driver_ids.append(r)
        except Exception:
            row = conn.execute("SELECT id FROM drivers WHERE name=?", (d[0],)).fetchone()
            driver_ids.append(row["id"] if row else 1)

    # ── Vehicles ──────────────────────────────────────────────────────────────
    vehicles = [
        ("T-101", "Semi Truck",  40000, 80, "CA", "Active"),
        ("T-102", "Semi Truck",  40000, 80, "CA", "Active"),
        ("T-103", "Semi Truck",  40000, 80, "CA", "Active"),
        ("T-104", "Semi Truck",  40000, 80, "CA", "Active"),
        ("T-105", "Day Cab",     36000, 70, "CA", "Active"),
        ("V-201", "Cargo Van",    5000, 14, "CA", "Active"),
    ]
    vehicle_ids = []
    for v in vehicles:
        try:
            r = conn.execute(
                "INSERT INTO vehicles (truck_number,vehicle_type,capacity_weight,capacity_cbm,country,status) VALUES (?,?,?,?,?,?)",
                v).lastrowid
            vehicle_ids.append(r)
        except Exception:
            row = conn.execute("SELECT id FROM vehicles WHERE truck_number=?", (v[0],)).fetchone()
            vehicle_ids.append(row["id"] if row else 1)

    # ── Shipments ─────────────────────────────────────────────────────────────
    shipments = [
        ("GFL-2026-001", "Mississauga, ON", "Ottawa, ON",       "In Transit",  "FTL", 0, 2850.00, "Auto Parts",           18400, 0),
        ("GFL-2026-002", "Mississauga, ON", "Montréal, QC",     "In Transit",  "FTL", 4, 3200.00, "Retail Goods",         22100, 1),
        ("GFL-2026-003", "Mississauga, ON", "Toronto, ON",      "Delivered",   "LTL", 6,  890.00, "Medical Supplies",      4200, -2),
        ("GFL-2026-004", "Brampton, ON",    "Calgary, AB",      "Booked",      "FTL", 3, 6800.00, "Industrial Equipment",  28000, 5),
        ("GFL-2026-005", "Mississauga, ON", "Windsor, ON",      "In Transit",  "FTL", 5, 1650.00, "Food & Beverage",       19500, 0),
        ("GFL-2026-006", "Toronto, ON",     "Vancouver, BC",    "Booked",      "FTL", 2, 8200.00, "Construction Material", 26800, 7),
        ("GFL-2026-007", "Mississauga, ON", "Sudbury, ON",      "Delivered",   "FTL", 0, 1920.00, "Automotive Parts",      17200, -3),
        ("GFL-2026-008", "Hamilton, ON",    "Kingston, ON",     "In Transit",  "LTL", 1,  740.00, "Consumer Electronics",   3800, 0),
        ("GFL-2026-009", "Mississauga, ON", "Detroit, MI",      "In Transit",  "FTL", 4, 3400.00, "Machine Components",    21000, 2),
        ("GFL-2026-010", "Brampton, ON",    "Montréal, QC",     "Draft",       "FTL", 6, 3100.00, "General Freight",       20000, 4),
        ("GFL-2026-011", "Mississauga, ON", "Chicago, IL",      "Booked",      "FTL", 2, 4200.00, "Auto Parts",            19800, 3),
        ("GFL-2026-012", "Toronto, ON",     "Ottawa, ON",       "Delivered",   "LTL", 5, 1100.00, "Office Supplies",        5500, -5),
    ]
    for i, s in enumerate(shipments):
        ref, origin, dest, status, mode, c_idx, rate, cargo, weight, eta_off = s
        eta = (today + timedelta(days=eta_off)).isoformat()
        etd = (today - timedelta(days=2)).isoformat()
        cname = carriers[c_idx][0] if c_idx < len(carriers) else ""
        cid   = carrier_ids[c_idx] if c_idx < len(carrier_ids) else None
        try:
            conn.execute("""INSERT INTO shipments
                (shipment_ref,status,customer_name,carrier_name,carrier_id,
                 origin_port,destination_port,eta,etd,cargo_description,
                 weight_kg,freight_rate,currency,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (ref, status, "Georgian Freight Lines", cname, cid,
                 origin, dest, eta, etd, cargo, weight, rate, "CAD"))
        except Exception:
            pass

    # ── Carrier Invoices ──────────────────────────────────────────────────────
    inv_data = [
        ("GFL-2026-003", "Vitran Express",           "INV-C-1001",  890.00, "Approved"),
        ("GFL-2026-007", "Challenger Motor Freight", "INV-C-1002", 1920.00, "Approved"),
        ("GFL-2026-012", "XTL Transport",            "INV-C-1003", 1100.00, "Approved"),
        ("GFL-2026-001", "Challenger Motor Freight", "INV-C-1004", 2850.00, "Pending"),
        ("GFL-2026-002", "TFI International",        "INV-C-1005", 3200.00, "Pending"),
        ("GFL-2026-005", "XTL Transport",            "INV-C-1006", 1650.00, "Pending"),
        ("GFL-2026-008", "Bison Transport",          "INV-C-1007",  740.00, "Pending"),
    ]
    for d in inv_data:
        try:
            conn.execute(
                "INSERT INTO carrier_invoices (shipment_ref,carrier_name,invoice_no,amount,currency,status) VALUES (?,?,?,?,'CAD',?)",
                d)
        except Exception:
            pass

    # ── Customer Invoices ─────────────────────────────────────────────────────
    cust_inv = [
        ("GFL-2026-003", "Georgian Freight Lines",  1068.00, "Paid",    (today - timedelta(days=7)).isoformat()),
        ("GFL-2026-007", "Georgian Freight Lines",  2304.00, "Paid",    (today - timedelta(days=3)).isoformat()),
        ("GFL-2026-012", "Georgian Freight Lines",  1320.00, "Paid",    (today - timedelta(days=1)).isoformat()),
        ("GFL-2026-001", "Georgian Freight Lines",  3420.00, "Sent",    (today + timedelta(days=15)).isoformat()),
        ("GFL-2026-002", "Georgian Freight Lines",  3840.00, "Sent",    (today + timedelta(days=15)).isoformat()),
        ("GFL-2026-004", "Georgian Freight Lines",  8160.00, "Draft",   (today + timedelta(days=30)).isoformat()),
        ("GFL-2026-006", "Georgian Freight Lines",  9840.00, "Draft",   (today + timedelta(days=30)).isoformat()),
    ]
    for d in cust_inv:
        try:
            conn.execute(
                "INSERT INTO customer_invoices (shipment_ref,customer_name,amount,currency,status,due_date) VALUES (?,?,?,'CAD',?,?)",
                d)
        except Exception:
            pass

    # ── Lanes ─────────────────────────────────────────────────────────────────
    lanes = [
        ("MSS-OTT", "Mississauga, ON", "Ottawa, ON",       "FTL", 5,  8),
        ("MSS-MTL", "Mississauga, ON", "Montréal, QC",     "FTL", 6, 12),
        ("MSS-TOR", "Mississauga, ON", "Toronto, ON",      "LTL", 1, 20),
        ("MSS-CGY", "Mississauga, ON", "Calgary, AB",      "FTL", 3,  2),
        ("MSS-VAN", "Mississauga, ON", "Vancouver, BC",    "FTL", 4,  2),
        ("MSS-WIN", "Mississauga, ON", "Windsor, ON",      "FTL", 2,  6),
        ("MSS-DET", "Mississauga, ON", "Detroit, MI",      "FTL", 2,  4),
        ("MSS-CHI", "Mississauga, ON", "Chicago, IL",      "FTL", 3,  3),
        ("BRP-KGS", "Brampton, ON",    "Kingston, ON",     "LTL", 2,  5),
        ("TOR-SDB", "Toronto, ON",     "Sudbury, ON",      "FTL", 4,  3),
    ]
    for l in lanes:
        try:
            conn.execute(
                "INSERT INTO tms_lanes (lane_code,origin_name,destination_name,mode,avg_transit_days,weekly_shipments,active) VALUES (?,?,?,?,?,?,1)",
                l)
        except Exception:
            pass

    # ── GPS Pings ─────────────────────────────────────────────────────────────
    gps = [
        ("GFL-2026-001", 44.2312, -76.4917, 68.2),
        ("GFL-2026-002", 45.3878, -75.6968, 72.1),
        ("GFL-2026-005", 43.2557, -79.8711, 65.8),
        ("GFL-2026-008", 43.7315, -79.7624, 59.4),
        ("GFL-2026-009", 43.0562, -79.1032, 71.0),
    ]
    for g in gps:
        try:
            conn.execute(
                "INSERT INTO tracking_pings (shipment_ref,lat,lon,speed_mph,recorded_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (g[0], g[1], g[2], g[3]))
        except Exception:
            pass

    # ── Shipment Events ───────────────────────────────────────────────────────
    events = [
        ("GFL-2026-001", "Status Change",   "Departed Mississauga terminal 06:30",         "Mississauga, ON"),
        ("GFL-2026-001", "GPS Update",      "En route via Hwy 401 — Kingston, ON",          "Kingston, ON"),
        ("GFL-2026-002", "Status Change",   "Departed Mississauga terminal 07:15",         "Mississauga, ON"),
        ("GFL-2026-002", "GPS Update",      "Cleared Québec border — Ottawa, ON",          "Ottawa, ON"),
        ("GFL-2026-003", "Status Change",   "Delivered — POD signed by J. Smith",          "Toronto, ON"),
        ("GFL-2026-007", "Status Change",   "Delivered — POD signed by M. Patel",          "Sudbury, ON"),
        ("GFL-2026-009", "Customs",         "Crossed border — Windsor/Detroit port of entry","Windsor, ON"),
        ("GFL-2026-012", "Status Change",   "Delivered — POD signed by C. Williams",       "Ottawa, ON"),
    ]
    for e in events:
        row = conn.execute("SELECT id FROM shipments WHERE shipment_ref=?", (e[0],)).fetchone()
        if row:
            try:
                conn.execute(
                    "INSERT INTO shipment_events (shipment_id,event_type,description,location) VALUES (?,?,?,?)",
                    (row["id"], e[1], e[2], e[3]))
            except Exception:
                pass

    conn.commit()
    print("[OK] GFLN demo database seeded")
    print(f"  Carriers:  {len(carriers)}")
    print(f"  Drivers:   {len(drivers)}")
    print(f"  Vehicles:  {len(vehicles)}")
    print(f"  Shipments: {len(shipments)}")
    print(f"  Invoices:  {len(inv_data) + len(cust_inv)}")
    print(f"  Lanes:     {len(lanes)}")
    print()
    print("Demo credentials:  demo / gfln2024")
    print("Start command:     see run_demo.bat")

if __name__ == "__main__":
    seed()
