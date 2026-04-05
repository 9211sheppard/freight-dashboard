"""
Dangerous Goods / Hazmat Engine
Covers IMDG (ocean), IATA DGR (air), ADR (EU road), DOT 49 CFR (US road).
Client uses this to classify cargo, validate declarations, generate DG docs.
"""
from .tms_db import get_db

# UN Number seed data — top 100 most common in freight
UN_NUMBERS = [
    ("UN1203","Gasoline/Petrol","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1263","Paint / Paint related material","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1268","Petroleum distillates","3","Flammable liquid","III","PGIII","ADR/IMDG/IATA"),
    ("UN1270","Petroleum oil","3","Flammable liquid","III","PGIII","ADR/IMDG/IATA"),
    ("UN1950","Aerosols","2.1","Flammable gas","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1993","Flammable liquid NOS","3","Flammable liquid","I/II/III","Various","ADR/IMDG/IATA"),
    ("UN3077","Environmentally hazardous substance solid","9","Misc","III","PGIII","ADR/IMDG/IATA"),
    ("UN3082","Environmentally hazardous substance liquid","9","Misc","III","PGIII","ADR/IMDG/IATA"),
    ("UN3090","Lithium metal batteries","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN3480","Lithium ion batteries","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN3481","Lithium ion batteries in equipment","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN3091","Lithium metal batteries in equipment","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1075","Petroleum gases liquefied","2.1","Flammable gas","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1072","Oxygen compressed","2.2","Non-flammable gas","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1017","Chlorine","2.3","Toxic gas","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1789","Hydrochloric acid","8","Corrosive","II/III","PGII/III","ADR/IMDG/IATA"),
    ("UN1824","Sodium hydroxide solution","8","Corrosive","II","PGII","ADR/IMDG/IATA"),
    ("UN2794","Batteries wet filled with acid","8","Corrosive","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1090","Acetone","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1170","Ethanol","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1748","Calcium hypochlorite dry","5.1","Oxidizer","II","PGII","ADR/IMDG"),
    ("UN2915","Radioactive material","7","Radioactive","N/A","N/A","ADR/IMDG/IATA"),
    ("UN1219","Isopropanol","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1888","Chloroform","6.1","Toxic","III","PGIII","ADR/IMDG/IATA"),
    ("UN2794","Lead acid battery","8","Corrosive","N/A","N/A","ADR/IMDG"),
    ("UN1760","Corrosive liquid NOS","8","Corrosive","I/II/III","Various","ADR/IMDG/IATA"),
    ("UN1230","Methanol","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN2924","Flammable liquid corrosive NOS","3","Flammable liquid","I/II/III","Various","ADR/IMDG/IATA"),
    ("UN3175","Solids containing flammable liquid NOS","4.1","Flammable solid","II","PGII","ADR/IMDG"),
    ("UN1845","Carbon dioxide solid (dry ice)","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN2672","Ammonia solution","8","Corrosive","III","PGIII","ADR/IMDG/IATA"),
    ("UN1779","Formic acid","8","Corrosive","II","PGII","ADR/IMDG/IATA"),
    ("UN2031","Nitric acid","8","Corrosive","I/II","PGI/II","ADR/IMDG/IATA"),
    ("UN1830","Sulphuric acid","8","Corrosive","II","PGII","ADR/IMDG/IATA"),
    ("UN1307","Xylenes","3","Flammable liquid","II/III","PGII/III","ADR/IMDG/IATA"),
    ("UN1294","Toluene","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN1114","Benzene","3","Flammable liquid","II","PGII","ADR/IMDG/IATA"),
    ("UN3166","Vehicle fuel cell","9","Misc","N/A","N/A","ADR/IMDG/IATA"),
    ("UN3528","Engine fuel cell flammable liquid","3","Flammable liquid","N/A","N/A","ADR/IMDG/IATA"),
    ("UN2809","Mercury","8","Corrosive","III","PGIII","IMDG"),
]

# Restricted / prohibited per mode
RESTRICTED = {
    "IATA": ["UN2915","UN1017","UN2031"],  # examples — radioactive, chlorine, concentrated nitric
    "IMDG_BULK": [],
}

HAZMAT_CLASSES = {
    "1": "Explosives",
    "2.1": "Flammable Gas",
    "2.2": "Non-Flammable Gas",
    "2.3": "Toxic Gas",
    "3": "Flammable Liquid",
    "4.1": "Flammable Solid",
    "4.2": "Spontaneously Combustible",
    "4.3": "Dangerous When Wet",
    "5.1": "Oxidizer",
    "5.2": "Organic Peroxide",
    "6.1": "Toxic",
    "6.2": "Infectious",
    "7": "Radioactive",
    "8": "Corrosive",
    "9": "Miscellaneous",
}


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dg_un_numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            un_number TEXT UNIQUE NOT NULL,
            proper_shipping_name TEXT NOT NULL,
            hazmat_class TEXT NOT NULL,
            hazard_label TEXT,
            packing_group TEXT,
            packing_group_code TEXT,
            regulations TEXT,
            special_provisions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dg_declarations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            declaration_ref TEXT UNIQUE NOT NULL,
            shipment_ref TEXT NOT NULL,
            un_number TEXT NOT NULL,
            proper_shipping_name TEXT NOT NULL,
            hazmat_class TEXT NOT NULL,
            packing_group TEXT,
            quantity REAL,
            unit TEXT DEFAULT 'kg',
            net_explosive_mass REAL,
            transport_mode TEXT DEFAULT 'road',
            inner_packaging TEXT,
            outer_packaging TEXT,
            shipper_name TEXT,
            consignee_name TEXT,
            emergency_contact TEXT,
            emergency_phone TEXT,
            status TEXT DEFAULT 'draft',
            validated INTEGER DEFAULT 0,
            validation_notes TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _seed_un_numbers(conn):
    existing = conn.execute("SELECT COUNT(*) FROM dg_un_numbers").fetchone()[0]
    if existing > 0:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO dg_un_numbers (un_number,proper_shipping_name,hazmat_class,hazard_label,packing_group,packing_group_code,regulations) VALUES (?,?,?,?,?,?,?)",
        UN_NUMBERS
    )
    conn.commit()


def init_dg_db():
    conn = get_db()
    _init_tables(conn)
    _seed_un_numbers(conn)


def search_un(query):
    conn = get_db()
    _init_tables(conn)
    _seed_un_numbers(conn)
    q = f"%{query.upper()}%"
    rows = conn.execute(
        "SELECT * FROM dg_un_numbers WHERE un_number LIKE ? OR UPPER(proper_shipping_name) LIKE ? LIMIT 20",
        (q, q)
    ).fetchall()
    return [dict(r) for r in rows]


def get_un(un_number):
    conn = get_db()
    _init_tables(conn)
    _seed_un_numbers(conn)
    row = conn.execute("SELECT * FROM dg_un_numbers WHERE un_number=?", (un_number.upper(),)).fetchone()
    return dict(row) if row else None


def validate_declaration(declaration_id):
    conn = get_db()
    decl = conn.execute("SELECT * FROM dg_declarations WHERE id=?", (declaration_id,)).fetchone()
    if not decl:
        return {"valid": False, "notes": "Declaration not found"}

    notes = []
    valid = True

    un = get_un(decl['un_number'])
    if not un:
        notes.append(f"UN number {decl['un_number']} not found in database")
        valid = False

    if not decl['emergency_phone']:
        notes.append("Emergency contact phone required")
        valid = False

    if not decl['proper_shipping_name']:
        notes.append("Proper Shipping Name required")
        valid = False

    if not decl['quantity'] or decl['quantity'] <= 0:
        notes.append("Quantity must be greater than 0")
        valid = False

    if decl['transport_mode'] == 'air' and un and decl['un_number'] in RESTRICTED.get('IATA', []):
        notes.append(f"{decl['un_number']} is restricted/prohibited on IATA air transport")
        valid = False

    if un and un['hazmat_class'] == '7':
        notes.append("Radioactive material requires additional radiation level documentation")

    conn.execute(
        "UPDATE dg_declarations SET validated=?, validation_notes=? WHERE id=?",
        (int(valid), "; ".join(notes) if notes else "All checks passed", declaration_id)
    )
    conn.commit()
    return {"valid": valid, "notes": notes or ["All checks passed"]}


def create_declaration(shipment_ref, un_number, quantity, unit='kg',
                        transport_mode='road', inner_pkg='', outer_pkg='',
                        shipper='', consignee='', emergency_contact='',
                        emergency_phone='', created_by='dispatcher'):
    conn = get_db()
    _init_tables(conn)
    _seed_un_numbers(conn)
    import secrets
    ref = "DG-" + secrets.token_hex(4).upper()
    un = get_un(un_number) or {}
    conn.execute("""
        INSERT INTO dg_declarations
        (declaration_ref, shipment_ref, un_number, proper_shipping_name,
         hazmat_class, packing_group, quantity, unit, transport_mode,
         inner_packaging, outer_packaging, shipper_name, consignee_name,
         emergency_contact, emergency_phone, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (ref, shipment_ref, un_number.upper(),
          un.get('proper_shipping_name', ''), un.get('hazmat_class', ''),
          un.get('packing_group', ''), quantity, unit, transport_mode,
          inner_pkg, outer_pkg, shipper, consignee, emergency_contact, emergency_phone, created_by))
    conn.commit()
    return ref


def get_declarations(shipment_ref=None):
    conn = get_db()
    _init_tables(conn)
    if shipment_ref:
        rows = conn.execute(
            "SELECT * FROM dg_declarations WHERE shipment_ref=? ORDER BY created_at DESC",
            (shipment_ref,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM dg_declarations ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


def get_dg_dashboard():
    conn = get_db()
    _init_tables(conn)
    total = conn.execute("SELECT COUNT(*) FROM dg_declarations").fetchone()[0]
    draft = conn.execute("SELECT COUNT(*) FROM dg_declarations WHERE status='draft'").fetchone()[0]
    invalid = conn.execute("SELECT COUNT(*) FROM dg_declarations WHERE validated=0 AND status!='draft'").fetchone()[0]
    recent = conn.execute(
        "SELECT * FROM dg_declarations ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return {
        "total": total, "draft": draft, "invalid": invalid,
        "recent_declarations": [dict(r) for r in recent],
        "hazmat_classes": HAZMAT_CLASSES,
    }
