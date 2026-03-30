import sqlite3

from .tenanting import DEFAULT_TENANT_ID, get_current_tenant
from .tms_db import get_db


SAMPLE_CARRIERS = [
    {
        "company_name": "Atlas Lane Logistics",
        "mc_number": "128044",
        "dot_number": "3748201",
        "equipment_types": "Dry Van, Reefer",
        "lanes_served": "IL->TX, WI->GA, IN->NC",
        "contact_name": "Maria Gomez",
        "contact_email": "capacity@atlaslanefreight.com",
        "contact_phone": "(312) 555-0141",
        "verified": 1,
        "listed_at": "2026-03-18 08:15:00",
    },
    {
        "company_name": "Granite State Hauling",
        "mc_number": "145882",
        "dot_number": "3987445",
        "equipment_types": "Flatbed, Step Deck",
        "lanes_served": "IL->OH, MI->PA, WI->IN",
        "contact_name": "Evan Price",
        "contact_email": "dispatch@granitestatehauling.com",
        "contact_phone": "(614) 555-0198",
        "verified": 1,
        "listed_at": "2026-03-17 10:20:00",
    },
    {
        "company_name": "Blue Mesa Transport",
        "mc_number": "152311",
        "dot_number": "4059284",
        "equipment_types": "Dry Van, Reefer",
        "lanes_served": "CA->AZ, CA->TX, NV->UT",
        "contact_name": "Sofia Ramirez",
        "contact_email": "sales@bluemesatransport.com",
        "contact_phone": "(602) 555-0114",
        "verified": 1,
        "listed_at": "2026-03-16 09:05:00",
    },
    {
        "company_name": "Ironline Capacity",
        "mc_number": "160409",
        "dot_number": "4128810",
        "equipment_types": "Dry Van, Power Only",
        "lanes_served": "TX->GA, OK->TN, LA->FL",
        "contact_name": "Marcus Reed",
        "contact_email": "ops@ironlinecapacity.com",
        "contact_phone": "(972) 555-0127",
        "verified": 0,
        "listed_at": "2026-03-15 11:40:00",
    },
    {
        "company_name": "Prairie Star Freight",
        "mc_number": "171225",
        "dot_number": "4201078",
        "equipment_types": "Dry Van, Box Truck",
        "lanes_served": "MN->IL, WI->MO, IA->NE",
        "contact_name": "Jenna Olson",
        "contact_email": "hello@prairiestarfreight.com",
        "contact_phone": "(651) 555-0180",
        "verified": 1,
        "listed_at": "2026-03-14 07:50:00",
    },
    {
        "company_name": "Summit Deck Carriers",
        "mc_number": "178904",
        "dot_number": "4274991",
        "equipment_types": "Flatbed, Conestoga",
        "lanes_served": "CO->TX, UT->AZ, WY->NE",
        "contact_name": "Caleb Dunn",
        "contact_email": "capacity@summitdeckcarriers.com",
        "contact_phone": "(303) 555-0135",
        "verified": 1,
        "listed_at": "2026-03-13 13:10:00",
    },
    {
        "company_name": "Harborlink Express",
        "mc_number": "183556",
        "dot_number": "4317722",
        "equipment_types": "Container Chassis, Dry Van",
        "lanes_served": "NJ->PA, NJ->VA, NY->MA",
        "contact_name": "Nicole Hart",
        "contact_email": "team@harborlinkexpress.com",
        "contact_phone": "(201) 555-0155",
        "verified": 1,
        "listed_at": "2026-03-12 16:45:00",
    },
    {
        "company_name": "Northern Reef Logistics",
        "mc_number": "191332",
        "dot_number": "4386409",
        "equipment_types": "Reefer, Box Truck",
        "lanes_served": "ON->MI, QC->NJ, NY->MA",
        "contact_name": "Aiden Clarke",
        "contact_email": "dispatch@northernreef.ca",
        "contact_phone": "(416) 555-0179",
        "verified": 0,
        "listed_at": "2026-03-11 12:25:00",
    },
    {
        "company_name": "Red Canyon Bulk",
        "mc_number": "204118",
        "dot_number": "4461284",
        "equipment_types": "Tanker, Hopper Bottom",
        "lanes_served": "TX->LA, KS->OK, NM->AZ",
        "contact_name": "Troy Henson",
        "contact_email": "rates@redcanyonbulk.com",
        "contact_phone": "(405) 555-0119",
        "verified": 1,
        "listed_at": "2026-03-10 14:30:00",
    },
    {
        "company_name": "Keystone Dedicated",
        "mc_number": "218650",
        "dot_number": "4527061",
        "equipment_types": "Dry Van, Power Only",
        "lanes_served": "OH->GA, PA->SC, IN->AL",
        "contact_name": "Hannah Cole",
        "contact_email": "support@keystonededicated.com",
        "contact_phone": "(412) 555-0162",
        "verified": 1,
        "listed_at": "2026-03-09 09:55:00",
    },
]

SAMPLE_REVIEWS = {
    "128044": [
        ("MKT-ATL-1001", 5, "Strong communication and no missed updates.", "2026-03-21 09:00:00"),
        ("MKT-ATL-1002", 4, "Handled a reefer reload cleanly and delivered on time.", "2026-03-24 13:10:00"),
    ],
    "145882": [
        ("MKT-GSH-1001", 5, "Flatbed securement was excellent and pickup was early.", "2026-03-20 11:35:00"),
        ("MKT-GSH-1002", 5, "Reliable on oversized deck work.", "2026-03-25 08:20:00"),
    ],
    "152311": [
        ("MKT-BMT-1001", 4, "Good west coast coverage with fast response times.", "2026-03-18 15:45:00"),
        ("MKT-BMT-1002", 4, "No surprises and clean paperwork.", "2026-03-22 10:00:00"),
    ],
    "160409": [
        ("MKT-ILC-1001", 4, "Solid Southeast lane coverage.", "2026-03-19 16:40:00"),
        ("MKT-ILC-1002", 3, "Needed more status updates after pickup.", "2026-03-23 07:50:00"),
    ],
    "171225": [
        ("MKT-PSF-1001", 5, "Box truck move was handled same-day.", "2026-03-17 12:05:00"),
        ("MKT-PSF-1002", 4, "Consistent Midwest coverage.", "2026-03-26 09:30:00"),
    ],
    "178904": [
        ("MKT-SDC-1001", 5, "Conestoga team handled weather delays well.", "2026-03-16 14:55:00"),
        ("MKT-SDC-1002", 4, "Professional dispatch and clean POD turnaround.", "2026-03-24 17:15:00"),
    ],
    "183556": [
        ("MKT-HLE-1001", 4, "Great dray + final-mile coordination.", "2026-03-15 10:30:00"),
        ("MKT-HLE-1002", 5, "Very responsive on East Coast port freight.", "2026-03-27 08:40:00"),
    ],
    "191332": [
        ("MKT-NRL-1001", 4, "Strong reefer service across the border.", "2026-03-13 13:35:00"),
        ("MKT-NRL-1002", 3, "Transit was fine but appointment updates were late.", "2026-03-21 18:05:00"),
    ],
    "204118": [
        ("MKT-RCB-1001", 5, "Bulk commodity lane was handled without issues.", "2026-03-14 08:15:00"),
        ("MKT-RCB-1002", 4, "Safe tanker operation and clean handoff.", "2026-03-25 12:50:00"),
    ],
    "218650": [
        ("MKT-KSD-1001", 5, "Dedicated capacity performed exactly as promised.", "2026-03-18 09:10:00"),
        ("MKT-KSD-1002", 5, "Fast acceptance and clear dispatcher follow-up.", "2026-03-26 16:20:00"),
    ],
}


def _current_tenant_ref():
    tenant_ref = (get_current_tenant() or DEFAULT_TENANT_ID).strip()
    return tenant_ref or DEFAULT_TENANT_ID


def _split_csv(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _serialize_carrier(row):
    if not row:
        return None
    carrier = dict(row)
    carrier["rating"] = round(float(carrier.get("rating") or 0), 2)
    carrier["review_count"] = int(carrier.get("review_count") or 0)
    carrier["verified"] = bool(carrier.get("verified"))
    carrier["equipment_list"] = _split_csv(carrier.get("equipment_types"))
    carrier["lane_list"] = _split_csv(carrier.get("lanes_served"))
    carrier["connection_status"] = carrier.get("connection_status") or ""
    return carrier


def _serialize_review(row):
    review = dict(row)
    review["rating"] = int(review.get("rating") or 0)
    review["review_text"] = (review.get("review_text") or "").strip()
    return review


def _refresh_carrier_rating(conn, carrier_id):
    totals = conn.execute(
        """
        SELECT ROUND(AVG(rating), 2) AS avg_rating, COUNT(*) AS review_count
        FROM marketplace_reviews
        WHERE carrier_id = ?
        """,
        (carrier_id,),
    ).fetchone()
    avg_rating = float((totals["avg_rating"] or 0) if totals else 0)
    review_count = int((totals["review_count"] or 0) if totals else 0)
    conn.execute(
        """
        UPDATE marketplace_carriers
        SET rating = ?, review_count = ?
        WHERE id = ?
        """,
        (avg_rating, review_count, carrier_id),
    )


def _seed_marketplace(conn):
    carrier_count = conn.execute("SELECT COUNT(*) AS count FROM marketplace_carriers").fetchone()["count"]
    if carrier_count:
        return

    conn.executemany(
        """
        INSERT INTO marketplace_carriers (
            company_name,
            mc_number,
            dot_number,
            equipment_types,
            lanes_served,
            contact_name,
            contact_email,
            contact_phone,
            rating,
            review_count,
            verified,
            listed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """,
        [
            (
                carrier["company_name"],
                carrier["mc_number"],
                carrier["dot_number"],
                carrier["equipment_types"],
                carrier["lanes_served"],
                carrier["contact_name"],
                carrier["contact_email"],
                carrier["contact_phone"],
                carrier["verified"],
                carrier["listed_at"],
            )
            for carrier in SAMPLE_CARRIERS
        ],
    )

    carrier_rows = conn.execute(
        "SELECT id, mc_number FROM marketplace_carriers"
    ).fetchall()
    carrier_ids = {row["mc_number"]: row["id"] for row in carrier_rows}

    review_rows = []
    for mc_number, reviews in SAMPLE_REVIEWS.items():
        carrier_id = carrier_ids.get(mc_number)
        if not carrier_id:
            continue
        for shipment_ref, rating, review_text, created_at in reviews:
            review_rows.append((carrier_id, shipment_ref, rating, review_text, created_at))

    if review_rows:
        conn.executemany(
            """
            INSERT INTO marketplace_reviews (
                carrier_id,
                shipment_ref,
                rating,
                review_text,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            review_rows,
        )

    for carrier_id in carrier_ids.values():
        _refresh_carrier_rating(conn, carrier_id)


def _ensure_marketplace_db():
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS marketplace_carriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                mc_number TEXT NOT NULL UNIQUE,
                dot_number TEXT DEFAULT '',
                equipment_types TEXT DEFAULT '',
                lanes_served TEXT DEFAULT '',
                contact_name TEXT DEFAULT '',
                contact_email TEXT DEFAULT '',
                contact_phone TEXT DEFAULT '',
                rating REAL NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS marketplace_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                carrier_id INTEGER NOT NULL,
                tenant_ref TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'connected', 'blocked')),
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (carrier_id, tenant_ref),
                FOREIGN KEY (carrier_id) REFERENCES marketplace_carriers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS marketplace_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                carrier_id INTEGER NOT NULL,
                shipment_ref TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                review_text TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (carrier_id) REFERENCES marketplace_carriers(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_marketplace_carriers_rating
                ON marketplace_carriers(verified, rating DESC, review_count DESC);
            CREATE INDEX IF NOT EXISTS idx_marketplace_connections_lookup
                ON marketplace_connections(carrier_id, tenant_ref);
            CREATE INDEX IF NOT EXISTS idx_marketplace_reviews_carrier
                ON marketplace_reviews(carrier_id, created_at DESC);
            """
        )
        _seed_marketplace(conn)
        conn.commit()
    finally:
        conn.close()


def _base_carrier_query():
    tenant_ref = _current_tenant_ref()
    query = """
        SELECT
            c.*,
            mc.status AS connection_status
        FROM marketplace_carriers c
        LEFT JOIN marketplace_connections mc
            ON mc.carrier_id = c.id
           AND mc.tenant_ref = ?
    """
    return tenant_ref, query


def search_carriers(equipment_type=None, origin_state=None, dest_state=None):
    _ensure_marketplace_db()
    equipment_type = (equipment_type or "").strip()
    origin_state = (origin_state or "").strip().upper()
    dest_state = (dest_state or "").strip().upper()

    tenant_ref, query = _base_carrier_query()
    clauses = []
    params = [tenant_ref]

    if equipment_type:
        clauses.append("UPPER(COALESCE(c.equipment_types, '')) LIKE ?")
        params.append(f"%{equipment_type.upper()}%")
    if origin_state and dest_state:
        clauses.append("UPPER(COALESCE(c.lanes_served, '')) LIKE ?")
        params.append(f"%{origin_state}->{dest_state}%")
    elif origin_state:
        clauses.append("UPPER(COALESCE(c.lanes_served, '')) LIKE ?")
        params.append(f"%{origin_state}->%")
    elif dest_state:
        clauses.append("UPPER(COALESCE(c.lanes_served, '')) LIKE ?")
        params.append(f"%->{dest_state}%")

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY COALESCE(c.rating, 0) DESC, COALESCE(c.review_count, 0) DESC, c.company_name ASC"

    conn = get_db()
    try:
        rows = conn.execute(query, params).fetchall()
        return [_serialize_carrier(row) for row in rows]
    finally:
        conn.close()


def get_carrier_profile(carrier_id):
    _ensure_marketplace_db()
    tenant_ref, query = _base_carrier_query()
    conn = get_db()
    try:
        carrier_row = conn.execute(
            query + " WHERE c.id = ?",
            (tenant_ref, carrier_id),
        ).fetchone()
        if not carrier_row:
            return None

        carrier = _serialize_carrier(carrier_row)
        reviews = [
            _serialize_review(row)
            for row in conn.execute(
                """
                SELECT id, carrier_id, shipment_ref, rating, review_text, created_at
                FROM marketplace_reviews
                WHERE carrier_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (carrier_id,),
            ).fetchall()
        ]

        breakdown_counts = {rating: 0 for rating in range(1, 6)}
        for review in reviews:
            breakdown_counts[review["rating"]] += 1
        total_reviews = len(reviews)
        rating_breakdown = []
        for rating in range(5, 0, -1):
            count = breakdown_counts[rating]
            percentage = round((count / total_reviews) * 100, 1) if total_reviews else 0
            rating_breakdown.append(
                {"rating": rating, "count": count, "percentage": percentage}
            )

        connection_status = carrier.get("connection_status") or ""
        return {
            "carrier": carrier,
            "reviews": reviews,
            "connection_status": connection_status,
            "rating_breakdown": rating_breakdown,
            "tenant_ref": tenant_ref,
        }
    finally:
        conn.close()


def request_connection(carrier_id):
    _ensure_marketplace_db()
    tenant_ref = _current_tenant_ref()
    conn = get_db()
    try:
        carrier = conn.execute(
            "SELECT id, company_name FROM marketplace_carriers WHERE id = ?",
            (carrier_id,),
        ).fetchone()
        if not carrier:
            raise ValueError("Carrier not found.")

        existing = conn.execute(
            """
            SELECT id, status
            FROM marketplace_connections
            WHERE carrier_id = ? AND tenant_ref = ?
            """,
            (carrier_id, tenant_ref),
        ).fetchone()

        if existing:
            if existing["status"] != "blocked":
                conn.execute(
                    """
                    UPDATE marketplace_connections
                    SET status = 'pending', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
            connection_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO marketplace_connections (
                    carrier_id,
                    tenant_ref,
                    status,
                    requested_at,
                    updated_at
                )
                VALUES (?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (carrier_id, tenant_ref),
            )
            connection_id = cursor.lastrowid

        conn.commit()
        connection = conn.execute(
            """
            SELECT id, carrier_id, tenant_ref, status, requested_at, updated_at
            FROM marketplace_connections
            WHERE id = ?
            """,
            (connection_id,),
        ).fetchone()
        return dict(connection)
    finally:
        conn.close()


def add_review(carrier_id, shipment_ref, rating, review_text):
    _ensure_marketplace_db()
    clean_shipment_ref = (shipment_ref or "").strip()
    clean_review_text = (review_text or "").strip()
    rating = int(rating)

    if not clean_shipment_ref:
        raise ValueError("Shipment reference is required.")
    if rating < 1 or rating > 5:
        raise ValueError("Rating must be between 1 and 5.")

    conn = get_db()
    try:
        carrier = conn.execute(
            "SELECT id FROM marketplace_carriers WHERE id = ?",
            (carrier_id,),
        ).fetchone()
        if not carrier:
            raise ValueError("Carrier not found.")

        conn.execute(
            """
            INSERT INTO marketplace_reviews (
                carrier_id,
                shipment_ref,
                rating,
                review_text,
                created_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (carrier_id, clean_shipment_ref, rating, clean_review_text),
        )
        _refresh_carrier_rating(conn, carrier_id)
        conn.commit()
        updated_carrier = conn.execute(
            "SELECT * FROM marketplace_carriers WHERE id = ?",
            (carrier_id,),
        ).fetchone()
        return _serialize_carrier(updated_carrier)
    finally:
        conn.close()


def get_featured_carriers():
    _ensure_marketplace_db()
    tenant_ref, query = _base_carrier_query()
    conn = get_db()
    try:
        rows = conn.execute(
            query
            + """
                WHERE c.verified = 1
                ORDER BY COALESCE(c.rating, 0) DESC, COALESCE(c.review_count, 0) DESC, c.company_name ASC
                LIMIT 6
            """,
            (tenant_ref,),
        ).fetchall()
        return [_serialize_carrier(row) for row in rows]
    finally:
        conn.close()


def get_marketplace_state_options():
    _ensure_marketplace_db()
    conn = get_db()
    try:
        rows = conn.execute("SELECT lanes_served FROM marketplace_carriers").fetchall()
        states = set()
        for row in rows:
            for lane in _split_csv(row["lanes_served"]):
                if "->" not in lane:
                    continue
                origin_state, dest_state = [part.strip().upper() for part in lane.split("->", 1)]
                if origin_state:
                    states.add(origin_state)
                if dest_state:
                    states.add(dest_state)
        return sorted(states)
    finally:
        conn.close()


def get_marketplace_equipment_options():
    _ensure_marketplace_db()
    conn = get_db()
    try:
        rows = conn.execute("SELECT equipment_types FROM marketplace_carriers").fetchall()
        equipment_types = set()
        for row in rows:
            for equipment_type in _split_csv(row["equipment_types"]):
                equipment_types.add(equipment_type)
        return sorted(equipment_types)
    finally:
        conn.close()


_ensure_marketplace_db()
