import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc = next(d for d in snapshot if d['id'] == '64e16365748d99bd4a1881e4db4e76c560090f016581edea6df6dcca16da5b15')
for l in doc['content'].splitlines():
    if l.strip():
        print(repr(l.strip()))
