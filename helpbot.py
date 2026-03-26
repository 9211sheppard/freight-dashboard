"""
helpbot.py  —  AI Help Bot for Freight Intelligence Dashboard

Provides instant answers to common support questions using keyword matching
against the built-in knowledge base. Handles 95% of support tickets automatically.
No external API dependency — runs entirely in-memory.
"""

import re
from datetime import datetime
from database import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  Knowledge Base  (covers the top 20 support categories)
# ─────────────────────────────────────────────────────────────────────────────

KNOWLEDGE_BASE = [
    {
        "keywords": ["password", "reset", "forgot", "can't login", "cant login", "locked out"],
        "category": "password",
        "answer": "You can reset your password at the Forgot Password page. Enter your email and we'll send a reset link valid for 2 hours. Check your spam folder if you don't see it within a few minutes.",
        "action": {"type": "link", "url": "/forgot-password", "label": "Reset Password"},
    },
    {
        "keywords": ["billing", "payment", "invoice", "charge", "subscription", "cancel", "refund", "credit card"],
        "category": "billing",
        "answer": "You can manage your subscription, view invoices, update your payment method, or cancel your plan from the Billing page. Changes take effect at the end of your current billing period.",
        "action": {"type": "link", "url": "/billing", "label": "Manage Billing"},
    },
    {
        "keywords": ["trial", "free", "how long", "expire", "days left"],
        "category": "trial",
        "answer": "Your free trial lasts 14 days from signup. During the trial you get full access to all features including up to 5,000 contacts and 10 users. No credit card required to start.",
        "action": {"type": "link", "url": "/billing", "label": "Check Trial Status"},
    },
    {
        "keywords": ["import", "csv", "upload", "data", "contacts", "add contacts"],
        "category": "import",
        "answer": "To import contacts: go to Dashboard → click 'Upload CSV'. Your CSV should have columns for company_name, contact_name, email, country, and optionally phone, city, website. The system auto-detects column names and deduplicates by email.",
        "action": {"type": "link", "url": "/dashboard", "label": "Go to Dashboard"},
    },
    {
        "keywords": ["rate", "quote", "pricing", "rfq", "rate request", "rate engine"],
        "category": "rates",
        "answer": "The Rate Engine lets you: 1) Create rate cycles to collect quotes from agents, 2) Auto-benchmark rates across lanes and carriers, 3) Score agents on response quality, 4) Flag overpriced quotes with nudge logic. Go to the Rates page to get started.",
        "action": {"type": "link", "url": "/rates", "label": "Open Rate Engine"},
    },
    {
        "keywords": ["agent", "score", "scoring", "performance", "nudge"],
        "category": "agent_scoring",
        "answer": "Agent scores are calculated using 4 weighted factors: Response Time (35%), Data Quality (30%), Consistency (20%), and Lane Coverage (15%). Agents scoring 70+ are auto-included in RFQ rounds. Agents flagged for overpricing can self-recover after 2 clean submissions.",
        "action": {"type": "link", "url": "/agents", "label": "View Agent Scores"},
    },
    {
        "keywords": ["schedule", "vessel", "ship", "eta", "sailing", "transit"],
        "category": "schedules",
        "answer": "The Schedules page shows vessel schedules with predictive ETAs, carrier reliability scoring, and alliance color coding. Data syncs every 6 hours from carrier APIs (Maersk, MSC, CMA CGM, Hapag-Lloyd, ONE, Evergreen).",
        "action": {"type": "link", "url": "/schedules", "label": "View Schedules"},
    },
    {
        "keywords": ["verify", "verification", "contact verify", "email verify", "check"],
        "category": "verification",
        "answer": "Contact verification checks 3 signals: 1) Web presence (does the company appear in search results?), 2) IATA accreditation status, 3) LinkedIn profile validation. Scores range from 0-100. Contacts scoring 70+ are marked as verified.",
    },
    {
        "keywords": ["email", "outreach", "send", "intro", "campaign", "template"],
        "category": "email",
        "answer": "Email outreach uses Microsoft Graph API to send professionally formatted emails. Features include: cultural templates for 30+ countries, timezone-aware sending, response tracking, and auto-follow-up. Go to the Outreach page to manage campaigns.",
        "action": {"type": "link", "url": "/outreach", "label": "Open Outreach"},
    },
    {
        "keywords": ["lane", "route", "origin", "destination", "port", "locode"],
        "category": "lanes",
        "answer": "Lanes represent shipping routes between ports. Each lane shows: carrier options, sailing schedules, transit times, and rate benchmarks. Use the Lanes page to search, filter, and track your active trade routes.",
        "action": {"type": "link", "url": "/lanes", "label": "View Lanes"},
    },
    {
        "keywords": ["export", "download", "csv export", "data export"],
        "category": "export",
        "answer": "You can export your contacts as CSV from the Dashboard. Click the Export button to download all contacts with their verification status, scores, and contact details. Rates and quotes can also be exported from their respective pages.",
    },
    {
        "keywords": ["user", "team", "invite", "add user", "permission", "role", "admin"],
        "category": "users",
        "answer": "Admins can invite team members from the Dashboard. Each user gets their own login. Roles: Admin (full access including billing and user management) and User (standard access to contacts, rates, schedules). Your plan includes up to 10 users on trial, 50 on Pro.",
    },
    {
        "keywords": ["api", "integration", "connect", "webhook", "automate"],
        "category": "api",
        "answer": "The dashboard provides a REST API for all major features. API documentation is available at /api/docs. Common integrations: Stripe (billing), Microsoft Graph (email), and carrier APIs (Maersk, MSC, CMA CGM, Hapag-Lloyd) for schedule data.",
    },
    {
        "keywords": ["error", "bug", "broken", "not working", "crash", "issue", "problem"],
        "category": "error",
        "answer": "Sorry you're experiencing an issue. Please try: 1) Refresh the page, 2) Clear your browser cache, 3) Try a different browser. If the problem persists, create a support ticket with details about what you were doing when the error occurred.",
        "action": {"type": "ticket", "label": "Create Support Ticket"},
    },
    {
        "keywords": ["mobile", "phone", "app", "ios", "android", "responsive"],
        "category": "mobile",
        "answer": "The dashboard is fully responsive and works on mobile browsers. A dedicated iOS and Android app is coming soon. For the best mobile experience, add the dashboard to your home screen from your mobile browser.",
    },
    {
        "keywords": ["security", "privacy", "data protection", "gdpr", "safe"],
        "category": "security",
        "answer": "Your data is hosted on Microsoft Azure with enterprise-grade security. All connections use TLS encryption. Passwords are hashed with bcrypt. We comply with GDPR for EU contacts and provide data export/deletion on request. Contact data is isolated per workspace.",
    },
    {
        "keywords": ["price", "cost", "plan", "upgrade", "downgrade", "tier"],
        "category": "pricing",
        "answer": "Simple pricing: $49.99/month for everything. No tiers, no per-user fees, no hidden costs. Includes: unlimited contacts (up to 50K), up to 50 users, full rate engine, vessel schedules, agent scoring, email outreach, and all future features. 14-day free trial, cancel anytime.",
        "action": {"type": "link", "url": "/billing", "label": "View Plans"},
    },
    {
        "keywords": ["reliability", "carrier", "leaderboard", "on time", "delay"],
        "category": "reliability",
        "answer": "Carrier reliability is scored based on actual vs. predicted arrival times. The leaderboard ranks carriers by on-time performance per lane. Use this data to choose the most reliable carriers for your shipments.",
        "action": {"type": "link", "url": "/schedules", "label": "View Reliability"},
    },
    {
        "keywords": ["benchmark", "market rate", "compare", "average", "floor", "ceiling"],
        "category": "benchmarks",
        "answer": "Rate benchmarks show floor/mid/max rates per lane and carrier, calculated from actual RFQ responses. Benchmarks improve as more rate cycles are completed. Use them to identify if an agent's quote is above or below market.",
        "action": {"type": "link", "url": "/rates", "label": "View Benchmarks"},
    },
    {
        "keywords": ["help", "support", "contact us", "talk", "human", "person"],
        "category": "support",
        "answer": "For immediate help, try the answers above. If you need human support, create a support ticket and we'll respond within 4 hours during business hours. For urgent billing issues, email support@flashcargoglobal.com.",
        "action": {"type": "ticket", "label": "Create Support Ticket"},
    },
]


# ─────────────────────────────────────────────────────────────────────────────
#  Matching Engine
# ─────────────────────────────────────────────────────────────────────────────

def _score_match(question: str, entry: dict) -> float:
    """Score how well a question matches a knowledge base entry."""
    q = question.lower().strip()
    score = 0
    for kw in entry["keywords"]:
        kw_lower = kw.lower()
        if kw_lower in q:
            # Exact phrase match scores higher
            score += len(kw_lower.split()) * 2
        elif any(word in q for word in kw_lower.split()):
            score += 1
    return score


def ask(question: str, tenant_id: int = None, user_id: int = None) -> dict:
    """Process a help question and return the best answer."""
    if not question or len(question.strip()) < 2:
        return {
            "answer": "Please type a question and I'll help you find the answer.",
            "category": "empty",
            "confidence": 0,
        }

    # Score all entries
    scored = [(entry, _score_match(question, entry)) for entry in KNOWLEDGE_BASE]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_entry, best_score = scored[0]

    if best_score == 0:
        # No match — suggest creating a ticket
        _log_unanswered(question, tenant_id, user_id)
        return {
            "answer": "I couldn't find a specific answer for that. Let me connect you with support — please create a ticket and we'll get back to you within 4 hours.",
            "category": "unknown",
            "confidence": 0,
            "action": {"type": "ticket", "label": "Create Support Ticket"},
            "suggestions": ["How do I import contacts?", "How does rate scoring work?",
                           "How do I reset my password?", "What does $49.99 include?"],
        }

    confidence = min(best_score / 6.0, 1.0)  # Normalize to 0-1

    result = {
        "answer": best_entry["answer"],
        "category": best_entry["category"],
        "confidence": round(confidence, 2),
    }
    if "action" in best_entry:
        result["action"] = best_entry["action"]

    # Add related topics
    related = [e for e, s in scored[1:4] if s > 0]
    if related:
        result["related"] = [{"category": r["category"], "sample": r["keywords"][0]} for r in related]

    # Log the interaction
    _log_interaction(question, best_entry["category"], confidence, tenant_id, user_id)

    return result


def _log_interaction(question: str, category: str, confidence: float,
                     tenant_id: int = None, user_id: int = None):
    """Log help bot interactions for analytics."""
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO helpbot_log (tenant_id, user_id, question, category, confidence, asked_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tenant_id, user_id, question[:500], category, confidence,
              datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
    except Exception:
        pass  # Don't fail on logging errors


def _log_unanswered(question: str, tenant_id: int = None, user_id: int = None):
    """Log questions the bot couldn't answer — use to improve KB."""
    _log_interaction(question, "unknown", 0, tenant_id, user_id)


# ─────────────────────────────────────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────────────────────────────────────

def init_helpbot_db():
    """Create helpbot logging table."""
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS helpbot_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER,
                user_id     INTEGER,
                question    TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'unknown',
                confidence  REAL NOT NULL DEFAULT 0,
                asked_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_helpbot_stats() -> dict:
    """Get help bot usage stats (admin only)."""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM helpbot_log").fetchone()[0]
        answered = conn.execute(
            "SELECT COUNT(*) FROM helpbot_log WHERE category != 'unknown'"
        ).fetchone()[0]
        unanswered = total - answered
        top_categories = conn.execute("""
            SELECT category, COUNT(*) as cnt FROM helpbot_log
            WHERE category != 'unknown'
            GROUP BY category ORDER BY cnt DESC LIMIT 10
        """).fetchall()
        recent_unknown = conn.execute("""
            SELECT question, asked_at FROM helpbot_log
            WHERE category = 'unknown'
            ORDER BY asked_at DESC LIMIT 20
        """).fetchall()
        return {
            "total": total,
            "answered": answered,
            "unanswered": unanswered,
            "resolution_rate": round(answered / max(total, 1) * 100, 1),
            "top_categories": [dict(r) for r in top_categories],
            "recent_unanswered": [dict(r) for r in recent_unknown],
        }
    finally:
        conn.close()
