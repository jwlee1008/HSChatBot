import sys
import json
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Collect all FAQs by category
faqs = [d for d in snapshot if d.get('source_type') == 'faq']
print(f"Total FAQs: {len(faqs)}")
faq_cats = Counter(d.get('category') for d in faqs)
for c, cnt in faq_cats.most_common():
    print(f"  {c}: {cnt}")

# Print sample FAQ from key categories
print("\n--- Sample FAQs ---")
for cat in ['수강신청·수업', '계절학기·상상더학기', '학점·졸업', '휴학·복학', '등록금납부']:
    matching = [f for f in faqs if f.get('category') == cat]
    print(f"\n[Category: {cat}] count: {len(matching)}")
    for m in matching[:3]:
        print(f"  Q: {m['title']}")
        print(f"  URL: {m['url']}")
        ans = (m.get('content') or '').replace('\n', ' ')[:100]
        print(f"  A: {ans}")
