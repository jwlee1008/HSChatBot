import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

from test_tagger_full import tagged_records, notices

unclass = [n for n, r in zip(notices, tagged_records) if r['status'] == 'unclassified']
print(f"Unclassified count: {len(unclass)}")

for i, u in enumerate(unclass[:25]):
    title = u['title']
    cat = u.get('category', '')
    src = u.get('source', '')
    print(f"{i+1:2d}: [{src}] [{cat}] {title[:70]}")
