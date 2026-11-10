import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Find all course-related guidance and FAQs
guidances = [d for d in snapshot if d.get('source_type') == 'guidance' and any(n in d.get('url', '') for n in ['6222', '6223', '6224', '6225', '6226', '6227', '6228', '6229', '6230', '6104', '6105'])]
print(f"Course Guidances: {len(guidances)}")
for g in guidances:
    print(f"  ID: {g['id'][:10]} | URL: {g['url']} | Title: {g['title']}")

# Find course FAQs
faqs = [d for d in snapshot if d.get('source_type') == 'faq' and any(k in d.get('category', '') for k in ['수강', '계절', '수업'])]
print(f"Course FAQs: {len(faqs)}")
for f in faqs[:10]:
    print(f"  ID: {f['id'][:10]} | Title: {f['title'][:40]} | URL: {f['url']}")

# Find course notices
notices = [d for d in snapshot if d.get('source_type') == 'notice' and any(k in d.get('title', '') for k in ['수강', '폐강', '장바구니', '계절학기', '계절수업'])]
print(f"Course Notices: {len(notices)}")
for n in notices[:10]:
    print(f"  ID: {n['id'][:10]} | Title: {n['title'][:40]} | Date: {n.get('date')}")
