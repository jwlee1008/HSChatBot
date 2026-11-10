import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc_6244 = next(d for d in snapshot if '/6244/subview.do' in d.get('url', ''))
for l in doc_6244['content'].splitlines():
    if l.strip():
        print(repr(l.strip()))
