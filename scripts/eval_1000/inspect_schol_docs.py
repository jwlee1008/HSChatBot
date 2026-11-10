import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc_6264 = next(d for d in snapshot if '/6264/subview.do' in d.get('url', ''))
doc_6262 = next(d for d in snapshot if '/6262/subview.do' in d.get('url', ''))

print("=== 6264 ===")
for l in doc_6264['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6262 ===")
for l in doc_6262['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))
