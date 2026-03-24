============================================================
  Freight Intelligence Dashboard - Setup & Administration
============================================================

QUICK START (First Time)
------------------------------------------------------------
1. Install Python 3.9+ from https://www.python.org/downloads/
   - During install, check "Add Python to PATH"
2. Extract this folder to your Desktop
3. Double-click: setup.bat
4. Double-click: run.bat
5. Browser opens to http://127.0.0.1:5000
6. Create your admin account (first user = admin)
7. Follow the in-app setup wizard

DAILY USE
------------------------------------------------------------
- Double-click run.bat -> browser opens automatically
- Dashboard is at http://127.0.0.1:5000

TEAM ACCESS
------------------------------------------------------------
- Admin: click "Add User" to invite team members by email
- Or: share the URL and have team members register at /register
- First registered user is automatically admin

IMPORTING DATA
------------------------------------------------------------
- Click the yellow "Import CSV" button in the top-right
- Supported CSV columns: company_name, email, phone, country,
  city, website, network (and more)
- The dashboard auto-detects column mappings

FEATURES
------------------------------------------------------------
- Contacts:  Search and manage your global agent network
- Schedules: Track vessel sailings with predictive ETAs
- Rates:     Benchmark freight rates from your agents
- Outreach:  Track email campaigns and responses
- Agents:    Score agent performance (admin only)

IN-APP HELP
------------------------------------------------------------
- Click the Help button in the navbar for full documentation
- Click the tour button in the navbar for a guided tour
- Click "Learn" for interactive training sessions

CONFIGURATION
------------------------------------------------------------
- config.py: API keys, email settings, database path
- Environment variables override config.py values:
  DASHBOARD_PASSWORD, EMAIL_FROM, GRAPH_TENANT_ID,
  GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, SECRET_KEY

REQUIREMENTS
------------------------------------------------------------
- Windows 10 or 11
- Python 3.9+ (with pip)
- ~100 MB disk space

TROUBLESHOOTING
------------------------------------------------------------
- "Python not found": Reinstall Python with "Add to PATH" checked
- "Port 5000 in use": Close other Flask apps or change port in app.py
- Dashboard won't load: Check that venv\Scripts\python.exe exists
- Import fails: Ensure CSV is UTF-8 encoded with column headers

============================================================
