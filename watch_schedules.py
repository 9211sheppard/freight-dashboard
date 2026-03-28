"""
watch_schedules.py
------------------
Watches the Vessel Schedule folder for new/updated CSVs and auto-syncs to DB.
Run once — stays alive in background, syncs whenever Codex drops a file.
"""
import os, time, subprocess, sys

WATCH_DIR = r"C:\Users\Owner\Desktop\Vessel Schedule"
SYNC_SCRIPT = os.path.join(os.path.dirname(__file__), "sync_schedules.py")
PYTHON = sys.executable
CHECK_INTERVAL = 15  # seconds

def get_snapshot():
    snap = {}
    try:
        for f in os.listdir(WATCH_DIR):
            if f.endswith(".csv"):
                path = os.path.join(WATCH_DIR, f)
                snap[f] = os.path.getmtime(path)
    except Exception:
        pass
    return snap

def run_sync():
    print("[watcher] Change detected — syncing...", flush=True)
    result = subprocess.run([PYTHON, SYNC_SCRIPT], capture_output=True, text=True)
    print(result.stdout, flush=True)
    if result.stderr:
        print(result.stderr, flush=True)

print(f"[watcher] Watching {WATCH_DIR} every {CHECK_INTERVAL}s", flush=True)
last_snap = get_snapshot()
print(f"[watcher] Tracking {len(last_snap)} CSV files", flush=True)

while True:
    time.sleep(CHECK_INTERVAL)
    current_snap = get_snapshot()
    changed = [f for f in current_snap if current_snap[f] != last_snap.get(f)]
    new_files = [f for f in current_snap if f not in last_snap]
    if changed or new_files:
        if new_files:
            print(f"[watcher] New files: {new_files}", flush=True)
        if changed:
            print(f"[watcher] Updated: {changed}", flush=True)
        run_sync()
        last_snap = current_snap
