import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

cal = next(d for d in snapshot if '6096' in d.get('url', ''))
lines = [l.strip() for l in cal['content'].splitlines() if l.strip()]

events = []
current_date = None
for l in lines:
    m = re.search(r'(202[5-7]\.[0-9]{2}\.[0-9]{2}(?:\([가-힣]+\))?(?:\s*~\s*(?:202[5-7]\.)?[0-9]{2}\.[0-9]{2}(?:\([가-힣]+\))?)?)', l)
    if m:
        current_date = m.group(1)
    elif current_date and l:
        events.append((current_date, l))
        current_date = None

print(f"Calendar events 80-end:")
for dt, ev in events[80:]:
    print(f"  {dt} : {ev}")
