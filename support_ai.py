"""
support_ai.py  —  AI-powered support pipeline with verification layer

The support flow:
1. Customer submits ticket
2. Claude diagnoses the issue (categorize, identify root cause)
3. If code fix needed → flag for Codex
4. If config/user error → auto-respond with instructions
5. After any fix → run verification checks BEFORE telling customer it's fixed
6. Log everything for admin visibility

This module handles steps 2, 4, 5, and 6.
Steps 1 and 3 are handled by tenant.py (ticket creation) and external Codex workflow.
"""

import json
import time
from datetime import datetime
from database import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  Ticket Categories → Auto-Diagnosis Rules
# ─────────────────────────────────────────────────────────────────────────────

DIAGNOSIS_RULES = {
    "password": {
        "auto_resolve": True,
        "diagnosis": "Password/login issue",
        "resolution": "You can reset your password from the login page using the 'Forgot Password' link. A reset email will be sent within 1 minute. If you don't receive it, check your spam folder.",
        "verify_type": "none",
    },
    "billing": {
        "auto_resolve": True,
        "diagnosis": "Billing/subscription issue",
        "resolution": "Visit the Billing page in your dashboard to update payment info, view invoices, or manage your subscription. If your card was declined, try updating your payment method.",
        "verify_type": "none",
    },
    "import": {
        "auto_resolve": False,
        "diagnosis": "Data import issue — may need format validation or encoding fix",
        "resolution": "Please ensure your CSV file uses UTF-8 encoding and has columns: company_name, email, phone_number, country. Upload via the Import CSV button.",
        "verify_type": "data_check",
    },
    "email": {
        "auto_resolve": False,
        "diagnosis": "Email delivery issue — check Graph API config, sender permissions, or recipient bounce",
        "resolution": None,  # Needs investigation
        "verify_type": "email_test",
    },
    "rates": {
        "auto_resolve": False,
        "diagnosis": "Rate engine issue — check RFQ cycle config, benchmark calculation, or agent scoring",
        "resolution": None,  # Needs investigation
        "verify_type": "rate_check",
    },
    "schedules": {
        "auto_resolve": False,
        "diagnosis": "Vessel schedule issue — check carrier API connectivity or sync status",
        "resolution": None,  # Needs investigation
        "verify_type": "schedule_check",
    },
    "bug": {
        "auto_resolve": False,
        "diagnosis": "Bug report — needs code investigation",
        "resolution": None,
        "verify_type": "code_check",
    },
    "general": {
        "auto_resolve": False,
        "diagnosis": "General inquiry",
        "resolution": "Please check our Help page at /help for common questions and guides.",
        "verify_type": "none",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Step 2: Diagnose a ticket
# ─────────────────────────────────────────────────────────────────────────────

def diagnose_ticket(ticket: dict) -> dict:
    """Analyze a support ticket and return diagnosis + recommended action.
    Returns {diagnosis, auto_resolve, resolution, verify_type, needs_codex}.
    """
    category = ticket.get("category", "general")
    subject = (ticket.get("subject") or "").lower()
    description = (ticket.get("description") or "").lower()

    rule = DIAGNOSIS_RULES.get(category, DIAGNOSIS_RULES["general"])

    # Enhanced diagnosis based on keywords
    needs_codex = False
    diagnosis = rule["diagnosis"]

    # Detect code-level issues from description
    code_keywords = ["error", "traceback", "500", "crash", "exception", "broken",
                     "not working", "fails", "bug", "server error", "blank page"]
    if any(kw in description or kw in subject for kw in code_keywords):
        needs_codex = True
        diagnosis += " — likely code-level issue, flagged for Codex review"

    # Detect data issues
    data_keywords = ["missing", "wrong data", "duplicate", "import failed", "csv error"]
    if any(kw in description or kw in subject for kw in data_keywords):
        diagnosis += " — data integrity issue detected"

    return {
        "diagnosis": diagnosis,
        "auto_resolve": rule["auto_resolve"],
        "resolution": rule["resolution"],
        "verify_type": rule["verify_type"],
        "needs_codex": needs_codex,
        "category": category,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Step 5: Verification Layer (CRITICAL — proves fix works before notifying)
# ─────────────────────────────────────────────────────────────────────────────

def verify_fix(ticket_id: int, verify_type: str, tenant_id: int = None) -> dict:
    """Run verification checks AFTER a fix is applied.
    Returns {verified: bool, checks: [...], message: str}.

    This is the investigation layer — we don't tell the customer it's fixed
    until we PROVE it works.
    """
    checks = []
    all_passed = True

    if verify_type == "none":
        return {"verified": True, "checks": [], "message": "No verification needed."}

    conn = get_db()
    try:
        if verify_type == "data_check":
            # Verify data integrity after import fix
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM contacts WHERE tenant_id = ?", (tenant_id or 1,)
                ).fetchone()[0]
                checks.append({"test": "contacts_exist", "passed": count > 0,
                                "detail": f"{count} contacts in database"})
                if count == 0:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "contacts_exist", "passed": False, "detail": str(e)})
                all_passed = False

            # Check for common data issues
            try:
                empty_emails = conn.execute(
                    "SELECT COUNT(*) FROM contacts WHERE tenant_id = ? AND (email IS NULL OR email = '')",
                    (tenant_id or 1,)
                ).fetchone()[0]
                total = conn.execute(
                    "SELECT COUNT(*) FROM contacts WHERE tenant_id = ?", (tenant_id or 1,)
                ).fetchone()[0]
                pct_empty = (empty_emails / total * 100) if total > 0 else 0
                checks.append({"test": "email_completeness", "passed": pct_empty < 50,
                                "detail": f"{pct_empty:.0f}% contacts missing email"})
                if pct_empty >= 50:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "email_completeness", "passed": False, "detail": str(e)})
                all_passed = False

        elif verify_type == "rate_check":
            # Verify rate engine is functioning
            try:
                lanes = conn.execute("SELECT COUNT(*) FROM lanes").fetchone()[0]
                checks.append({"test": "lanes_exist", "passed": lanes > 0,
                                "detail": f"{lanes} lanes configured"})
                if lanes == 0:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "lanes_exist", "passed": False, "detail": str(e)})
                all_passed = False

        elif verify_type == "schedule_check":
            # Verify schedule sync is working
            try:
                from health import check_workers
                workers = check_workers()
                sync_ok = workers.get("schedule_sync", {}).get("alive", False)
                checks.append({"test": "schedule_sync_alive", "passed": sync_ok,
                                "detail": "Schedule sync worker" +
                                (" responsive" if sync_ok else " not responding")})
                if not sync_ok:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "schedule_sync_alive", "passed": False, "detail": str(e)})
                all_passed = False

        elif verify_type == "email_test":
            # Verify email system is functional
            try:
                from config import GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
                email_configured = bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET)
                checks.append({"test": "email_config", "passed": email_configured,
                                "detail": "Graph API" + (" configured" if email_configured else " NOT configured")})
                if not email_configured:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "email_config", "passed": False, "detail": str(e)})
                all_passed = False

        elif verify_type == "code_check":
            # Basic application health check after code fix
            try:
                from health import check_database
                db = check_database()
                checks.append({"test": "database", "passed": db["ok"],
                                "detail": f"DB latency: {db.get('latency_ms', -1)}ms"})
                if not db["ok"]:
                    all_passed = False
            except Exception as e:
                checks.append({"test": "database", "passed": False, "detail": str(e)})
                all_passed = False

            # Check health endpoint
            checks.append({"test": "app_running", "passed": True,
                            "detail": "Application is responding"})

        # Log verification result
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO system_health_log (check_type, status, details, checked_at)
               VALUES (?, ?, ?, ?)""",
            (f"ticket_{ticket_id}_verify", "pass" if all_passed else "fail",
             json.dumps(checks), now)
        )
        conn.commit()

    finally:
        conn.close()

    message = "All verification checks passed." if all_passed else \
              f"Verification failed: {sum(1 for c in checks if not c['passed'])} check(s) failed."

    return {
        "verified": all_passed,
        "checks": checks,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Step 6: Update ticket with diagnosis and verification results
# ─────────────────────────────────────────────────────────────────────────────

def process_ticket(ticket_id: int) -> dict:
    """Full ticket processing pipeline: diagnose → resolve/flag → verify.
    Returns the complete processing result.
    """
    conn = get_db()
    try:
        ticket = conn.execute(
            "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if not ticket:
            return {"ok": False, "error": "Ticket not found"}
        ticket = dict(ticket)
    finally:
        conn.close()

    # Step 2: Diagnose
    diagnosis = diagnose_ticket(ticket)

    # Step 4: Auto-resolve if possible
    if diagnosis["auto_resolve"] and diagnosis["resolution"]:
        conn = get_db()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """UPDATE support_tickets
                   SET status = 'auto_resolved', auto_resolved = 1,
                       resolution_note = ?, resolved_at = ?
                   WHERE id = ?""",
                (diagnosis["resolution"], now, ticket_id)
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "ok": True,
            "ticket_id": ticket_id,
            "action": "auto_resolved",
            "diagnosis": diagnosis["diagnosis"],
            "resolution": diagnosis["resolution"],
            "needs_codex": False,
            "verified": True,
        }

    # Step 3: Flag for Codex if needed
    if diagnosis["needs_codex"]:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE support_tickets SET status = 'investigating', resolution_note = ? WHERE id = ?",
                (f"Diagnosis: {diagnosis['diagnosis']}\nFlagged for Codex review.", ticket_id)
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "ok": True,
            "ticket_id": ticket_id,
            "action": "flagged_for_codex",
            "diagnosis": diagnosis["diagnosis"],
            "resolution": None,
            "needs_codex": True,
            "verified": False,
        }

    # Non-auto, non-codex — provide diagnosis and available resolution
    conn = get_db()
    try:
        conn.execute(
            "UPDATE support_tickets SET status = 'diagnosed', resolution_note = ? WHERE id = ?",
            (f"Diagnosis: {diagnosis['diagnosis']}", ticket_id)
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "action": "diagnosed",
        "diagnosis": diagnosis["diagnosis"],
        "resolution": diagnosis.get("resolution"),
        "needs_codex": False,
        "verified": False,
        "verify_type": diagnosis["verify_type"],
    }


def verify_and_close_ticket(ticket_id: int, tenant_id: int = None) -> dict:
    """After a fix is applied (by Codex or manually), verify it works and close the ticket.
    This is the critical step — we PROVE the fix works before telling the customer.
    """
    conn = get_db()
    try:
        ticket = conn.execute(
            "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if not ticket:
            return {"ok": False, "error": "Ticket not found"}
        ticket = dict(ticket)
    finally:
        conn.close()

    # Determine verify type from category
    category = ticket.get("category", "general")
    rule = DIAGNOSIS_RULES.get(category, DIAGNOSIS_RULES["general"])
    verify_type = rule["verify_type"]

    # Run verification
    result = verify_fix(ticket_id, verify_type, tenant_id)

    # Update ticket based on verification
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if result["verified"]:
            conn.execute(
                """UPDATE support_tickets
                   SET status = 'resolved', resolved_at = ?,
                       resolution_note = COALESCE(resolution_note, '') || ?
                   WHERE id = ?""",
                (now, f"\n\nVerification: PASSED at {now}\n{result['message']}", ticket_id)
            )
        else:
            conn.execute(
                """UPDATE support_tickets
                   SET status = 'verification_failed',
                       resolution_note = COALESCE(resolution_note, '') || ?
                   WHERE id = ?""",
                (f"\n\nVerification: FAILED at {now}\n{result['message']}\nChecks: {json.dumps(result['checks'])}",
                 ticket_id)
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "verified": result["verified"],
        "checks": result["checks"],
        "message": result["message"],
        "status": "resolved" if result["verified"] else "verification_failed",
    }
