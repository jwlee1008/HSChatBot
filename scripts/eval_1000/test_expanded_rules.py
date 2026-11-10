import sys
import json
import re

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']

MORE_TITLE_RULES = [
    ('TUITION', r'등록금|분할납부|등록\s*안내|추가등록|등록금\s*수납', '등록금'),
    ('COURSE', r'수강신청|장바구니|폐강|수강\s*정정|수강포기|계절학기|계절수업|수강철회|수강', '수강'),
    ('LEAVE_RETURN', r'휴학|복학|조기복학|귀향복학', '휴학/복학'),
    ('GRADUATION', r'졸업요건|졸업사정|조기졸업|학위취득\s*유예|학위수여식|졸업식|졸업작품|졸업전시|졸업시험|졸업논문|졸업유예|졸업예정|졸업\s*안내', '졸업'),
    ('SCHOLARSHIP', r'장학금|장학생|국가장학|학자금|근로장학|희망사다리|생활비대출|장학증서|장학\s*안내|장학선발|\[장학\]', '장학금'),
    ('ACADEMIC_CALENDAR', r'학사일정|개강|종강|보강\s*일정|수업일수', '학사일정'),
    ('GRADES_CREDITS', r'성적\s*조회|성적\s*열람|성적\s*정정|성적이의|학점교류|학점인정|학점포기|성적', '성적/학점'),
    ('STUDENT_STATUS', r'전과\s*신청|전과\s*선발|전과|트랙\s*선택|트랙\s*신청|트랙\s*변경|다전공|복수전공|부전공|재입학|자퇴|제적|전공변경|학적', '학적/트랙/전과'),
    ('CAREER', r'채용|인턴|현장실습|취업|창업|일자리|직무|진로|IPP|채용연계|공채|신입사원|CEO|스타트업|기업\s*설명회|고시반', '진로/취업'),
    ('CAMPUS_PROGRAM', r'비교과|봉사|특강|공모전|서포터즈|캠프|멘토링|동아리|워크샵|경진대회|단기연수|어학연수|해외연수|대회|페스티벌|Festival|축제|방송제|이벤트|튜터링|튜터|파트너|앰버서더|아카데미|교육생\s*모집|참여자\s*모집|참가자\s*모집|참가\s*신청|수강생\s*모집|설명회|공모\s*안내', '비교과/프로그램'),
    ('STUDENT_LIFE', r'기숙사|생활관|우촌학사|도서관|식당|시설|IT|포털|와이파이|Wi-Fi|전자출결|스마트자기관리|보건실|심리상담|상담|심리검사|예비군|학생증|증명서|셔틀버스|통학버스|대관|운영시간|이용안내|AI\s*HUB|AI\s*Hub|헬피챗|서비스\s*장애|플랫폼|만족도\s*조사|설문조사|HSP', '학생생활/복지/시설'),
]

OTHER_WORDS = ['교원', '교수', '직원', '발전기금', '기부', '이사회', '장례', '추모', '입찰', '공사', '퇴직', '포상', '모금', '동행', '조의', '부고']

unclass = []
for n in notices:
    t = n.get('title', '')
    c = n.get('content', '') or ''
    matched = False
    for top, pat, label in MORE_TITLE_RULES:
        if re.search(pat, t, re.IGNORECASE):
            matched = True
            break
    if not matched:
        for top, pat, label in MORE_TITLE_RULES:
            if re.search(pat, c[:500], re.IGNORECASE):
                matched = True
                break
    if not matched:
        if any(w in (t + ' ' + c[:300]) for w in OTHER_WORDS):
            matched = True
        else:
            unclass.append(n)

print(f"Remaining unclassified count: {len(unclass)}")
for u in unclass[:10]:
    print(" ", u['title'])
