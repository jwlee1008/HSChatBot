import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc = next(d for d in snapshot if d['id'] == '3710e9aad222e964b4c715b746a51d957d19ca799797a3eb0f99166f2945d820')
for l in doc['content'].splitlines():
    if l.strip():
        print(repr(l.strip()))
