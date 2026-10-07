#!/usr/bin/env python3
"""
scripts/verify_rag_eval_evidence.py

R0 RAG 평가 기준선 대표 10사례의 로컬 데이터 근거 전수 대조 검증 스크립트.
data/unified_campus_knowledge.json과의 ID, URL, 제목, 실제 원문 발췌 일치 여부 및
데이터셋 SHA-256 무결성을 읽기 전용으로 검증한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

DATA_PATH = Path("data/unified_campus_knowledge.json")
EXPECTED_SHA256 = "c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e"

# R0 대표 10사례 평가 근거 명세
EVAL_CASES = [
    {
        "case_id": "case-01",
        "category": "CAT-01 수강",
        "question": "수강신청 일정과 수강신청 후 정정 방법이 어떻게 돼?",
        "doc_id": "a13e7f186a30adc9b2f7883f02679e58a49e74b805e80d0320a7e709bb3fc93d",
        "url": "https://www.hansung.ac.kr/hansung/6225/subview.do",
        "title": "수강신청",
        "quotes": [
            "매학기 개강전 (2월, 8월 중순)",
            "한성대학교 종합정보시스템 > 교무 > 수강신청",
            "수강신청 후 종합정보시스템 > 교무 > 수강신청서를 통해 확인 가능",
            "2차 수강신청 정정기간 및 수강신청 포기기간 이후에는 반드시 수강 신청 내역을 확인 해야 함",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "상시 안내 문서, 정확한 원문 일치",
    },
    {
        "case_id": "case-02",
        "category": "CAT-02 장학",
        "question": "2026년 2학기 국가장학금 2차 신청 마감일이랑 가구원 동의 마감일이 같아?",
        "doc_id": "bdda8c56bb23a38e3266b27b5901e2a043b4db2cb37bc3748666a8fe7271e9d4",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/223971/artclView.do",
        "title": "국가장학금\n2026년 2학기 국가장학금 2차 신청 안내",
        "quotes": [
            "'26.8.12.(수) 09시~9.9.(수) 18시",
            "서류제출 및 가구원 동의",
            "26.8.12.(수) 09시~9.16.(수) 184]",
        ],
        "content_status": "ocr",
        "review_status": "NEEDS_REVIEW_FOR_TIME",
        "notes": "포스터 OCR 본문. 9/9 vs 9/16 날짜 구분은 확정 평가; 184] 시각 표기는 수기 이미지 대조 전까지 채점 제외",
    },
    {
        "case_id": "case-03",
        "category": "CAT-03 졸업",
        "question": "학사학위취득유예(졸업유예) 신청 자격이 어떻게 되나요?",
        "doc_id": "f16516639046a6dbcf85d538fdada707cfa4ee3e84a249b4b44303e76a018fcd",
        "url": "https://www.hansung.ac.kr/hansung/6237/subview.do",
        "title": "졸업유예(학사학위취득유예)",
        "quotes": [
            "유예 신청자격은 신청하는 학기에 8학기 이상 등록하고 졸업학점과 전공 졸업요건을 모두 충족 예정인 학생이어야 함. 단, 외국인 유학생은 유예신청을 할 수 없음.",
            "수료자, 조기졸업 신청자, 외국인유학생은 졸업유예 신청 불가 / 편입생은 졸업유예 신청 가능",
            "유예 신청은 학기 단위로 신청하면 최대 2개 학기(1년)까지 신청/승인 가능함.",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "상시 안내(6237). 8학기 이상, 최대 2학기, 외국인/수료자/조기졸업 신청자 불가 제약",
    },
    {
        "case_id": "case-04",
        "category": "CAT-04 휴복학",
        "question": "일반휴학은 한 번에 몇 학기까지 가능하고 통산 몇 학기까지 휴학할 수 있어?",
        "doc_id": "57ff96ebbafdcc71acea368b70bcf6a6a304f4207718dfefd7c92ce75b12fb7b",
        "url": "https://www.hansung.ac.kr/hansung/6248/subview.do",
        "title": "휴학",
        "quotes": [
            "휴학은 재학기간중 통산",
            "3년(6학기) 가능(군휴학기간 제외)하며",
            "1회에 1학기, 혹은 2학기 휴학할 수 있다.",
            "신입생 은 병역 또는 질병에 의한 경우 이외에는 입학 년도의 휴학을 할 수 없다.",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "상시 안내(6248). 1회 1~2학기, 통산 3년(6학기), 신입생 첫해 제한. 공백 정규화 적용",
    },
    {
        "case_id": "case-05",
        "category": "CAT-05 시설",
        "question": "상상파크 기자재와 코딩라운지 세미나실은 어떻게 예약하고 이용시간이 어떻게 돼?",
        "doc_id": "002c45a581276fc882ccebe30204c976f2cac668efbd727ba16ac05672a2564f",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2148/artclList.do?page=1",
        "title": "시설·기자재이용 상상파크·상상파크플러스·코딩라운지는 어떻게 이용하나요?",
        "quotes": [
            "상상파크 기자재 및 상상파크플러스·코딩라운지 공간은 사전 예약 후 이용할 수 있습니다.",
            "스마트융합교육센터 홈페이지에서 원하는 시설 및 이용 시간을 선택하여 예약할 수 있습니다.",
            "학기 중 : 09:00 ~ 21:00",
            "방학 중 : 10:00 ~ 16:00",
            "- 기자재 및 공간 이용 시 실물 신분증을 지참하여 안내데스크로 방문해 주세요",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "FAQ 전용 게시물 ID(002c45a5...) 정정 완료. 5개 발췌 전수 일치",
    },
    {
        "case_id": "case-06",
        "category": "CAT-06 약어",
        "question": "제26회 TOPCIT 정기평가 한성대 단체접수 마감일과 보증금, 응시료 지원 조건이 뭐야?",
        "doc_id": "7315051911dd61481bf87fa8f2347f5b01e7be395623a44d9e41bdd14fa5d308",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224626/artclView.do",
        "title": "한성공지\n★기간연장:~9.9.(수)★[SW중심] 제26회 TOPCIT(소프트웨어 역량검정 시험) 정기평가 시행 안내",
        "quotes": [
            "9. 4.(금) ~ 9. 9.(수) 24:00까지 ※접수기간연장",
            "- 보증금: 20,000원",
            "- 보증금 현금 20,000원 납부하여야 정상 접수됨(실제 응시한 학생에 한하여 납부된 보증금은 시험 종료 후 7일 이내 환급)",
            "★ 사업단을 통하여 응시했을 경우 참여 혜택 ★",
            "4) 응시료 전액 지원 (10,000원)",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "보증금 20,000원과 응시료 10,000원 전액 지원 엄격 분리 완료",
    },
    {
        "case_id": "case-07",
        "category": "CAT-08 충돌",
        "question": "2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간이 언제야?",
        "doc_id": "1a676b27ed5c8142545bbfb02958d03031276fbb0f5491a7264b47471e598ae1",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224562/artclView.do",
        "title": "한성공지\n2026학년도 2학기 전공(트랙)연계 협업형 진로·취업멘토링 참가자 모집 안내 (9.10.목~6.11.목 15:00)",
        "quotes": [
            "2026학년도 2학기 전공(트랙)연계 협업형 진로·취업멘토링 참가자 모집 안내 (9.10.목~6.11.목 15:00)",
            "2. 신청 기간: 2026. 09. 10.(목) ~ 2026. 09. 17.(목) 15:00까지",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "본문 9.17 15:00 정답, 제목 6.11 답변 시 FAIL, 제목/본문 충돌 안내 필수",
    },
    {
        "case_id": "case-08",
        "category": "CAT-08 제약",
        "question": "편입생 전적대학 학점 재인정 신청 대상자가 누구야?",
        "doc_id": "e8ef6be49a4035bf045418f414546e2acf10952f2e134f168183eed0d8c10864",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224588/artclView.do",
        "title": "한성공지\n편입생 전적대학 학점 재(추가)인정 신청 안내",
        "quotes": [
            "1. 대상자 : 일반편입생(외국인 유학생 제외) 중 전적대학 학점 추가인정 또는 재인정 신청 대상자",
            "2. 신청 접수 기간 : 2026. 9. 10.(목) 10:00 ∼ 9. 18.(금) 17:00",
        ],
        "content_status": "text",
        "review_status": "VERIFIED",
        "notes": "원문 문장 정확 복사 완료. 외국인 유학생 제외 제약 필수",
    },
    {
        "case_id": "case-09",
        "category": "CAT-09 미확보",
        "question": "2026년 2학기 푸른등대 기부장학금 신규 선발 자격과 세부 기준이 어떻게 돼?",
        "doc_id": "aa68cba782916d8ad17285242d26f87026b07a32b3065988656851b9b5bc044e",
        "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224477/artclView.do",
        "title": "국가장학금\n2026년 2학기 푸른등대 기부장학금 신규장학생 선발 안내",
        "quotes": [
            "2026년 2학기 푸른등대 기부장학금 신규장학생 선발 안내",
        ],
        "content_status": "title_only",
        "review_status": "VERIFIED",
        "notes": "본문 미확보(빈 문자열). 허위 요건 생성 방지 및 공지 링크 유보 안내",
    },
    {
        "case_id": "case-10",
        "category": "CAT-05 부재",
        "question": "상상빌리지(기숙사) 이번 주(기준 시점: 2026-09-23T15:00:00+09:00 주간) 화요일 점심 메뉴가 뭐야?",
        "doc_id": None,
        "url": None,
        "title": None,
        "quotes": [],
        "content_status": "uncollected",
        "review_status": "UNCOLLECTED_ABSTAIN",
        "notes": "상상빌리지 및 해당 주 식단 데이터 미확보. 임의 메뉴 생성 금지(유보 안내 시 PASS)",
    },
]


def normalize_whitespace(text: str) -> str:
    """연속된 줄바꿈, 탭, 공백 및 비분리 공백(\\xa0)을 단일 공백으로 치환."""
    return re.sub(r"\s+", " ", text).strip()


def verify_all_cases() -> bool:
    print("=" * 72)
    print(" CampusMate RAG 대표 10사례 근거 전수 대조 검증 (Read-Only)")
    print("=" * 72)

    # 1. 파일 확인 및 SHA-256 검증
    if not DATA_PATH.exists():
        print(f"[FAIL] Data file not found: {DATA_PATH}")
        return False

    with open(DATA_PATH, "rb") as f:
        raw_bytes = f.read()
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    print(f"Data file: {DATA_PATH} ({len(raw_bytes):,} bytes)")
    print(f"Expected SHA-256: {EXPECTED_SHA256}")
    print(f"Actual   SHA-256: {actual_sha256}")

    if actual_sha256 != EXPECTED_SHA256:
        print("[FAIL] SHA-256 mismatch!")
        return False
    print("[PASS] SHA-256 Hash Verified.\n")

    # 2. 문서 로드 및 맵 구성
    dataset = json.loads(raw_bytes.decode("utf-8"))
    doc_map = {d["id"]: d for d in dataset}
    print(f"Loaded {len(doc_map):,} documents into memory.")
    print("-" * 72)

    overall_pass = True

    # 3. 10개 사례별 대조
    for case in EVAL_CASES:
        cid = case["case_id"]
        cat = case["category"]
        doc_id = case["doc_id"]

        print(f"\n[{cid}] {cat} - {case['question'][:42]}...")

        # 부재 사례(case-10) 처리
        if doc_id is None:
            if case["content_status"] == "uncollected" and case["review_status"] == "UNCOLLECTED_ABSTAIN":
                print("  - 근거 문서 상태: 미확보 (상상빌리지/해당 주 식단 정보 미확보)")
                print("  - 판정 정책: 조기 유보(Abstain) 시 PASS")
                print("  - [PASS] 미확보 사례 정의 정상 (허위 ID/URL 생성 없음)")
            else:
                print("  - [FAIL] 미확보 사례의 상태 지정 오류")
                overall_pass = False
            continue

        # 문서 존재 확인
        doc = doc_map.get(doc_id)
        if not doc:
            print(f"  - [FAIL] Document ID not found in dataset: {doc_id}")
            overall_pass = False
            continue

        # URL 일치 검증
        actual_url = doc.get("url")
        if actual_url != case["url"]:
            print(f"  - [FAIL] URL mismatch: expected={case['url']}, actual={actual_url}")
            overall_pass = False
        else:
            print(f"  - URL 일치: {actual_url}")

        # 제목 일치 검증 (포함 관계)
        actual_title = doc.get("title", "")
        expected_title_clean = normalize_whitespace(case["title"])
        actual_title_clean = normalize_whitespace(actual_title)
        if expected_title_clean not in actual_title_clean:
            print(f"  - [FAIL] Title mismatch: expected={case['title']!r}, actual={actual_title!r}")
            overall_pass = False
        else:
            print(f"  - 제목 일치: {normalize_whitespace(case['title'])[:35]}...")

        # 원문 발췌 포함 검증
        full_raw_text = actual_title + "\n" + doc.get("content", "")
        full_norm_text = normalize_whitespace(full_raw_text)

        all_quotes_found = True
        for quote in case["quotes"]:
            is_exact = quote in full_raw_text
            is_norm = normalize_whitespace(quote) in full_norm_text
            if is_exact:
                match_type = "정확 부분 문자열 (Exact Substring)"
            elif is_norm:
                match_type = "공백 정규화 일치 (Whitespace Normalized)"
            else:
                match_type = "불일치 (NOT FOUND)"
                all_quotes_found = False
                overall_pass = False

            disp_q = quote[:36] + ("..." if len(quote) > 36 else "")
            print(f"    * Quote: {disp_q!r} -> {match_type}")

        if all_quotes_found:
            print(f"  - [PASS] 모든 원문 발췌 검증 성공 ({len(case['quotes'])}개 발췌)")
        else:
            print(f"  - [FAIL] 원문 발췌 중 불일치 항목 존재")

    print("\n" + "=" * 72)
    if overall_pass:
        print(" [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)")
        print(" (자동 검사는 로컬 JSON과의 일치를 보증하며 원본 이미지의 OCR 정확도는 수기 대조 대상임)")
    else:
        print(" [최종 결과] 대표 10사례 검증 중 실패 항목 존재: FAIL")
    print("=" * 72)

    return overall_pass


if __name__ == "__main__":
    success = verify_all_cases()
    sys.exit(0 if success else 1)
