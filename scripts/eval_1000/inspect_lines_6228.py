import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Let's inspect sentences in guidance 6228 (장바구니)
doc_6228 = next(d for d in snapshot if '/6228/subview.do' in d.get('url', ''))
lines = [l.strip() for l in doc_6228['content'].splitlines() if l.strip()]
print(f"6228 has {len(lines)} non-empty lines:")
for l in lines:
    print("  ", l)
