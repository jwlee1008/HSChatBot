import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']

# Let's inspect notice kinds
kinds = {'correction': 0, 'extension': 0, 'cancellation': 0, 'result': 0, 'announcement': 0}
for n in notices:
    t = n.get('title', '')
    c = n.get('content', '') or ''
    combined = t + ' ' + c[:200]
    if any(k in t for k in ['[수정]', '[정정]', '내용 정정', '수정 안내', '정정 공고', '정정 안내']) or '공지 내용 수정' in c[:200]:
        kinds['correction'] += 1
    elif any(k in t for k in ['[연장]', '기간 연장', '추가 접수', '추가 모집', '추가 신청', '일정 연장']):
        kinds['extension'] += 1
    elif any(k in t for k in ['[취소]', '폐강', '행사 취소', '선발 취소', '운영 취소']):
        kinds['cancellation'] += 1
    elif any(k in t for k in ['선발 결과', '합격자 발표', '최종 합격', '선정 결과', '수상자 발표', '장학생 선발 결과']):
        kinds['result'] += 1
    else:
        kinds['announcement'] += 1

print('Notice kinds:', kinds)
