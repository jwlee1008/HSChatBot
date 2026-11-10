import sys
import json
import re
import hashlib
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json', 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']
print(f"Total notices to tag: {len(notices)}")

# Priority keyword mapping for TITLE matching
# (topic, pattern, label)
TITLE_RULES = [
    # TUITION
    ('TUITION', r'등록금|분할납부|등록\s*안내|추가등록|등록금\s*수납', '등록금'),
    # COURSE
    ('COURSE', r'수강신청|장바구니|폐강|수강\s*정정|수강포기|계절학기|계절수업|수강철회', '수강신청'),
    # LEAVE_RETURN
    ('LEAVE_RETURN', r'휴학|복학|조기복학|귀향복학', '휴학/복학'),
    # GRADUATION
    ('GRADUATION', r'졸업요건|졸업사정|조기졸업|학위취득\s*유예|학위수여식|졸업식|졸업작품|졸업전시|졸업시험|졸업논문|졸업유예|졸업예정|졸업\s*안내', '졸업'),
    # SCHOLARSHIP
    ('SCHOLARSHIP', r'장학금|장학생|국가장학|학자금|근로장학|희망사다리|생활비대출|장학증서|장학\s*안내|장학선발|\[장학\]', '장학금'),
    # ACADEMIC_CALENDAR
    ('ACADEMIC_CALENDAR', r'학사일정|개강|종강|보강\s*일정|수업일수', '학사일정'),
    # GRADES_CREDITS
    ('GRADES_CREDITS', r'성적\s*조회|성적\s*열람|성적\s*정정|성적이의|학점교류|학점인정|학점포기', '성적/학점'),
    # STUDENT_STATUS
    ('STUDENT_STATUS', r'전과\s*신청|전과\s*선발|트랙\s*선택|트랙\s*신청|트랙\s*변경|다전공|복수전공|부전공|재입학|자퇴|제적|전공변경', '학적/트랙/전과'),
    # CAREER
    ('CAREER', r'채용|인턴|현장실습|취업|창업|일자리|직무|진로|IPP|채용연계|공채|신입사원', '진로/취업'),
    # CAMPUS_PROGRAM
    ('CAMPUS_PROGRAM', r'비교과|봉사|특강|공모전|서포터즈|캠프|멘토링|동아리|워크샵|경진대회|단기연수|어학연수|해외연수|대회', '비교과/프로그램'),
    # STUDENT_LIFE
    ('STUDENT_LIFE', r'기숙사|생활관|우촌학사|도서관|식당|시설|IT|포털|와이파이|전자출결|스마트자기관리|보건실|심리상담|예비군|학생증|증명서|셔틀버스|통학버스|대관', '학생생활/복지/시설'),
]

# Secondary / body keywords
BODY_RULES = [
    ('TUITION', [r'등록금\s*납부', r'분할납부', r'등록금\s*고지서', r'등록금\s*환불']),
    ('COURSE', [r'수강신청', r'장바구니', r'폐강', r'수강\s*정정', r'수강포기', r'계절학기', r'계절수업']),
    ('LEAVE_RETURN', [r'일반휴학', r'군휴학', r'복학\s*신청', r'휴학\s*신청', r'조기복학']),
    ('GRADUATION', [r'졸업요건', r'졸업사정', r'조기졸업', r'학위취득\s*유예', r'학위수여식', r'졸업식']),
    ('SCHOLARSHIP', [r'장학금\s*지급', r'국가장학금', r'교내장학금', r'교외장학금', r'장학생\s*선발', r'학자금\s*대출']),
    ('ACADEMIC_CALENDAR', [r'학사일정', r'개강일', r'종강일', r'수업일수']),
    ('GRADES_CREDITS', [r'성적\s*조회', r'성적\s*정정', r'학점교류', r'학점인정']),
    ('STUDENT_STATUS', [r'전과\s*신청', r'트랙\s*선택', r'다전공\s*신청', r'재입학\s*신청']),
    ('CAREER', [r'채용공고', r'인턴십', r'현장실습', r'취업지원', r'창업지원']),
    ('CAMPUS_PROGRAM', [r'비교과\s*프로그램', r'봉사활동', r'특강\s*안내', r'공모전\s*안내', r'멘토링\s*프로그램']),
    ('STUDENT_LIFE', [r'생활관\s*입사', r'도서관\s*이용', r'전자출결', r'예비군\s*훈련', r'학생증\s*발급']),
]

def find_first_quote(text, patterns):
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            start = max(0, m.start() - 10)
            end = min(len(text), m.end() + 15)
            # Find cleaner sentence/phrase boundary
            matched_str = m.group(0)
            # Just return exact matching substring or a short surrounding quote that exists in text
            return matched_str
    return None

def extract_notice_kind(title, content):
    combined = title + " " + (content[:300] if content else "")
    if re.search(r'\[[^\]]*수정[^\]]*\]|\[[^\]]*정정[^\]]*\]|\(수정\)|\(정정\)|수정\s*안내|정정\s*공고|정정\s*안내|공지\s*내용\s*수정', title):
        # ensure not "수강신청 정정" unless brackets specify correction
        if not re.search(r'수강(?:\s*신청)?\s*정정', title) or re.search(r'\[[^\]]*수정[^\]]*\]|\[[^\]]*정정[^\]]*\]', title):
            return "correction"
    if re.search(r'\[[^\]]*연장[^\]]*\]|\(연장\)|기간\s*연장|추가\s*접수|추가\s*모집|추가\s*신청|일정\s*연장|마감\s*연장', title):
        return "extension"
    if re.search(r'\[[^\]]*취소[^\]]*\]|\(취소\)|폐강|행사\s*취소|선발\s*취소|운영\s*취소', title):
        return "cancellation"
    if re.search(r'선발\s*결과|합격자\s*발표|최종\s*합격|선정\s*결과|수상자\s*발표|장학생\s*선발\s*결과', title):
        return "result"
    return "announcement"

def extract_terms(title, content):
    text = title + " " + (content[:500] if content else "")
    terms = []
    evidence = []
    
    # 202X학년도 Y학기 / 202X-Y학기 / 202X년도 Y학기
    m = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*([12])학기', text)
    if m:
        year = int(m.group(1))
        sem = m.group(2)
        quote = m.group(0)
        # find where quote exists exactly in title or content
        target_text = title if quote in title else content
        if target_text and quote in target_text:
            terms.append({"year": year, "semester": sem})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

    # Summer / Winter semester
    m_summer = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*(?:여름|하계)\s*(?:계절)?\s*(?:학기|수업)', text)
    if m_summer:
        year = int(m_summer.group(1))
        quote = m_summer.group(0)
        target_text = title if quote in title else content
        if target_text and quote in target_text:
            terms.append({"year": year, "semester": "summer"})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

    m_winter = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*(?:겨울|동계)\s*(?:계절)?\s*(?:학기|수업)', text)
    if m_winter:
        year = int(m_winter.group(1))
        quote = m_winter.group(0)
        target_text = title if quote in title else content
        if target_text and quote in target_text:
            terms.append({"year": year, "semester": "winter"})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

    return terms, evidence

def extract_audience(title, content):
    text = title + " " + (content[:500] if content else "")
    candidates = ["학부생", "재학생", "신입생", "편입생", "졸업예정자", "휴학생", "복학생", "대학원생", "학기초과자", "외국인 유학생", "장애학생", "예비군"]
    found = []
    for cand in candidates:
        if cand in title or (content and cand in content[:300]):
            found.append(cand)
    return found

# Let's run a test pass over all notices
tagged_records = []
topic_counts = Counter()
status_counts = Counter()

for doc in notices:
    doc_id = doc['id']
    title = doc.get('title', '')
    content = doc.get('content', '') or ''
    source_hash = hashlib.sha256((title + "\n" + content).encode('utf-8')).hexdigest()
    
    full_text = title + "\n" + content
    
    topics = []
    evidence_list = []
    
    # 1. Match title rules
    for topic, pat, label in TITLE_RULES:
        m = re.search(pat, title)
        if m and topic not in topics:
            topics.append(topic)
            quote = m.group(0)
            evidence_list.append({"field": f"topics.{topic}", "quote": quote})
            if len(topics) >= 2:
                break
                
    # 2. If no title match, check body rules
    if not topics:
        for topic, pats in BODY_RULES:
            for pat in pats:
                m = re.search(pat, content[:1000])
                if m and topic not in topics:
                    topics.append(topic)
                    quote = m.group(0)
                    evidence_list.append({"field": f"topics.{topic}", "quote": quote})
                    break
            if len(topics) >= 2:
                break
                
    # 3. Check for specific other/faculty/external
    if not topics:
        if any(w in full_text for w in ['교원', '교수', '직원', '발전기금', '기부', '이사회', '장례', '추모', '입찰', '공사', '채용 (교원)']):
            topics = ["OTHER"]
            status = "tagged"
            m = re.search(r'교원|교수|직원|발전기금|기부|이사회|입찰|공사', full_text)
            if m:
                evidence_list.append({"field": "topics.OTHER", "quote": m.group(0)})
        else:
            topics = ["UNCLASSIFIED"]
            status = "unclassified"
    else:
        status = "tagged"
        
    # Cap topics to 3
    topics = topics[:3]
    
    # Extract terms
    terms, term_ev = extract_terms(title, content)
    evidence_list.extend(term_ev)
    
    # Extract audience
    audience = extract_audience(title, content)
    
    # Notice kind
    notice_kind = extract_notice_kind(title, content)
    
    record = {
        "doc_id": doc_id,
        "source_hash": source_hash,
        "topics": topics,
        "terms": terms,
        "audience": audience,
        "notice_kind": notice_kind,
        "supersedes_id": None,
        "evidence": evidence_list,
        "status": status
    }
    
    tagged_records.append(record)
    for t in topics:
        topic_counts[t] += 1
    status_counts[status] += 1

print(f"Tagged {len(tagged_records)} records.")
print("Topic counts:", topic_counts)
print("Status counts:", status_counts)
