import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']

corrections = []
for n in notices:
    t = n.get('title', '')
    if re.search(r'\[.*수정.*\]|\[.*정정.*\]|정정공고|정정안내|\(수정\)|\(정정\)|수정 공지', t):
        # But make sure it is not "수강신청 정정"!
        # Remember: "수강신청 정정 기간" is students correcting registration, not a correction of the notice!
        if not re.search(r'수강(?:\s*신청)?\s*정정', t) or re.search(r'\[.*수정.*\]|\[.*정정.*\]', t):
            corrections.append(t)

print(f"Correction count: {len(corrections)}")
for c in corrections[:10]:
    print(" ", c)
