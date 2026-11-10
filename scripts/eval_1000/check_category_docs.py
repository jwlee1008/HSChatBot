import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

# Find relevant docs for each category
category_patterns = {
    '수강신청': r'수강|장바구니|폐강|수강정정|수강신청|계절학기|계절수업',
    '휴학·복학': r'휴학|복학|조기복학|귀향복학',
    '졸업요건': r'졸업|학위취득|조기졸업|학위수여|졸업작품|졸업전시|졸업논문|졸업시험',
    '장학금': r'장학|장학생|국가장학|학자금|근로장학|희망사다리',
    '학사일정': r'학사일정|개강|종강|보강|기말고사|중간고사|방학',
}

for cat_name, pat in category_patterns.items():
    matching_docs = []
    for d in snapshot:
        text = d.get('title', '') + ' ' + (d.get('content', '') or '')
        if re.search(pat, text):
            matching_docs.append(d)
    print(f"Category [{cat_name}]: {len(matching_docs)} documents match pattern.")
    # Show counts by source_type
    from collections import Counter
    st_counts = Counter(d.get('source_type') for d in matching_docs)
    print(f"   By source_type: {st_counts}")
