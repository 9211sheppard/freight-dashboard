import zipfile, os
src = r'C:\Users\Owner\Desktop\tms-master'
dst = r'C:\Users\Owner\Desktop\tms-master-backup-FINAL.zip'
skip_ext = ('.log', '.pyc')
skip_dirs = {'__pycache__', '.git', 'node_modules', '.pytest_cache'}
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if not any(f.endswith(e) for e in skip_ext) and f != 'make_backup.py':
                fp = os.path.join(root, f)
                arc = os.path.join('tms-master', os.path.relpath(fp, src))
                z.write(fp, arc)
size = os.path.getsize(dst)
print(f'Backup complete: {dst}')
print(f'Size: {size/1024/1024:.1f} MB')
