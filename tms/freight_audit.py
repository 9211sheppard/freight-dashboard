from .tms_db import get_db


DISCREPANCY_THRESHOLD = 5.0
KG_TO_LBS = 2.20462
AUDIT_STATUSES = ("pending", "approved", "disputed", "resolved")


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return bool(row)


def _table_columns(conn, table_name):
    if not _table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS freight_audit_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            shipment_ref TEXT NOT NULL,
            billed_amount REAL NOT NULL DEFAULT 0,
            expected_amount REAL NOT NULL DEFAULT 0,
            discrepancy REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tenant_id TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_freight_audit_items_invoice_id ON freight_audit_items(invoice_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_freight_audit_items_status ON freight_audit_items(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_freight_audit_items_shipment_ref ON freight_audit_items(shipment_ref)"
    )


def _shipment_weight_lbs(row):
    weight_lbs = row.get("weight_lbs")
    if weight_lbs not in (None, ""):
        try:
            return round(float(weight_lbs), 2)
        except (TypeError, ValueError):
            return 0.0

    weight_kg = row.get("weight_kg")
    if weight_kg in (None, ""):
        return 0.0
    try:
        return round(float(weight_kg) * KG_TO_LBS, 2)
    except (TypeError, ValueError):
        return 0.0


def _invoice_source(conn):
    invoice_columns = _table_columns(conn, "invoices")
    if {"id", "shipment_ref"} <= invoice_columns:
        billed_column = next(
            (column for column in ("billed_amount", "amount", "total_amount") if column in invoice_columns),
            None,
        )
        if billed_column:
            number_column = next(
                (column for column in ("invoice_no", "invoice_number", "number") if column in invoice_columns),
                None,
            )
            return {
                "table": "invoices",
                "alias": "i",
                "shipment_column": "shipment_ref",
                "billed_column": billed_column,
                "number_column": number_column,
            }

    carrier_columns = _table_columns(conn, "carrier_invoices")
    if {"id", "shipment_ref", "amount"} <= carrier_columns:
        return {
            "table": "carrier_invoices",
            "alias": "ci",
            "shipment_column": "shipment_ref",
            "billed_column": "amount",
            "number_column": "invoice_no" if "invoice_no" in carrier_columns else None,
        }
    return None


def _invoice_rows(conn):
    source = _invoice_source(conn)
    if not source:
        return []

    invoice_number_expr = (
        f"{source['alias']}.{source['number_column']}" if source["number_column"] else "NULL"
    )
    shipment_columns = _table_columns(conn, "shipments")
    weight_expr = "s.weight_lbs" if "weight_lbs" in shipment_columns else "NULL"
    query = f"""
        SELECT
            {source['alias']}.id AS invoice_id,
            {invoice_number_expr} AS invoice_no,
            {source['alias']}.{source['shipment_column']} AS shipment_ref,
            {source['alias']}.{source['billed_column']} AS billed_amount,
            s.customer_name,
            s.carrier_name,
            s.origin_port,
            s.destination_port,
            s.mode,
            s.lane_code,
            s.freight_rate,
            s.weight_kg,
            {weight_expr} AS weight_lbs
        FROM {source['table']} {source['alias']}
        LEFT JOIN shipments s ON s.shipment_ref = {source['alias']}.{source['shipment_column']}
        ORDER BY {source['alias']}.id DESC
    """
    return [dict(row) for row in conn.execute(query).fetchall()]


def _rate_query_for_reference(rate_columns):
    if "shipment_ref" in rate_columns:
        return ("shipment_ref = ?", lambda shipment: (shipment.get("shipment_ref"),))
    if "lane_code" in rate_columns:
        return ("lane_code = ?", lambda shipment: (shipment.get("lane_code"),))
    if {"origin_port", "destination_port", "mode"} <= rate_columns:
        return (
            "origin_port = ? AND destination_port = ? AND (mode = ? OR mode IS NULL OR mode = '')",
            lambda shipment: (
                shipment.get("origin_port"),
                shipment.get("destination_port"),
                shipment.get("mode"),
                shipment.get("mode"),
            ),
        )
    if {"origin", "destination", "mode"} <= rate_columns:
        return (
            "origin = ? AND destination = ? AND (mode = ? OR mode IS NULL OR mode = '')",
            lambda shipment: (
                shipment.get("origin_port"),
                shipment.get("destination_port"),
                shipment.get("mode"),
                shipment.get("mode"),
            ),
        )
    return (None, None)


def _expected_from_tms_rates(conn, shipment, weight_lbs):
    rate_columns = _table_columns(conn, "tms_rates")
    if not rate_columns:
        return None

    where_sql, params_builder = _rate_query_for_reference(rate_columns)
    if not where_sql or not params_builder:
        return None

    params = params_builder(shipment)
    if any(value in (None, "") for value in params[: min(3, len(params))]):
        return None

    range_clauses = []
    if "min_weight" in rate_columns:
        range_clauses.append("(min_weight IS NULL OR min_weight <= ?)")
        params = (*params, weight_lbs)
    if "max_weight" in rate_columns:
        range_clauses.append("(max_weight IS NULL OR max_weight >= ?)")
        params = (*params, weight_lbs)

    where_parts = [where_sql] + range_clauses
    order_parts = []
    if "updated_at" in rate_columns:
        order_parts.append("updated_at DESC")
    if "id" in rate_columns:
        order_parts.append("id DESC")
    order_sql = ", ".join(order_parts) if order_parts else "ROWID DESC"
    query = f"SELECT * FROM tms_rates WHERE {' AND '.join(where_parts)} ORDER BY {order_sql} LIMIT 1"
    rate_row = conn.execute(query, params).fetchone()
    if not rate_row:
        return None

    rate_row = dict(rate_row)
    min_charge = float(rate_row.get("min_charge") or 0)
    rate_flat = float(rate_row.get("rate_flat") or 0)

    if rate_row.get("expected_amount") not in (None, ""):
        return round(float(rate_row["expected_amount"]), 2)
    if rate_row.get("rate_per_cwt") not in (None, ""):
        calculated = rate_flat + (float(rate_row["rate_per_cwt"]) * (weight_lbs / 100.0))
        return round(max(min_charge, calculated), 2)
    if rate_row.get("rate_per_lb") not in (None, ""):
        calculated = rate_flat + (float(rate_row["rate_per_lb"]) * weight_lbs)
        return round(max(min_charge, calculated), 2)
    if rate_row.get("rate") not in (None, ""):
        calculated = rate_flat + (float(rate_row["rate"]) * weight_lbs)
        return round(max(min_charge, calculated), 2)
    if rate_flat:
        return round(max(min_charge, rate_flat), 2)
    return None


def _expected_amount(conn, shipment):
    weight_lbs = _shipment_weight_lbs(shipment)
    if weight_lbs <= 0:
        return None

    tms_rate_amount = _expected_from_tms_rates(conn, shipment, weight_lbs)
    if tms_rate_amount is not None:
        return tms_rate_amount

    freight_rate = shipment.get("freight_rate")
    if freight_rate not in (None, ""):
        return round(float(freight_rate), 2)
    return None


def run_audit():
    conn = get_db()
    try:
        _ensure_table(conn)
        created = 0
        updated = 0
        resolved = 0
        skipped = 0

        for row in _invoice_rows(conn):
            if not row.get("shipment_ref"):
                skipped += 1
                continue

            billed_amount = row.get("billed_amount")
            if billed_amount in (None, ""):
                skipped += 1
                continue

            expected_amount = _expected_amount(conn, row)
            if expected_amount is None:
                skipped += 1
                continue

            billed_amount = round(float(billed_amount), 2)
            discrepancy = round(billed_amount - expected_amount, 2)
            existing = conn.execute(
                "SELECT * FROM freight_audit_items WHERE invoice_id = ?",
                (row["invoice_id"],),
            ).fetchone()

            if abs(discrepancy) > DISCREPANCY_THRESHOLD:
                if existing:
                    status = existing["status"] if existing["status"] in AUDIT_STATUSES else "pending"
                    conn.execute(
                        """
                        UPDATE freight_audit_items
                        SET shipment_ref = ?,
                            billed_amount = ?,
                            expected_amount = ?,
                            discrepancy = ?,
                            status = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE invoice_id = ?
                        """,
                        (
                            row["shipment_ref"],
                            billed_amount,
                            expected_amount,
                            discrepancy,
                            status,
                            row["invoice_id"],
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO freight_audit_items
                            (invoice_id, shipment_ref, billed_amount, expected_amount, discrepancy, status, notes)
                        VALUES (?, ?, ?, ?, ?, 'pending', '')
                        """,
                        (
                            row["invoice_id"],
                            row["shipment_ref"],
                            billed_amount,
                            expected_amount,
                            discrepancy,
                        ),
                    )
                    created += 1
                continue

            if existing:
                next_status = existing["status"]
                if next_status in {"pending", "disputed"}:
                    next_status = "resolved"
                    resolved += 1
                conn.execute(
                    """
                    UPDATE freight_audit_items
                    SET shipment_ref = ?,
                        billed_amount = ?,
                        expected_amount = ?,
                        discrepancy = ?,
                        status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE invoice_id = ?
                    """,
                    (
                        row["shipment_ref"],
                        billed_amount,
                        expected_amount,
                        discrepancy,
                        next_status,
                        row["invoice_id"],
                    ),
                )
                updated += 1

        conn.commit()
        return {
            "created": created,
            "updated": updated,
            "resolved": resolved,
            "skipped": skipped,
        }
    finally:
        conn.close()


def get_audit_queue():
    conn = get_db()
    try:
        _ensure_table(conn)
        source = _invoice_source(conn)
        if not source:
            return []

        invoice_number_expr = (
            f"{source['alias']}.{source['number_column']}" if source["number_column"] else "NULL"
        )
        billed_expr = f"{source['alias']}.{source['billed_column']}"
        query = f"""
            SELECT
                ai.*,
                {invoice_number_expr} AS invoice_no,
                {billed_expr} AS current_billed_amount,
                s.customer_name,
                s.carrier_name,
                s.origin_port,
                s.destination_port,
                s.mode,
                s.weight_kg
            FROM freight_audit_items ai
            LEFT JOIN {source['table']} {source['alias']} ON {source['alias']}.id = ai.invoice_id
            LEFT JOIN shipments s ON s.shipment_ref = ai.shipment_ref
            WHERE ai.status = 'pending'
            ORDER BY ABS(ai.discrepancy) DESC, ai.created_at DESC
        """
        rows = [dict(row) for row in conn.execute(query).fetchall()]
        for row in rows:
            row["weight_lbs"] = _shipment_weight_lbs(row)
        return rows
    finally:
        conn.close()


def approve_item(item_id):
    conn = get_db()
    try:
        _ensure_table(conn)
        cursor = conn.execute(
            """
            UPDATE freight_audit_items
            SET status = 'approved',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def dispute_item(item_id, notes):
    conn = get_db()
    try:
        _ensure_table(conn)
        cursor = conn.execute(
            """
            UPDATE freight_audit_items
            SET status = 'disputed',
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ((notes or "").strip(), item_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_audit_summary():
    conn = get_db()
    try:
        _ensure_table(conn)
        summary = {status: 0 for status in AUDIT_STATUSES}
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS item_count, COALESCE(SUM(ABS(discrepancy)), 0) AS discrepancy_total
            FROM freight_audit_items
            GROUP BY status
            """
        ).fetchall()
        total_discrepancy = 0.0
        for row in rows:
            status = row["status"]
            if status in summary:
                summary[status] = int(row["item_count"] or 0)
                total_discrepancy += float(row["discrepancy_total"] or 0)
        summary["total_discrepancy"] = round(total_discrepancy, 2)
        return summary
    finally:
        conn.close()
