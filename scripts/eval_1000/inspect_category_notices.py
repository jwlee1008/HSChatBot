import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\notice_tags.jsonl', 'r', encoding='utf-8') as f:
    tags = [json.loads(line) for line in f]

tag_map = {t['doc_id']: t for t in tags}
doc_map = {d['id']: d for d in snapshot}

for target_top in ['COURSE', 'LEAVE_RETURN', 'GRADUATION', 'SCHOLARSHIP', 'ACADEMIC_CALENDAR']:
    matching = [doc_map[t['doc_id']] for t in tags if target_top in t['topics']]
    print(f"\n=== Topic {target_top}: {len(matching)} notices ===")
    for m in matching[:8]:
        content_preview = (m.get('content') or '').replace('\n', ' ')[:80]
        print(f"  [{m.get('date')}] {m['title'][:50]} | {content_preview}")
