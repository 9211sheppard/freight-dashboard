# Freight Intelligence Dashboard — Changelog

## v1.1.0 — 2026-03-20

### Added
- **Rate Intelligence Engine V2** (`rate_engine_v2.py`)
  - Benchmark calculation: drops bottom 10% of submissions, builds floor/mid/max per lane + carrier
  - Agent scoring: Response 35% / Quality 30% / Consistency 20% / Coverage 15% + Negotiation 10%
  - Nudge logic: score 70-84 → flag >30% over mid; score ≥85 → flag >35%
  - Self-recovery: 2 consecutive clean submissions → auto-unflag
  - RFQ candidates: score ≥70, not flagged, 7-day cooldown between requests
  - Smart matcher: internal only, tie-break speed > price > consistency
  - Trend tracking (activates after 3+ cycles): rising / falling / stable
  - Archive forever — no deletions, only archiving
  - Full pipeline: `run_intelligence_cycle(cycle_id)`

- **Per-user Authentication** (`auth.py`)
  - Email + password login with bcrypt hashing
  - User registration (first registered user = admin automatically)
  - Email-based password reset with 2-hour expiry tokens
  - Admin role system — admins can view leaderboard and manage users
  - Session helpers: `set_session`, `clear_session`, `current_user`, `is_admin`
  - Password change for logged-in users

- **New Templates**
  - `register.html` — account creation form
  - `forgot_password.html` — request reset link
  - `reset_password.html` — set new password via token

- **New API Routes**
  - `GET  /api/auth/me` — returns current user from session
  - `POST /api/auth/change-password` — change password (logged in)
  - `GET  /api/admin/users` — list all users (admin only)
  - `PATCH /api/admin/users/:id/role` — promote/demote user (admin only)
  - `GET  /api/v2/rates/benchmarks` — rate benchmarks by lane
  - `POST /api/v2/rates/run-cycle` — run full intelligence cycle
  - `GET  /api/v2/rates/agent-scores` — all agent scores
  - `GET  /api/v2/rates/rfq-candidates` — best agents for a lane
  - `GET  /api/v2/rates/trend` — price trend for a lane
  - `POST /api/v2/rates/nudge-response` — log nudge response
  - `GET  /api/v2/rates/flags` — flagged agents
  - `GET  /api/v2/rates/best-match` — smart rate match

- **Database** (`database.py`)
  - 8 new tables with auto-migration: `users`, `password_resets`,
    `learning_progress`, `learning_streaks`, `agent_scores`,
    `rate_benchmarks`, `nudge_log`, `rate_flags`, `rate_history`
  - Auto-migration for `rates` table: `origin_locode`, `dest_locode`,
    `validation_status`, `confidence`, `win`, `archived`, `deviation_pct`
  - Auto-migration for `lanes` table: `carrier`, `alliance`, `service`,
    `frequency`, `etd`, `eta`, `vessel`, `transit`, `source`, `confidence`,
    `locode_origin`, `locode_dest`

- **Network Access**
  - Flask binds to `0.0.0.0:5000` — accessible to all office team members
    on the same network (or via VPN)

### Changed
- Login page now accepts **email + password** (per-user accounts)
  - Legacy admin-only password-only login still works as fallback
- `requirements.txt` updated: added `bcrypt>=4.0.0`

---

## v1.0.0 — 2026-03-19

### Added
- Contact management dashboard (WFA, WWPC, FIATA, FreightNet, AHK-Japan)
- Vessel schedule lanes tab with LOCODE codes + carrier alliance color badges
- Carriers tab with FMCSA SAFER API integration
- Rate Intelligence Engine V1 (`rate_engine.py`) with email outreach
- Learning system with Freight & Logistics Masterclass
- 12-hour vessel schedule health check (`check_schedules.py`)
- CSV auto-import pipeline with deduplication and auto-fix
- PyInstaller .exe packaging (onedir mode for DLL compatibility)
