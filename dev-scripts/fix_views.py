#!/usr/bin/env python3
"""
dev-scripts/fix_views.py
Safely clean NUL bytes and optionally remove stray blocks.
Usage: python dev-scripts/fix_views.py /path/to/views.py
Creates a backup file views.py.bak before writing.
Requires DEV_ALLOW=1 or DEBUG=True.
"""
import os, sys

if os.environ.get('DEBUG', 'False') != 'True' and os.environ.get('DEV_ALLOW') != '1':
    print("Dev-only helper. Set DEBUG=True or DEV_ALLOW=1 to run.")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: fix_views.py path/to/views.py")
    sys.exit(1)

path = sys.argv[1]
if not os.path.exists(path):
    print("File not found:", path)
    sys.exit(1)

with open(path, 'rb') as fh:
    data = fh.read()

# remove NUL bytes
clean = data.replace(b'\x00', b'')

bak = path + '.bak'
with open(bak, 'wb') as fh:
    fh.write(data)
print("Backup written to", bak)

with open(path, 'wb') as fh:
    fh.write(clean)
print("Wrote cleaned file to", path)
