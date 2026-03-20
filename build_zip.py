import zipfile, os

DIST_DIR = r'C:\Users\Owner\Desktop\claude code\contact-dashboard\dist\ContactDashboard'
DB_SRC   = r'C:\Users\Owner\Desktop\claude code\contact-dashboard\data\contacts.db'
OUT_ZIP  = r'C:\Users\Owner\Desktop\ContactDashboard.zip'

README = (
    "ContactDashboard - Freight Intelligence Platform\n"
    "================================================\n\n"
    "HOW TO INSTALL (first time)\n"
    "---------------------------\n"
    "1. Extract this ZIP anywhere (Desktop, C:\\Apps\\, etc.)\n"
    "   You will get a ContactDashboard\\ folder.\n\n"
    "2. Double-click  >>  Start Dashboard.bat  <<  inside that folder\n"
    "   A browser opens automatically. Log in and you are done.\n\n"
    "   Always use Start Dashboard.bat to launch.\n"
    "   It handles cleanup automatically every time.\n\n"
    "HOW TO UPDATE (when you receive a new ZIP)\n"
    "------------------------------------------\n"
    "1. Close the browser tab\n"
    "2. Extract the new ZIP to the SAME location -- allow it to overwrite\n"
    "3. Double-click Start Dashboard.bat\n\n"
    "Start Dashboard.bat automatically:\n"
    "  - Stops any old running instance\n"
    "  - Cleans up leftover temp files from old versions\n"
    "  - Removes duplicate ContactDashboard folders\n"
    "  - Launches fresh\n\n"
    "Your contacts database lives in data\\contacts.db\n"
    "It is NOT overwritten on update -- your data is always safe.\n\n"
    "TROUBLESHOOTING\n"
    "---------------\n"
    "- Browser shows Loading... forever:\n"
    "  Close and re-run Start Dashboard.bat\n\n"
    "- Port already in use:\n"
    "  Start Dashboard.bat kills old instances automatically.\n"
    "  If it persists, open Task Manager and end ContactDashboard.exe\n\n"
    "Default login password: admin123\n"
    "(Ask your team leader if this has been changed)\n"
)

total_files = 0
total_bytes = 0

with zipfile.ZipFile(OUT_ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    # Walk entire dist/ContactDashboard/ folder (exe + _internal + bat)
    for root, dirs, files in os.walk(DIST_DIR):
        for file in files:
            src_path = os.path.join(root, file)
            rel = os.path.relpath(src_path, os.path.dirname(DIST_DIR))
            arc_name = rel.replace('\\', '/')
            z.write(src_path, arc_name)
            total_files += 1
            total_bytes += os.path.getsize(src_path)

    # Contacts database (next to exe so it persists between updates)
    z.write(DB_SRC, 'ContactDashboard/data/contacts.db')
    total_files += 1
    total_bytes += os.path.getsize(DB_SRC)

    # README
    z.writestr('ContactDashboard/README.txt', README)
    total_files += 1

zip_size = os.path.getsize(OUT_ZIP)
print(f"ZIP created : {OUT_ZIP}")
print(f"ZIP size    : {zip_size/1024/1024:.1f} MB  ({total_files} files, {total_bytes/1024/1024:.1f} MB uncompressed)")
print()
print("Structure inside zip:")
seen = set()
with zipfile.ZipFile(OUT_ZIP) as z:
    for info in z.infolist():
        parts = info.filename.split('/')
        top = '/'.join(parts[:2]) + ('/' if len(parts) > 2 else '')
        if top not in seen:
            seen.add(top)
            print(f"  {top}")
