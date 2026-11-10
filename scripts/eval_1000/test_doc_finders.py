import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

doc_by_url = {}
for d in snapshot:
    url = d.get('url', '')
    if url not in doc_by_url:
        doc_by_url[url] = d

doc_by_id = {d['id']: d for d in snapshot}

def find_doc(url_keyword=None, title_keyword=None, source_type=None):
    candidates = snapshot
    if source_type:
        candidates = [d for d in candidates if d.get('source_type') == source_type]
    if url_keyword:
        candidates = [d for d in candidates if url_keyword in d.get('url', '')]
    if title_keyword:
        candidates = [d for d in candidates if title_keyword in d.get('title', '')]
    return candidates

# Test finding key documents
print("6225:", len(find_doc(url_keyword='6225')))
print("6228:", len(find_doc(url_keyword='6228')))
print("6234:", len(find_doc(url_keyword='6234')))
print("6236:", len(find_doc(url_keyword='6236')))
print("6248:", len(find_doc(url_keyword='6248')))
print("6249:", len(find_doc(url_keyword='6249')))
print("6264:", len(find_doc(url_keyword='6264')))
print("6096:", len(find_doc(url_keyword='6096')))

# Notice search test
print("Notice 폐강:", len(find_doc(title_keyword='폐강', source_type='notice')))
print("Notice 국가장학금:", len(find_doc(title_keyword='국가장학금', source_type='notice')))
print("Notice 휴학:", len(find_doc(title_keyword='휴학', source_type='notice')))
