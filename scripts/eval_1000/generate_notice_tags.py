import sys
import json
import re
import hashlib
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

SNAPSHOT_PATH = r'C:\server01\.codex-work\campusrag-gemini-20261109\results\source_snapshot.json'
OUTPUT_PATH = r'C:\server01\.codex-work\campusrag-gemini-20261109\results\notice_tags.jsonl'

with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
    snapshot = json.load(f)

notices = [d for d in snapshot if d.get('source_type') == 'notice']
print(f"Loaded {len(notices)} notices from snapshot.")

# Comprehensive rules with patterns and specific quote extractors
# Ordered by priority for title matching
TITLE_TAXONOMY = [
    ('TUITION', [
        r'등록금\s*납부', r'등록금\s*분할납부', r'분할납부', r'등록금\s*고지서', r'등록금\s*환불',
        r'학기초과자\s*등록금', r'추가등록', r'등록금\s*수납', r'등록금'
    ]),
    ('COURSE', [
        r'수강신청', r'장바구니', r'폐강', r'수강\s*정정', r'수강포기', r'수강철회',
        r'여름계절학기', r'겨울계절학기', r'하계계절', r'동계계절', r'계절학기', r'계절수업',
        r'수강제한', r'수강안내'
    ]),
    ('LEAVE_RETURN', [
        r'군휴학', r'일반휴학', r'조기복학', r'귀향복학', r'휴학\s*연장', r'휴학', r'복학'
    ]),
    ('GRADUATION', [
        r'졸업요건', r'졸업사정', r'조기졸업', r'학위취득\s*유예', r'학위수여식', r'졸업식',
        r'졸업작품', r'졸업전시', r'졸업시험', r'졸업논문', r'졸업유예', r'졸업예정', r'졸업'
    ]),
    ('SCHOLARSHIP', [
        r'국가장학금', r'국가근로', r'학자금\s*대출', r'학자금\s*지원', r'희망사다리',
        r'교내장학', r'교외장학', r'장학생\s*선발', r'장학금\s*신청', r'장학금', r'장학생',
        r'\[장학\]', r'장학'
    ]),
    ('ACADEMIC_CALENDAR', [
        r'학사일정표', r'학사일정', r'개강', r'종강', r'보강\s*일정', r'보강주간', r'수업일수', r'방학\s*일정'
    ]),
    ('GRADES_CREDITS', [
        r'성적\s*조회', r'성적\s*열람', r'성적\s*정정', r'성적이의', r'학점교류', r'학점인정',
        r'학점포기', r'학점계산', r'성적평가'
    ]),
    ('STUDENT_STATUS', [
        r'전과\s*신청', r'전과\s*선발', r'전과', r'트랙\s*선택', r'트랙\s*신청', r'트랙\s*변경',
        r'전공선택', r'전공변경', r'다전공', r'복수전공', r'부전공', r'재입학', r'자퇴', r'제적', r'학적'
    ]),
    ('CAREER', [
        r'채용공고', r'채용', r'인턴십', r'인턴', r'현장실습', r'취업', r'창업', r'일자리',
        r'직무', r'진로', r'IPP', r'채용연계', r'공채', r'신입사원', r'CEO', r'스타트업',
        r'기업\s*설명회', r'고시반', r'취준'
    ]),
    ('CAMPUS_PROGRAM', [
        r'비교과', r'봉사단', r'해외봉사', r'사회봉사', r'봉사', r'특강', r'공모전', r'서포터즈',
        r'홍보대사', r'캠프', r'멘토링', r'동아리', r'워크샵', r'경진대회', r'단기연수', r'어학연수',
        r'해외연수', r'교류\s*프로그램', r'페스티벌', r'Festival', r'축제', r'방송제', r'이벤트',
        r'튜터링', r'튜터', r'앰버서더', r'아카데미', r'교육생\s*모집', r'참여자\s*모집',
        r'참가자\s*모집', r'참가\s*신청', r'수강생\s*모집', r'프로그램\s*참가'
    ]),
    ('STUDENT_LIFE', [
        r'기숙사', r'생활관', r'우촌학사', r'도서관', r'식당', r'학식', r'학생식당', r'시설',
        r'IT', r'포털', r'와이파이', r'Wi-Fi', r'전자출결', r'스마트자기관리', r'보건실',
        r'심리상담', r'상담', r'심리검사', r'예비군', r'학생증', r'증명서', r'셔틀버스',
        r'통학버스', r'대관', r'운영시간', r'이용안내', r'AI\s*HUB', r'AI\s*Hub', r'헬피챗',
        r'서비스\s*장애', r'플랫폼', r'만족도\s*조사', r'설문조사', r'HSP', r'주택', r'카페', r'케이카페'
    ]),
]

BODY_TAXONOMY = [
    ('TUITION', [r'등록금\s*납부', r'분할납부', r'등록금\s*고지서', r'등록금\s*환불', r'등록금\s*수납']),
    ('COURSE', [r'수강신청', r'장바구니', r'폐강', r'수강\s*정정', r'수강포기', r'계절학기', r'계절수업']),
    ('LEAVE_RETURN', [r'일반휴학', r'군휴학', r'복학\s*신청', r'휴학\s*신청', r'조기복학']),
    ('GRADUATION', [r'졸업요건', r'졸업사정', r'조기졸업', r'학위취득\s*유예', r'학위수여식', r'졸업식']),
    ('SCHOLARSHIP', [r'장학금\s*지급', r'국가장학금', r'교내장학금', r'교외장학금', r'장학생\s*선발', r'학자금\s*대출']),
    ('ACADEMIC_CALENDAR', [r'학사일정', r'개강일', r'종강일', r'수업일수']),
    ('GRADES_CREDITS', [r'성적\s*조회', r'성적\s*정정', r'학점교류', r'학점인정']),
    ('STUDENT_STATUS', [r'전과\s*신청', r'트랙\s*선택', r'다전공\s*신청', r'재입학\s*신청']),
    ('CAREER', [r'채용공고', r'인턴십', r'현장실습', r'취업지원', r'창업지원', r'직무교육']),
    ('CAMPUS_PROGRAM', [r'비교과\s*프로그램', r'봉사활동', r'특강\s*안내', r'공모전\s*안내', r'멘토링\s*프로그램']),
    ('STUDENT_LIFE', [r'생활관\s*입사', r'도서관\s*이용', r'전자출결', r'예비군\s*훈련', r'학생증\s*발급']),
]

OTHER_KEYWORDS = [
    '교원', '교수', '직원', '발전기금', '기부', '이사회', '장례', '추모', '입찰', '공사',
    '퇴직', '포상', '모금', '동행', '조의', '부고', '카드뉴스', '연구윤리'
]

def extract_exact_quote(text, pattern):
    m = re.search(pattern, text)
    if m:
        # Use the exact matched string
        return m.group(0)
    return None

def extract_notice_kind(title, content):
    if re.search(r'\[[^\]]*수정[^\]]*\]|\[[^\]]*정정[^\]]*\]|\(수정\)|\(정정\)|수정\s*안내|정정\s*공고|정정\s*안내|수정\s*공지', title):
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
    terms = []
    evidence = []
    # Try title first, then content
    for text_src in [title, content]:
        if not text_src:
            continue
        # 1. 202X학년도 Y학기 / 202X-Y학기 / 202X년 Y학기
        m = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*([12])학기', text_src)
        if m:
            quote = m.group(0)
            terms.append({"year": int(m.group(1)), "semester": m.group(2)})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

        # 2. Summer semester
        m_summer = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*(?:여름|하계)\s*(?:계절)?\s*(?:학기|수업)?', text_src)
        if m_summer and any(w in m_summer.group(0) for w in ['여름', '하계']):
            quote = m_summer.group(0)
            terms.append({"year": int(m_summer.group(1)), "semester": "summer"})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

        # 3. Winter semester
        m_winter = re.search(r'(202[0-9])(?:학년도|-|년도|\s*년)?\s*(?:겨울|동계)\s*(?:계절)?\s*(?:학기|수업)?', text_src)
        if m_winter and any(w in m_winter.group(0) for w in ['겨울', '동계']):
            quote = m_winter.group(0)
            terms.append({"year": int(m_winter.group(1)), "semester": "winter"})
            evidence.append({"field": "terms", "quote": quote})
            return terms, evidence

    return terms, evidence

def extract_audience(title, content):
    candidates = ["학부생", "재학생", "신입생", "편입생", "졸업예정자", "휴학생", "복학생", "대학원생", "학기초과자", "외국인 유학생", "장애학생", "예비군"]
    found = []
    combined = title + " " + (content[:300] if content else "")
    for cand in candidates:
        if cand in combined:
            found.append(cand)
    return found

records = []
topic_counts = Counter()
status_counts = Counter()

for doc in notices:
    doc_id = doc['id']
    title = doc.get('title', '')
    content = doc.get('content', '') or ''
    source_hash = hashlib.sha256((title + "\n" + content).encode('utf-8')).hexdigest()
    
    topics = []
    evidence_list = []
    
    # 1. Match from title
    for topic, pats in TITLE_TAXONOMY:
        for pat in pats:
            q = extract_exact_quote(title, pat)
            if q and topic not in topics:
                topics.append(topic)
                evidence_list.append({"field": f"topics.{topic}", "quote": q})
                break
        if len(topics) >= 2:
            break
            
    # 2. If no title match, match from content
    if not topics and content:
        for topic, pats in BODY_TAXONOMY:
            for pat in pats:
                q = extract_exact_quote(content[:1500], pat)
                if q and topic not in topics:
                    topics.append(topic)
                    evidence_list.append({"field": f"topics.{topic}", "quote": q})
                    break
            if len(topics) >= 2:
                break
                
    # 3. If still no match, check OTHER
    if not topics:
        full_text = title + " " + content[:1000]
        other_q = None
        for ow in OTHER_KEYWORDS:
            if ow in full_text:
                other_q = ow
                break
        if other_q:
            topics = ["OTHER"]
            evidence_list.append({"field": "topics.OTHER", "quote": other_q})
            status = "tagged"
        else:
            topics = ["UNCLASSIFIED"]
            evidence_list = []
            status = "unclassified"
    else:
        status = "tagged"
        
    # Cap topics to 3 max
    topics = topics[:3]
    
    # Extract terms
    terms, term_ev = extract_terms(title, content)
    evidence_list.extend(term_ev)
    
    # Extract audience
    audience = extract_audience(title, content)
    
    # Extract notice kind
    notice_kind = extract_notice_kind(title, content)
    
    rec = {
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
    records.append(rec)
    for t in topics:
        topic_counts[t] += 1
    status_counts[status] += 1

# Validate every single record
errors = []
notice_map = {d['id']: d for d in notices}

for i, r in enumerate(records):
    orig = notice_map.get(r['doc_id'])
    if not orig:
        errors.append(f"Record {i}: doc_id {r['doc_id']} not found in notices")
        continue
    # Check hash
    exp_hash = hashlib.sha256((orig['title'] + "\n" + (orig.get('content') or '')).encode('utf-8')).hexdigest()
    if r['source_hash'] != exp_hash:
        errors.append(f"Record {i}: hash mismatch")
    # Check topics
    if not (1 <= len(r['topics']) <= 3):
        errors.append(f"Record {i}: topics length {len(r['topics'])} not in 1..3")
    if "OTHER" in r['topics'] and len(r['topics']) > 1:
        errors.append(f"Record {i}: OTHER is not standalone")
    if "UNCLASSIFIED" in r['topics'] and len(r['topics']) > 1:
        errors.append(f"Record {i}: UNCLASSIFIED is not standalone")
    # Check quotes exist literally in title or content
    title = orig['title']
    content = orig.get('content') or ''
    for ev in r['evidence']:
        q = ev['quote']
        if q not in title and q not in content:
            errors.append(f"Record {i} ({orig['id']}): quote '{q}' not found in title/content")

print(f"Validation finished. Total errors: {len(errors)}")
if errors:
    for e in errors[:10]:
        print("  Error:", e)
else:
    print("All records perfectly validated against source texts!")
    # Save to notice_tags.jsonl
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"Saved {len(records)} lines to {OUTPUT_PATH}")

print("\n--- Summary ---")
print("Total records:", len(records))
print("Topic counts:", topic_counts)
print("Status counts:", status_counts)
