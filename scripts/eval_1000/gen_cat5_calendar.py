# -*- coding: utf-8 -*-
"""
Generate Category 5: 학사일정 (200 items: CAL-0001 ~ CAL-0200)
Quota:
  dev: 160 (single: 112, multi: 24, abstain: 24)
  test: 40 (single: 28, multi: 6, abstain: 6)
Total: 200 items
"""
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from build_dataset_engine import (
    DOC_BY_ID,
    DOC_BY_URL,
    check_quote_in_doc,
    build_single,
    build_multi,
    build_abstain,
    snapshot
)

def parse_events(doc):
    lines = [l.strip() for l in doc['content'].split('\n') if l.strip()]
    norm = ' '.join(doc['content'].split())
    events = []
    i = 0
    seen = set()
    while i < len(lines):
        l = lines[i]
        if re.match(r'^\d{4}\.\d{2}\.\d{2}', l):
            if i + 2 < len(lines) and lines[i+1] == '~' and re.match(r'^\d{4}\.\d{2}\.\d{2}', lines[i+2]):
                dt = f"{lines[i]} ~ {lines[i+2]}"
                name = lines[i+3] if i + 3 < len(lines) else ""
                target = f"{dt} {name}"
                if target in norm and target not in seen and name:
                    events.append((dt, name, target))
                    seen.add(target)
                i += 4
            else:
                dt = lines[i]
                name = lines[i+1] if i + 1 < len(lines) else ""
                target = f"{dt} {name}"
                if target in norm and target not in seen and name:
                    events.append((dt, name, target))
                    seen.add(target)
                i += 2
        else:
            i += 1
    return events

def generate_cal_all():
    d6096 = next(d for d in snapshot if '6096' in d['url'])
    d6097 = next(d for d in snapshot if '6097' in d['url'])

    events_ug = parse_events(d6096)
    events_grad = parse_events(d6097)

    items = []
    cur_id = 1

    # 1. DEV SINGLE: 112 items (CAL-0001 ~ CAL-0112)
    # 56 from ug, 56 from grad
    for idx in range(56):
        dt, name, target = events_ug[idx]
        m_num = int(re.search(r'\d{4}\.(\d{2})', dt).group(1))
        fam = f"dev-cal-ug-s{idx+1}"
        q = f"2026학년도 학부 학사일정 중 {m_num}월에 진행되는 '{name}' 일정(일자 또는 기간)은 언제야?"
        a = f"2026학년도 학부 학사일정상 {m_num}월의 '{name}' 일정은 {dt}이다."
        items.append(build_single(f"CAL-{cur_id:04d}", "학사일정", "dev", fam, q, a, d6096['id'], f"학부 {name} 일정", target))
        cur_id += 1

    for idx in range(56):
        dt, name, target = events_grad[idx]
        m_num = int(re.search(r'\d{4}\.(\d{2})', dt).group(1))
        fam = f"dev-cal-grad-s{idx+1}"
        q = f"2026학년도 대학원 학사일정 중 {m_num}월에 진행되는 '{name}' 일정(일자 또는 기간)은 언제야?"
        a = f"2026학년도 대학원 학사일정상 {m_num}월의 '{name}' 일정은 {dt}이다."
        items.append(build_single(f"CAL-{cur_id:04d}", "학사일정", "dev", fam, q, a, d6097['id'], f"대학원 {name} 일정", target))
        cur_id += 1

    assert cur_id == 113, f"Expected cur_id 113 after dev single, got {cur_id}"

    # 2. DEV MULTI: 24 items (CAL-0113 ~ CAL-0136)
    # Pair ug and grad events (2 distinct URLs)
    for m_idx in range(24):
        ug_dt, ug_name, ug_tgt = events_ug[m_idx]
        grad_dt, grad_name, grad_tgt = events_grad[m_idx]
        m_ug = int(re.search(r'\d{4}\.(\d{2})', ug_dt).group(1))
        m_grad = int(re.search(r'\d{4}\.(\d{2})', grad_dt).group(1))
        fam = f"dev-cal-multi-{m_idx+1}"
        q = f"2026학년도 학부 {m_ug}월 '{ug_name}' 일정과 대학원 {m_grad}월 '{grad_name}' 일정을 각각 알려줘."
        a = f"2026학년도 학부 '{ug_name}' 일정은 {ug_dt}이며, 대학원 '{grad_name}' 일정은 {grad_dt}이다."
        evs = [
            (d6096['id'], f"학부 {ug_name}", ug_tgt),
            (d6097['id'], f"대학원 {grad_name}", grad_tgt)
        ]
        items.append(build_multi(f"CAL-{cur_id:04d}", "학사일정", "dev", fam, q, a, evs))
        cur_id += 1

    assert cur_id == 137, f"Expected cur_id 137 after dev multi, got {cur_id}"

    # 3. DEV ABSTAIN: 24 items (CAL-0137 ~ CAL-0160)
    dev_abstains = [
        ("dev-cal-abs-1", "2029학년도 1학기 개강일과 종강일이 각각 며칠인지 알려줘.", "2029학년도 학사일정 정보는 등록되어 있지 않다고 밝힌다."),
        ("dev-cal-abs-2", "2028학년도 2학기 수강신청 정정 기간을 알려줘.", "2028학년도 학사일정 정보는 안내되어 있지 않다고 밝힌다."),
        ("dev-cal-abs-3", "2030학년도 전기 학위수여식 날짜를 알려줘.", "2030학년도 학위수여식 일정은 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-4", "2027학년도 2학기 중간고사 및 기말고사 시작 일정을 알려줘.", "2027학년도 시험 일정은 안내되어 있지 않다고 밝힌다."),
        ("dev-cal-abs-5", "2029학년도 동계 계절학기 개강 일자가 언제인지 알려줘.", "2029학년도 계절학기 일정 정보는 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-6", "2028학년도 하계방학 시작일과 종료일을 알려줘.", "2028학년도 방학 일정 정보는 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-7", "서울대학교 2026학년도 1학기 개강일과 수강신청 기간을 알려줘.", "타대학의 학사일정 정보는 한성대학교 학사정보에서 제공하지 않는다고 밝힌다."),
        ("dev-cal-abs-8", "연세대학교 2026학년도 2학기 기말고사 일정을 알려줘.", "타대학 학사일정은 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-9", "고려대학교 2026학년도 전반기 입학식 일정을 알려줘.", "타대학 입학식 일정은 제공하지 않는다고 밝힌다."),
        ("dev-cal-abs-10", "내 개인 구글 캘린더에 등록된 이번 주 팀프로젝트 회의 일정을 조회해줘.", "학생 개인의 외부 캘린더 일정은 연동 및 조회할 수 없다고 밝힌다."),
        ("dev-cal-abs-11", "내 포털 개인 시간표에서 매주 화요일 수업이 끝나는 정확한 시간을 알려줘.", "학생 개인의 시간표 정보는 조회할 수 없다고 밝힌다."),
        ("dev-cal-abs-12", "2026학년도 2학기 중간고사 컴퓨터공학부 3학년 전공시험 고사장 건물 및 좌석번호를 알려줘.", "개인별 세부 고사장 좌석번호는 학사일정 공지에서 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-13", "2026학년도 1학기 기말고사 전공과목별 분반별 상세 시험감독 교수 명단을 알려줘.", "과목별 시험감독 교수 배정 명단은 학사일정 안내에 포함되어 있지 않다고 밝힌다."),
        ("dev-cal-abs-14", "2027학년도 트랙선택 신청 기간 일정을 미리 알려줘.", "2027학년도 트랙선택 세부 일정은 아직 공지되지 않았다고 밝힌다."),
        ("dev-cal-abs-15", "2028학년도 대학원 학·석사연계과정생 모집 일정을 알려줘.", "2028학년도 대학원 모집 일정은 제공되지 않는다고 밝힌다."),
        ("dev-cal-abs-16", "성균관대학교 2026학년도 학사일정상 여름방학 시작일을 알려줘.", "타대학 학사일정은 제공하지 않는다고 밝힌다."),
        ("dev-cal-abs-17", "내 학생 계정의 이번 학기 공강 요일이 언제인지 알려줘.", "개별 학생의 수강 시간표상 공강 정보는 조회할 수 없다고 밝힌다."),
        ("dev-cal-abs-18", "2026학년도 대동제 축제 3일차 연예인 초청공연 상세 타임테이블과 순서를 알려줘.", "축제 연예인 공연 상세 순서 및 시간표는 학사일정 정보에 없다고 밝힌다."),
        ("dev-cal-abs-19", "2029학년도 1학기 등록금 분할납부 1차 납부 기간을 알려줘.", "2029학년도 분할납부 일정은 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-20", "2028학년도 일반 전과 신청 기간을 알려줘.", "2028학년도 전과 신청 일정은 공지되지 않았다고 밝힌다."),
        ("dev-cal-abs-21", "2030학년도 하계 상상더학기 개강일을 알려줘.", "2030학년도 상상더학기 개강 일정은 확인할 수 없다고 밝힌다."),
        ("dev-cal-abs-22", "경희대학교 2026학년도 2학기 개강일을 알려줘.", "타대학 학사일정 정보는 제공하지 않는다고 밝힌다."),
        ("dev-cal-abs-23", "이번 주말 한성대 중앙도서관 4층 열람실의 개인 좌석 배정 현황을 알려줘.", "도서관 실시간 열람실 좌석 배정 현황은 조회할 수 없다고 밝힌다."),
        ("dev-cal-abs-24", "2029학년도 조기졸업 신청 기간이 언제인지 알려줘.", "2029학년도 조기졸업 신청 일정은 공지되어 있지 않다고 밝힌다."),
    ]
    for fam, q, a in dev_abstains:
        items.append(build_abstain(f"CAL-{cur_id:04d}", "학사일정", "dev", fam, q, a))
        cur_id += 1

    assert cur_id == 161, f"Expected cur_id 161 after dev abstain, got {cur_id}"

    # 4. TEST SINGLE: 28 items (CAL-0161 ~ CAL-0188)
    # 14 from remaining ug events (indices 56..69), 14 from remaining grad events (indices 56..69)
    for idx in range(56, 70):
        dt, name, target = events_ug[idx]
        m_num = int(re.search(r'\d{4}\.(\d{2})', dt).group(1))
        fam = f"test-cal-ug-s{idx+1}"
        q = f"2026학년도 학부 {m_num}월 학사일정에서 '{name}' 일자는 언제로 예정되어 있어?"
        a = f"2026학년도 학부 학사일정상 {m_num}월 '{name}' 일자는 {dt}이다."
        items.append(build_single(f"CAL-{cur_id:04d}", "학사일정", "test", fam, q, a, d6096['id'], f"학부 {name} 일정", target))
        cur_id += 1

    for idx in range(56, 70):
        dt, name, target = events_grad[idx]
        m_num = int(re.search(r'\d{4}\.(\d{2})', dt).group(1))
        fam = f"test-cal-grad-s{idx+1}"
        q = f"2026학년도 대학원 {m_num}월 학사일정에서 '{name}' 일정은 언제로 지정되어 있어?"
        a = f"2026학년도 대학원 학사일정상 {m_num}월 '{name}' 일정은 {dt}이다."
        items.append(build_single(f"CAL-{cur_id:04d}", "학사일정", "test", fam, q, a, d6097['id'], f"대학원 {name} 일정", target))
        cur_id += 1

    assert cur_id == 189, f"Expected cur_id 189 after test single, got {cur_id}"

    # 5. TEST MULTI: 6 items (CAL-0189 ~ CAL-0194)
    for m_idx in range(6):
        ug_dt, ug_name, ug_tgt = events_ug[56 + m_idx]
        grad_dt, grad_name, grad_tgt = events_grad[56 + m_idx]
        m_ug = int(re.search(r'\d{4}\.(\d{2})', ug_dt).group(1))
        m_grad = int(re.search(r'\d{4}\.(\d{2})', grad_dt).group(1))
        fam = f"test-cal-multi-{m_idx+1}"
        q = f"2026학년도 학부 {m_ug}월 '{ug_name}' 일정과 대학원 {m_grad}월 '{grad_name}' 일정을 함께 비교해서 알려줘."
        a = f"학부 '{ug_name}' 일정은 {ug_dt}이고, 대학원 '{grad_name}' 일정은 {grad_dt}이다."
        evs = [
            (d6096['id'], f"학부 {ug_name}", ug_tgt),
            (d6097['id'], f"대학원 {grad_name}", grad_tgt)
        ]
        items.append(build_multi(f"CAL-{cur_id:04d}", "학사일정", "test", fam, q, a, evs))
        cur_id += 1

    assert cur_id == 195, f"Expected cur_id 195 after test multi, got {cur_id}"

    # 6. TEST ABSTAIN: 6 items (CAL-0195 ~ CAL-0200)
    test_abstains = [
        ("test-cal-abs-1", "2031학년도 1학기 개강일과 입학식 일정을 알려줘.", "2031학년도 학사일정 정보는 안내되어 있지 않다고 밝힌다."),
        ("test-cal-abs-2", "한양대학교 2026학년도 1학기 중간고사 기간을 알려줘.", "타대학 학사일정은 제공하지 않는다고 밝힌다."),
        ("test-cal-abs-3", "내 개인 포털 계정의 오늘 수강 과목 출석 체크 현황을 실시간으로 조회해줘.", "개인별 실시간 전자출결 상태는 대리 조회할 수 없다고 밝힌다."),
        ("test-cal-abs-4", "2028학년도 대학원 석·박사학위논문 심사 신청 일정을 알려줘.", "2028학년도 대학원 심사 일정은 아직 공지되지 않았다고 밝힌다."),
        ("test-cal-abs-5", "2032학년도 학사일정 전체 목록을 알려줘.", "2032학년도 학사일정 정보는 등록되어 있지 않다고 밝힌다."),
        ("test-cal-abs-6", "중앙대학교 2026학년도 후기 학위수여식 날짜를 알려줘.", "타대학 학위수여식 일정은 확인할 수 없다고 밝힌다."),
    ]
    for fam, q, a in test_abstains:
        items.append(build_abstain(f"CAL-{cur_id:04d}", "학사일정", "test", fam, q, a))
        cur_id += 1

    assert cur_id == 201, f"Expected cur_id 201 at completion, got {cur_id}"
    return items

if __name__ == "__main__":
    items = generate_cal_all()
    print(f"Generated {len(items)} calendar items.")
    dev_items = [it for it in items if it['split'] == 'dev']
    test_items = [it for it in items if it['split'] == 'test']
    print(f"Dev: {len(dev_items)}, Test: {len(test_items)}")
    dev_fams = set(x['family_id'] for x in dev_items)
    test_fams = set(x['family_id'] for x in test_items)
    leak = dev_fams & test_fams
    print(f"Family leak count: {len(leak)}")
    assert len(leak) == 0, f"Leak detected: {leak}"
    print("Calendar category generator validated successfully!")
