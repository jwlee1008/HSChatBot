import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

course_notices = [d for d in snapshot if d.get('source_type') == 'notice' and any(k in d.get('title', '') for k in ['수강', '폐강', '장바구니', '계절학기', '계절수업'])]
print(f"Total course notices: {len(course_notices)}")
for i, n in enumerate(course_notices):
    lines = [l.strip() for l in (n.get('content') or '').splitlines() if l.strip()]
    first_lines = ' // '.join(lines[:3])[:100]
    print(f"{i+1:2d}: [{n.get('date')}] {n['title'][:40]} | {first_lines}")
