import sys
import json
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

print(f"Total documents in snapshot: {len(snapshot)}")

# Group by source_type
by_type = Counter(d.get('source_type') for d in snapshot)
print("Source types:", by_type)

# Inspect categories in guidance, faq, form
for st in ['guidance', 'faq', 'form']:
    docs = [d for d in snapshot if d.get('source_type') == st]
    cats = Counter(d.get('category', '') for d in docs)
    print(f"\n[{st}] total {len(docs)} docs. Top categories:")
    for c, cnt in cats.most_common(10):
        print(f"  {c}: {cnt}")
