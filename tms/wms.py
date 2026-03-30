from __future__ import annotations

import random
import string
from datetime import datetime

from .tms_db import get_db


RECEIPT_STATUSES = ("pending", "receiving", "complete")
PICK_STATUSES = ("pending", "picking", "complete", "cancelled")
PICK_LINE_STATUSES = ("pending", "picked", "short")
CYCLE_COUNT_STATUSES = ("pending", "counting", "complete")


def _normalize_text(value):
    return (value or "").strip()


def _generate_ref(prefix):
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choices(string.digits, k=4))
    return f"{prefix}-{stamp}-{suffix}"


def ensure_wms_tables(conn=None):
    owns_connection = conn is None
    conn = conn or get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wms_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_name TEXT,
                zone TEXT,
                aisle TEXT,
                bay TEXT,
                level TEXT,
                position TEXT,
                location_code TEXT UNIQUE,
                capacity_units INTEGER DEFAULT 100,
                current_units INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS wms_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE,
                name TEXT,
                description TEXT,
                unit_of_measure TEXT,
                weight_kg REAL,
                volume_cbm REAL,
                category TEXT,
                barcode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS wms_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_id INTEGER,
                sku TEXT,
                quantity REAL,
                lot_number TEXT,
                expiry_date DATE,
                shipment_ref TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (location_id) REFERENCES wms_locations(id)
            );

            CREATE TABLE IF NOT EXISTS wms_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_ref TEXT UNIQUE,
                shipment_ref TEXT,
                supplier_name TEXT,
                po_number TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'receiving', 'complete')),
                received_by TEXT,
                received_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS wms_receipt_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER,
                sku TEXT,
                expected_qty REAL,
                received_qty REAL DEFAULT 0,
                location_code TEXT,
                notes TEXT,
                FOREIGN KEY (receipt_id) REFERENCES wms_receipts(id)
            );

            CREATE TABLE IF NOT EXISTS wms_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pick_ref TEXT UNIQUE,
                shipment_ref TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'picking', 'complete', 'cancelled')),
                picked_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS wms_pick_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pick_id INTEGER,
                sku TEXT,
                location_code TEXT,
                quantity REAL,
                picked_qty REAL DEFAULT 0,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'picked', 'short')),
                FOREIGN KEY (pick_id) REFERENCES wms_picks(id)
            );

            CREATE TABLE IF NOT EXISTS wms_cycle_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                count_ref TEXT UNIQUE,
                location_code TEXT,
                counted_by TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'counting', 'complete')),
                discrepancy_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_wms_inventory_sku
            ON wms_inventory (sku);

            CREATE INDEX IF NOT EXISTS idx_wms_inventory_location
            ON wms_inventory (location_id);

            CREATE INDEX IF NOT EXISTS idx_wms_receipt_lines_receipt
            ON wms_receipt_lines (receipt_id);

            CREATE INDEX IF NOT EXISTS idx_wms_pick_lines_pick
            ON wms_pick_lines (pick_id);
            """
        )
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def _ensure_product(conn, sku):
    sku = _normalize_text(sku)
    if not sku:
        raise ValueError("SKU is required.")
    conn.execute(
        """
        INSERT OR IGNORE INTO wms_products
            (sku, name, description, unit_of_measure, category, barcode, created_at)
        VALUES (?, '', '', '', '', '', CURRENT_TIMESTAMP)
        """,
        (sku,),
    )


def _ensure_location(conn, location_code):
    location_code = _normalize_text(location_code)
    if not location_code:
        raise ValueError("Location code is required.")

    existing = conn.execute(
        "SELECT * FROM wms_locations WHERE location_code = ?",
        (location_code,),
    ).fetchone()
    if existing:
        return dict(existing)

    cur = conn.execute(
        """
        INSERT INTO wms_locations
            (warehouse_name, zone, aisle, bay, level, position, location_code)
        VALUES ('', '', '', '', '', '', ?)
        """,
        (location_code,),
    )
    return dict(
        conn.execute("SELECT * FROM wms_locations WHERE id = ?", (cur.lastrowid,)).fetchone()
    )


def _refresh_location_units(conn, location_id):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total_units
        FROM wms_inventory
        WHERE location_id = ? AND quantity > 0
        """,
        (location_id,),
    ).fetchone()
    total_units = max(float(row["total_units"] or 0), 0)
    conn.execute(
        "UPDATE wms_locations SET current_units = ? WHERE id = ?",
        (int(round(total_units)), location_id),
    )


def _inventory_available_at_location(conn, sku, location_code):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(i.quantity), 0) AS total_qty
        FROM wms_inventory i
        JOIN wms_locations l ON l.id = i.location_id
        WHERE i.sku = ? AND l.location_code = ? AND i.quantity > 0
        """,
        (_normalize_text(sku), _normalize_text(location_code)),
    ).fetchone()
    return float(row["total_qty"] or 0)


def _allocate_location_for_pick(conn, sku):
    row = conn.execute(
        """
        SELECT l.location_code, SUM(i.quantity) AS total_qty
        FROM wms_inventory i
        JOIN wms_locations l ON l.id = i.location_id
        WHERE i.sku = ? AND i.quantity > 0
        GROUP BY l.location_code
        ORDER BY total_qty DESC, l.location_code ASC
        LIMIT 1
        """,
        (_normalize_text(sku),),
    ).fetchone()
    return row["location_code"] if row else ""


def _refresh_receipt_status(conn, receipt_id):
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS line_count,
            COALESCE(SUM(CASE WHEN received_qty > 0 THEN 1 ELSE 0 END), 0) AS received_lines,
            COALESCE(SUM(CASE WHEN received_qty >= expected_qty THEN 1 ELSE 0 END), 0) AS complete_lines
        FROM wms_receipt_lines
        WHERE receipt_id = ?
        """,
        (receipt_id,),
    ).fetchone()

    line_count = int(row["line_count"] or 0)
    received_lines = int(row["received_lines"] or 0)
    complete_lines = int(row["complete_lines"] or 0)

    if line_count and complete_lines >= line_count:
        status = "complete"
        received_at_sql = "CURRENT_TIMESTAMP"
    elif received_lines > 0:
        status = "receiving"
        received_at_sql = "COALESCE(received_at, CURRENT_TIMESTAMP)"
    else:
        status = "pending"
        received_at_sql = "received_at"

    conn.execute(
        f"""
        UPDATE wms_receipts
        SET status = ?,
            received_at = {received_at_sql}
        WHERE id = ?
        """,
        (status, receipt_id),
    )
    return status


def _refresh_pick_status(conn, pick_id):
    header = conn.execute(
        "SELECT status FROM wms_picks WHERE id = ?",
        (pick_id,),
    ).fetchone()
    if not header:
        raise ValueError("Pick was not found.")
    if header["status"] == "cancelled":
        return "cancelled"

    row = conn.execute(
        """
        SELECT
            COUNT(*) AS line_count,
            COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_lines
        FROM wms_pick_lines
        WHERE pick_id = ?
        """,
        (pick_id,),
    ).fetchone()
    line_count = int(row["line_count"] or 0)
    pending_lines = int(row["pending_lines"] or 0)

    if line_count and pending_lines == 0:
        status = "complete"
        completed_at_sql = "CURRENT_TIMESTAMP"
    elif line_count and pending_lines < line_count:
        status = "picking"
        completed_at_sql = "completed_at"
    else:
        status = "pending"
        completed_at_sql = "completed_at"

    conn.execute(
        f"""
        UPDATE wms_picks
        SET status = ?,
            completed_at = {completed_at_sql}
        WHERE id = ?
        """,
        (status, pick_id),
    )
    return status


def list_inventory():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        rows = conn.execute(
            """
            SELECT
                i.id,
                i.sku,
                COALESCE(p.name, '') AS product_name,
                COALESCE(p.unit_of_measure, '') AS unit_of_measure,
                l.location_code,
                i.quantity,
                i.lot_number,
                i.expiry_date,
                i.shipment_ref,
                i.received_at,
                i.updated_at
            FROM wms_inventory i
            LEFT JOIN wms_products p ON p.sku = i.sku
            LEFT JOIN wms_locations l ON l.id = i.location_id
            WHERE i.quantity > 0
            ORDER BY i.sku ASC, l.location_code ASC, i.expiry_date ASC, i.received_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_receipts():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        rows = conn.execute(
            """
            SELECT
                r.*,
                COUNT(rl.id) AS line_count,
                COALESCE(SUM(rl.expected_qty), 0) AS expected_total,
                COALESCE(SUM(rl.received_qty), 0) AS received_total
            FROM wms_receipts r
            LEFT JOIN wms_receipt_lines rl ON rl.receipt_id = r.id
            GROUP BY r.id
            ORDER BY r.created_at DESC, r.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_receipt(receipt_id):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        header = conn.execute(
            """
            SELECT
                r.*,
                COUNT(rl.id) AS line_count,
                COALESCE(SUM(rl.expected_qty), 0) AS expected_total,
                COALESCE(SUM(rl.received_qty), 0) AS received_total
            FROM wms_receipts r
            LEFT JOIN wms_receipt_lines rl ON rl.receipt_id = r.id
            WHERE r.id = ?
            GROUP BY r.id
            """,
            (receipt_id,),
        ).fetchone()
        if not header:
            return None

        lines = conn.execute(
            """
            SELECT
                rl.*,
                MAX(rl.expected_qty - rl.received_qty, 0) AS remaining_qty
            FROM wms_receipt_lines rl
            WHERE rl.receipt_id = ?
            ORDER BY rl.id ASC
            """,
            (receipt_id,),
        ).fetchall()
        receipt = dict(header)
        receipt["lines"] = [dict(row) for row in lines]
        expected_total = float(receipt["expected_total"] or 0)
        received_total = float(receipt["received_total"] or 0)
        receipt["completion_pct"] = round((received_total / expected_total) * 100, 1) if expected_total else 0.0
        return receipt
    finally:
        conn.close()


def list_picks():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        rows = conn.execute(
            """
            SELECT
                p.*,
                COUNT(pl.id) AS line_count,
                COALESCE(SUM(pl.quantity), 0) AS requested_total,
                COALESCE(SUM(pl.picked_qty), 0) AS picked_total
            FROM wms_picks p
            LEFT JOIN wms_pick_lines pl ON pl.pick_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC, p.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_pick(pick_id):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        header = conn.execute(
            """
            SELECT
                p.*,
                COUNT(pl.id) AS line_count,
                COALESCE(SUM(pl.quantity), 0) AS requested_total,
                COALESCE(SUM(pl.picked_qty), 0) AS picked_total
            FROM wms_picks p
            LEFT JOIN wms_pick_lines pl ON pl.pick_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (pick_id,),
        ).fetchone()
        if not header:
            return None

        lines = conn.execute(
            """
            SELECT
                pl.*,
                MAX(pl.quantity - pl.picked_qty, 0) AS remaining_qty
            FROM wms_pick_lines pl
            WHERE pl.pick_id = ?
            ORDER BY pl.id ASC
            """,
            (pick_id,),
        ).fetchall()

        pick = dict(header)
        pick["lines"] = []
        requested_total = float(pick["requested_total"] or 0)
        picked_total = float(pick["picked_total"] or 0)
        pick["completion_pct"] = round((picked_total / requested_total) * 100, 1) if requested_total else 0.0

        for row in lines:
            item = dict(row)
            item["available_qty"] = _inventory_available_at_location(conn, item["sku"], item["location_code"])
            pick["lines"].append(item)
        return pick
    finally:
        conn.close()


def list_locations():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        rows = conn.execute(
            """
            SELECT
                l.*,
                COALESCE(inv.used_units, 0) AS used_units,
                COALESCE(inv.sku_count, 0) AS sku_count,
                CASE
                    WHEN COALESCE(l.capacity_units, 0) > 0 THEN ROUND((COALESCE(inv.used_units, 0) * 100.0) / l.capacity_units, 1)
                    ELSE 0
                END AS utilization_pct,
                COALESCE(NULLIF(l.zone, ''), 'Unassigned') AS zone_label
            FROM wms_locations l
            LEFT JOIN (
                SELECT
                    location_id,
                    SUM(quantity) AS used_units,
                    COUNT(DISTINCT sku) AS sku_count
                FROM wms_inventory
                WHERE quantity > 0
                GROUP BY location_id
            ) inv ON inv.location_id = l.id
            ORDER BY zone_label ASC, l.location_code ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_inventory_by_sku(sku):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        sku = _normalize_text(sku)
        rows = conn.execute(
            """
            SELECT
                i.sku,
                COALESCE(p.name, '') AS product_name,
                l.location_code,
                COALESCE(NULLIF(l.zone, ''), 'Unassigned') AS zone,
                SUM(i.quantity) AS quantity,
                COUNT(*) AS record_count,
                MIN(i.expiry_date) AS next_expiry
            FROM wms_inventory i
            LEFT JOIN wms_products p ON p.sku = i.sku
            LEFT JOIN wms_locations l ON l.id = i.location_id
            WHERE i.sku = ? AND i.quantity > 0
            GROUP BY i.sku, p.name, l.location_code, l.zone
            ORDER BY l.location_code ASC
            """,
            (sku,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_inventory_by_location(location_code):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        location_code = _normalize_text(location_code)
        rows = conn.execute(
            """
            SELECT
                l.location_code,
                i.sku,
                COALESCE(p.name, '') AS product_name,
                SUM(i.quantity) AS quantity,
                COUNT(*) AS record_count,
                MIN(i.expiry_date) AS next_expiry
            FROM wms_inventory i
            JOIN wms_locations l ON l.id = i.location_id
            LEFT JOIN wms_products p ON p.sku = i.sku
            WHERE l.location_code = ? AND i.quantity > 0
            GROUP BY l.location_code, i.sku, p.name
            ORDER BY i.sku ASC
            """,
            (location_code,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_receipt(shipment_ref, supplier, po_number, lines):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        clean_lines = []
        for line in lines or []:
            sku = _normalize_text(line.get("sku"))
            if not sku:
                continue
            expected_qty = float(line.get("expected_qty") or 0)
            if expected_qty <= 0:
                raise ValueError(f"Expected quantity must be greater than zero for {sku}.")
            clean_lines.append(
                {
                    "sku": sku,
                    "expected_qty": expected_qty,
                    "location_code": _normalize_text(line.get("location_code")),
                    "notes": _normalize_text(line.get("notes")),
                }
            )

        if not clean_lines:
            raise ValueError("At least one receipt line is required.")

        receipt_ref = _generate_ref("RCV")
        cur = conn.execute(
            """
            INSERT INTO wms_receipts
                (receipt_ref, shipment_ref, supplier_name, po_number, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
            """,
            (
                _normalize_text(receipt_ref),
                _normalize_text(shipment_ref),
                _normalize_text(supplier),
                _normalize_text(po_number),
            ),
        )
        receipt_id = cur.lastrowid

        for line in clean_lines:
            _ensure_product(conn, line["sku"])
            conn.execute(
                """
                INSERT INTO wms_receipt_lines
                    (receipt_id, sku, expected_qty, received_qty, location_code, notes)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (
                    receipt_id,
                    line["sku"],
                    line["expected_qty"],
                    line["location_code"],
                    line["notes"],
                ),
            )

        conn.commit()
        return {"id": receipt_id, "receipt_ref": receipt_ref}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def receive_line(receipt_line_id, qty, location_code):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        line = conn.execute(
            """
            SELECT rl.*, r.shipment_ref, r.id AS receipt_id
            FROM wms_receipt_lines rl
            JOIN wms_receipts r ON r.id = rl.receipt_id
            WHERE rl.id = ?
            """,
            (receipt_line_id,),
        ).fetchone()
        if not line:
            raise ValueError("Receipt line was not found.")

        qty = float(qty)
        if qty < 0:
            raise ValueError("Received quantity cannot be negative.")

        new_location_code = _normalize_text(location_code or line["location_code"])
        current_received_qty = float(line["received_qty"] or 0)
        if qty < current_received_qty:
            raise ValueError("Received quantity cannot be less than the quantity already recorded.")
        if qty > 0 and not new_location_code:
            raise ValueError("Location code is required when receiving inventory.")
        if current_received_qty > 0:
            original_location = _normalize_text(line["location_code"])
            if original_location and new_location_code and new_location_code != original_location:
                raise ValueError("Location code cannot be changed after inventory has already been received.")

        delta_qty = qty - current_received_qty
        location = None

        if delta_qty > 0:
            location = _ensure_location(conn, new_location_code)
            _ensure_product(conn, line["sku"])

            existing_inventory = conn.execute(
                """
                SELECT *
                FROM wms_inventory
                WHERE location_id = ?
                  AND sku = ?
                  AND COALESCE(lot_number, '') = ''
                  AND expiry_date IS NULL
                  AND COALESCE(shipment_ref, '') = COALESCE(?, '')
                LIMIT 1
                """,
                (location["id"], line["sku"], line["shipment_ref"]),
            ).fetchone()

            if existing_inventory:
                conn.execute(
                    """
                    UPDATE wms_inventory
                    SET quantity = quantity + ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (delta_qty, existing_inventory["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO wms_inventory
                        (location_id, sku, quantity, lot_number, expiry_date, shipment_ref, received_at, updated_at)
                    VALUES (?, ?, ?, NULL, NULL, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (location["id"], line["sku"], delta_qty, line["shipment_ref"]),
                )
            _refresh_location_units(conn, location["id"])

        conn.execute(
            """
            UPDATE wms_receipt_lines
            SET received_qty = ?,
                location_code = ?
            WHERE id = ?
            """,
            (qty, new_location_code, receipt_line_id),
        )

        status = _refresh_receipt_status(conn, line["receipt_id"])
        conn.commit()
        return {
            "receipt_id": line["receipt_id"],
            "receipt_line_id": receipt_line_id,
            "received_qty": qty,
            "location_code": new_location_code,
            "status": status,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_pick(shipment_ref, lines):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        clean_lines = []
        for line in lines or []:
            sku = _normalize_text(line.get("sku"))
            if not sku:
                continue
            quantity = float(line.get("quantity") or 0)
            if quantity <= 0:
                raise ValueError(f"Pick quantity must be greater than zero for {sku}.")

            location_code = _normalize_text(line.get("location_code"))
            if not location_code:
                location_code = _allocate_location_for_pick(conn, sku)

            clean_lines.append(
                {
                    "sku": sku,
                    "quantity": quantity,
                    "location_code": location_code,
                }
            )

        if not clean_lines:
            raise ValueError("At least one pick line is required.")

        pick_ref = _generate_ref("PICK")
        cur = conn.execute(
            """
            INSERT INTO wms_picks
                (pick_ref, shipment_ref, status, created_at)
            VALUES (?, ?, 'pending', CURRENT_TIMESTAMP)
            """,
            (_normalize_text(pick_ref), _normalize_text(shipment_ref)),
        )
        pick_id = cur.lastrowid

        for line in clean_lines:
            conn.execute(
                """
                INSERT INTO wms_pick_lines
                    (pick_id, sku, location_code, quantity, picked_qty, status)
                VALUES (?, ?, ?, ?, 0, 'pending')
                """,
                (pick_id, line["sku"], line["location_code"], line["quantity"]),
            )

        conn.commit()
        return {"id": pick_id, "pick_ref": pick_ref}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def pick_line(pick_line_id, picked_qty):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        line = conn.execute(
            """
            SELECT pl.*, p.id AS pick_id
            FROM wms_pick_lines pl
            JOIN wms_picks p ON p.id = pl.pick_id
            WHERE pl.id = ?
            """,
            (pick_line_id,),
        ).fetchone()
        if not line:
            raise ValueError("Pick line was not found.")

        target_qty = float(picked_qty)
        current_picked_qty = float(line["picked_qty"] or 0)
        requested_qty = float(line["quantity"] or 0)

        if target_qty < 0:
            raise ValueError("Picked quantity cannot be negative.")
        if target_qty < current_picked_qty:
            raise ValueError("Picked quantity cannot be less than the quantity already recorded.")
        if target_qty > requested_qty:
            raise ValueError("Picked quantity cannot exceed the requested quantity.")
        if not _normalize_text(line["location_code"]):
            raise ValueError("Pick line does not have a source location.")

        delta_qty = target_qty - current_picked_qty
        if delta_qty > 0:
            available_qty = _inventory_available_at_location(conn, line["sku"], line["location_code"])
            if delta_qty > available_qty:
                raise ValueError("Not enough inventory is available at the selected location.")

            inventory_rows = conn.execute(
                """
                SELECT i.id, i.location_id, i.quantity
                FROM wms_inventory i
                JOIN wms_locations l ON l.id = i.location_id
                WHERE i.sku = ? AND l.location_code = ? AND i.quantity > 0
                ORDER BY CASE WHEN i.expiry_date IS NULL THEN 1 ELSE 0 END ASC,
                         i.expiry_date ASC,
                         i.received_at ASC,
                         i.id ASC
                """,
                (line["sku"], line["location_code"]),
            ).fetchall()

            remaining = delta_qty
            touched_locations = set()
            for inventory_row in inventory_rows:
                if remaining <= 0:
                    break
                available = float(inventory_row["quantity"] or 0)
                consume = min(available, remaining)
                conn.execute(
                    """
                    UPDATE wms_inventory
                    SET quantity = quantity - ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (consume, inventory_row["id"]),
                )
                touched_locations.add(inventory_row["location_id"])
                remaining -= consume

            conn.execute("DELETE FROM wms_inventory WHERE quantity <= 0.000001")
            for location_id in touched_locations:
                _refresh_location_units(conn, location_id)

        status = "picked" if target_qty >= requested_qty else "short"
        conn.execute(
            """
            UPDATE wms_pick_lines
            SET picked_qty = ?,
                status = ?
            WHERE id = ?
            """,
            (target_qty, status, pick_line_id),
        )

        pick_status = _refresh_pick_status(conn, line["pick_id"])
        conn.commit()
        return {
            "pick_id": line["pick_id"],
            "pick_line_id": pick_line_id,
            "picked_qty": target_qty,
            "status": status,
            "pick_status": pick_status,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_low_stock(threshold=10):
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        threshold = float(threshold)
        rows = conn.execute(
            """
            SELECT
                i.sku,
                COALESCE(p.name, '') AS product_name,
                SUM(i.quantity) AS total_qty,
                COUNT(DISTINCT i.location_id) AS location_count
            FROM wms_inventory i
            LEFT JOIN wms_products p ON p.sku = i.sku
            WHERE i.quantity > 0
            GROUP BY i.sku, p.name
            HAVING SUM(i.quantity) < ?
            ORDER BY total_qty ASC, i.sku ASC
            """,
            (threshold,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_location_utilization():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(l.zone, ''), 'Unassigned') AS zone,
                COUNT(*) AS location_count,
                COALESCE(SUM(l.capacity_units), 0) AS capacity_units,
                COALESCE(SUM(inv.used_units), 0) AS current_units,
                CASE
                    WHEN COALESCE(SUM(l.capacity_units), 0) > 0 THEN ROUND((COALESCE(SUM(inv.used_units), 0) * 100.0) / SUM(l.capacity_units), 1)
                    ELSE 0
                END AS utilization_pct
            FROM wms_locations l
            LEFT JOIN (
                SELECT location_id, SUM(quantity) AS used_units
                FROM wms_inventory
                WHERE quantity > 0
                GROUP BY location_id
            ) inv ON inv.location_id = l.id
            WHERE COALESCE(l.active, 1) = 1
            GROUP BY COALESCE(NULLIF(l.zone, ''), 'Unassigned')
            ORDER BY zone ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_wms_dashboard():
    conn = get_db()
    ensure_wms_tables(conn)
    try:
        sku_count = conn.execute(
            """
            SELECT COUNT(DISTINCT sku)
            FROM wms_inventory
            WHERE quantity > 0
            """
        ).fetchone()[0]
        on_hand_units = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM wms_inventory WHERE quantity > 0"
        ).fetchone()[0]
        pending_receipts = conn.execute(
            """
            SELECT COUNT(*)
            FROM wms_receipts
            WHERE status IN ('pending', 'receiving')
            """
        ).fetchone()[0]
        open_picks = conn.execute(
            """
            SELECT COUNT(*)
            FROM wms_picks
            WHERE status IN ('pending', 'picking')
            """
        ).fetchone()[0]

        return {
            "inventory_value": None,
            "inventory_value_display": "N/A",
            "inventory_value_note": "Unit cost is not stored in the current WMS schema.",
            "sku_count": int(sku_count or 0),
            "pending_receipts": int(pending_receipts or 0),
            "open_picks": int(open_picks or 0),
            "on_hand_units": round(float(on_hand_units or 0), 2),
            "low_stock": get_low_stock(),
            "location_utilization": get_location_utilization(),
        }
    finally:
        conn.close()
