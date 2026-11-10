import sys
import json
import re
import hashlib

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']
print(f"Loaded {len(notices)} notices.")

# Let's inspect some samples for topics and see how they are distributed
topic_keywords = {
    'COURSE': ['수강신청', '수강 정정', '수강포기', '수강철회', '장바구니', '폐강', '계절학기', '계절수업', '수강취소', '수강'],
    'LEAVE_RETURN': ['휴학', '복학', '군휴학', '일반휴학', '조기복학', '휴학연장'],
    'GRADUATION': ['졸업', '학위취득', '학위수여', '졸업요건', '졸업사정', '조기졸업', '졸업작품', '졸업시험', '학위취득유예', '졸업유예'],
    'SCHOLARSHIP': ['장학', '장학금', '장학생', '국가장학', '국가근로', '학자금', '희망사다리', '생활비대출', '장학증서'],
    'ACADEMIC_CALENDAR': ['학사일정', '개강', '종강', '보강', '기말고사', '중간고사', '수업일수', '방학 일정'],
    'GRADES_CREDITS': ['성적', '학점', '성적조회', '성적정정', '성적이의', '학점포기', '학점교류', '학점인정'],
    'STUDENT_STATUS': ['전과', '트랙', '다전공', '부전공', '복수전공', '제2트랙', '제1트랙', '재입학', '자퇴', '제적', '전공변경', '트랙변경', '학적'],
    'TUITION': ['등록금', '분할납부', '등록 안내', '납부 안내', '등록금 환불', '추가등록', '학기초과자 등록'],
    'CAREER': ['취업', '채용', '인턴', '현장실습', '창업', '진로', '일자리', '면접', '서류전형', '직무', 'IPP', '기업 리얼후기'],
    'CAMPUS_PROGRAM': ['비교과', '봉사', '특강', '공모전', '서포터즈', '캠프', '멘토링', '동아리', '워크샵', '경진대회', '사회봉사', '교류', 'WFK'],
    'STUDENT_LIFE': ['기숙사', '도서관', '생활관', '셔틀버스', '학식', '식당', '보건', '시설', 'IT', '정보전산', '주차', '증명서', '학생증', '예비군']
}

matched_counts = {k: 0 for k in topic_keywords}
unmatched = []

for doc in notices:
    text = (doc.get('title', '') + ' ' + (doc.get('content', '') or ''))
    matched = False
    for top, kws in topic_keywords.items():
        if any(kw in text for kw in kws):
            matched_counts[top] += 1
            matched = True
    if not matched:
        unmatched.append(doc)

print("Keyword hits count:")
for k, v in matched_counts.items():
    print(f"  {k:18s}: {v}")
print(f"Total unmatched: {len(unmatched)}")
if unmatched:
    for u in unmatched[:5]:
        print(f"  Unmatched sample: {u['title']}")
