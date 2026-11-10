import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Inspect FAQs related to course/class/grades
faqs = [d for d in snapshot if d.get('source_type') == 'faq']
print(f"Total FAQs: {len(faqs)}")

course_faqs = []
for f in faqs:
    cat = f.get('category', '')
    title = f.get('title', '')
    content = f.get('content', '') or ''
    if any(w in (cat + ' ' + title) for w in ['수강신청', '계절학기', '상상더학기', '수업', '사이버강의']):
        course_faqs.append(f)

print(f"Course & Class FAQs: {len(course_faqs)}")
for cf in course_faqs[:8]:
    print(f"  [{cf['category']}] {cf['title']} ({cf['id'][:8]})")
    lines = [l.strip() for l in (cf.get('content') or '').splitlines() if l.strip()]
    if lines:
        print(f"    Ans line 1: {lines[0][:80]}")
