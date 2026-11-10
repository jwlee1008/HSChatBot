import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc_6234 = next(d for d in snapshot if '/6234/subview.do' in d.get('url', ''))
doc_6235 = next(d for d in snapshot if '/6235/subview.do' in d.get('url', ''))
doc_6236 = next(d for d in snapshot if '/6236/subview.do' in d.get('url', ''))
doc_6237 = next(d for d in snapshot if '/6237/subview.do' in d.get('url', ''))
doc_6238 = next(d for d in snapshot if '/6238/subview.do' in d.get('url', ''))

print("=== 6234 (졸업및학위) ===")
for l in doc_6234['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6235 (졸업사정절차) ===")
for l in doc_6235['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6236 (조기졸업) ===")
for l in doc_6236['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6237 (졸업유예) ===")
for l in doc_6237['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))
