import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Print guidances related to academics
for d in snapshot:
    if d.get('source_type') == 'guidance':
        title = d.get('title', '')
        url = d.get('url', '')
        cat = d.get('category', '')
        if any(w in (title + ' ' + cat) for w in ['수업', '수강', '학사일정', '성적', '졸업', '학적', '휴학', '복학', '장학', '등록']):
            print(f"[{cat}] {title} -> {url}")
