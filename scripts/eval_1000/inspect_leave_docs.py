import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc_6248 = next(d for d in snapshot if '/6248/subview.do' in d.get('url', ''))
doc_6249 = next(d for d in snapshot if '/6249/subview.do' in d.get('url', ''))
doc_6250 = next(d for d in snapshot if '/6250/subview.do' in d.get('url', ''))
doc_6251 = next(d for d in snapshot if '/6251/subview.do' in d.get('url', ''))
doc_6252 = next(d for d in snapshot if '/6252/subview.do' in d.get('url', ''))

print("=== 6248 (휴학) ===")
for l in doc_6248['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6249 (복학) ===")
for l in doc_6249['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))

print("\n=== 6250 (일반휴학상담) ===")
for l in doc_6250['content'].splitlines():
    if l.strip():
        print(" ", repr(l.strip()))
