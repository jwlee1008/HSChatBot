# CampusMate 마일스톤 repair4 수정 및 최종 검증 보고서

**작성 일시**: 2026-09-25  
**검증자**: Gemini (Antigravity Agent)  
**참조 보고서**: `docs/codex_milestone_repair3_review_20260925.md`  
**목표**: 연도 보정 회귀 결함의 근본적 해결, 시작/종료 명시 연도 보존, 상대 날짜의 기준 시점 독립성 보장, 정상 원문 값 무결성 유지.

---

## 1. 개요 및 요약

`docs/codex_milestone_repair3_review_20260925.md`에서 지적된 유일한 잔여 P1 결함인 **`_validate_and_normalize_candidates`의 문서 첫 연도 치환으로 인한 연도 보정 회귀**를 완벽히 해결하였습니다. 기존에 해결 완료 판정을 받은 결함 B(시각 날조 및 하드코딩 업무명 제거), 결함 C(ScheduleEditModal 시작/종료 독립 변경 추적 및 마이크로초 정밀도 보존), 공통 날짜·시각 검증 체계는 100% 온전하게 유지되었습니다.

| 항목 | 문제점 원인 | 조치 및 해결 내용 | 검증 결과 |
| :--- | :--- | :--- | :--- |
| **연도 보정 회귀 (P1)** | `_validate_and_normalize_candidates`에서 문서/인용문에서 처음 발견한 4자리 연도를 모든 날짜 필드에 무조건 문자열 치환(`val.replace(ref_year, expected_year)`)하여, 이미 정상 파싱된 종료 연도(2026)를 2025로 덮어쓰거나, 무관한 사업 연도(2025)로 상대 날짜(오늘/내일)를 오염시킴 | 전역 연도 치환 로직(`explicit_doc_year`, `expected_year`, `val.replace(...)`)을 완전 제거. 시작/종료 각각의 날짜 표현에 명시된 연도를 독립 보존하고, 상대 날짜는 `reference_time` 기준으로만 계산. 연도 경계를 넘는 기간 일정(`12월 ~ 1월`)에서 종료 연도 생략 시 자연스러운 연도 롤오버(`y2 = y1 + 1 if m2 < m1 else y1`) 적용 | **해결 완료** (회귀 32건 전수 PASS, 8대 반례 전수 PASS) |

---

## 2. 연도 처리 수정 상세 내역

### 2.1 공통 게이트 전역 치환 로직 제거
- **파일**: [`backend/schedules/extraction.py`](file:///Users/jwlee/study1/aisw/backend/schedules/extraction.py)
- **제거된 로직**:
  - `_validate_and_normalize_candidates` 도입부에 존재하던 `explicit_doc_year` 추출 및 루프 내 `expected_year` 기반 문자열 치환 블록(`val.replace(str(ref_year), str(expected_year), 1)`)을 전면 삭제.
  - 공통 게이트는 **오류 검증(달력 날짜 유효성, 시각 범위, 기간 순서 `start <= end`, 시각 근거 도출 유무)**과 **오류값의 안전한 유보(`None` 클리어 및 `is_ambiguous=True`)** 역할에만 충실하도록 복원하였으며, 유효한 원문 파싱값을 임의로 변경하지 않도록 보장.

### 2.2 시작/종료 각각의 명시 연도 독립 보존
- 기간 일정(규칙 4, 5, 6, 8, 16, 17) 및 단일 마감(규칙 1, 2, 3, 10, 18, 19)은 각각의 정규식 매칭 그룹에서 시작 연도와 종료 연도를 독립적으로 파싱하여 보존합니다:
  - 예: `2025년 12월 30일 09:00부터 2026년 1월 5일 18:00까지`
    - 시작 연도: `m_per_time.group(1)` -> `2025`
    - 종료 연도: `m_per_time.group(5)` -> `2026`
    - 각각의 연도가 독립적으로 보존되어 `2025-12-30T09:00:00+09:00 ~ 2026-01-05T18:00:00+09:00`로 정확히 추출됨.

### 2.3 종료 연도 생략 시 문맥 기반 연도 롤오버 지원
- 종료 날짜에 연도가 명시되지 않았으나 12월에서 1월로 넘어가는 등 연도 경계를 넘는 경우(`m2 < m1`):
  - `y2 = int(m.group(end_year_idx)) if m.group(end_year_idx) else (y1 + 1 if m2 < m1 else y1)`
  - 규칙 4(분리 문장), 규칙 5(선착순), 규칙 6(매일 반복), 규칙 8(연장), 규칙 16(기간 시각 포함), 규칙 17(기간 시각 없음)에 적용하여, 종료 연도가 생략된 경우에도 시작>종료 순서 역전 오류 없이 정확하게 익년 1월로 추론.

### 2.4 상대 날짜의 기준 시점 독립성 보장
- `오늘`, `내일`, `이번 주 금요일`, `다음 주 월요일` 등 상대 날짜 표현은 본문 내에 출현하는 과거/미래 사업 연도(예: "2025년 사업 안내입니다.")와 완전히 격리되어, 오직 전달된 `reference_time`(미제공 시 기본 기준 시각)을 기준으로만 계산됩니다.

---

## 3. 8대 반례 및 검증 결과

[`tests/test_schedule_extraction.py`](file:///Users/jwlee/study1/aisw/tests/test_schedule_extraction.py)에 신규 테스트 함수 `test_codex_round4_year_handling_counterexamples`를 추가하여 전수 검증하였습니다. (기준 시점: `reference_time="2026-09-25T12:00:00+09:00"`)

| 번호 | 테스트 입력 텍스트 | 기대 결과 | 실제 추출 결과 | 판정 |
| :---: | :--- | :--- | :--- | :---: |
| **1** | 교육 기간은 2025년 12월 30일 09:00부터 2026년 1월 5일 18:00까지입니다. | 시작 `2025-12-30T09:00:00+09:00`<br>종료 `2026-01-05T18:00:00+09:00` | 시작 `2025-12-30T09:00:00+09:00`<br>종료 `2026-01-05T18:00:00+09:00` | **PASS** |
| **2** | 교육 기간은 2025년 12월 30일부터 2026년 1월 5일까지입니다. | 시작 `2025-12-30`<br>종료 `2026-01-05` | 시작 `2025-12-30`<br>종료 `2026-01-05` | **PASS** |
| **3** | 2025년 사업 안내입니다. 오늘 18시까지 장학금 신청서를 제출하세요. | 종료 `2026-09-25T18:00:00+09:00`<br>(2025년 사업 연도 미오염) | 종료 `2026-09-25T18:00:00+09:00`<br>(2026년 당일 정확 유지) | **PASS** |
| **4** | 2025년 사업 안내입니다. 내일 오후 2시에 장학금 설명회가 진행됩니다. | 시작 `2026-09-26T14:00:00+09:00`<br>(2025년 사업 연도 미오염) | 시작 `2026-09-26T14:00:00+09:00`<br>(2026년 익일 정확 유지) | **PASS** |
| **5** | 교육 기간은 2026년 12월 30일 09:00부터 2027년 1월 5일 18:00까지입니다. | 시작 `2026-12-30T09:00:00+09:00`<br>종료 `2027-01-05T18:00:00+09:00` | 시작 `2026-12-30T09:00:00+09:00`<br>종료 `2027-01-05T18:00:00+09:00` | **PASS** |
| **6** | 교육 기간은 2026년 12월 30일부터 2027년 1월 5일까지입니다. | 시작 `2026-12-30`<br>종료 `2027-01-05` | 시작 `2026-12-30`<br>종료 `2027-01-05` | **PASS** |
| **7** | 교육 기간은 2025년 12월 30일 09:00부터 1월 5일 18:00까지입니다. | 종료 연도 롤오버 추론:<br>시작 `2025-12-30T09:00:00+09:00`<br>종료 `2026-01-05T18:00:00+09:00` | 시작 `2025-12-30T09:00:00+09:00`<br>종료 `2026-01-05T18:00:00+09:00` | **PASS** |
| **8** | 행사 취소 안내: 2027년 11월 20일 14:00 예정되었던 음악회 행사는 취소되었습니다. | 기존 취소 명시 연도 보존:<br>`2027-11-20T14:00:00+09:00`<br>`action="cancel"` | `2027-11-20T14:00:00+09:00`<br>`is_cancellation=True` | **PASS** |

---

## 4. 실행 명령어 및 전수 결과

### 4.1 9개 핵심 회귀 테스트 슈트 실행
```bash
.venv/bin/pytest tests/test_browser_e2e.py tests/test_ui_and_e2e_flow.py tests/test_schedule_extraction.py tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -v
```
- **실행 결과**:
  ```text
  ======================= 150 passed, 1 warning in 46.40s ========================
  ```
- **상세 내역**:
  - `tests/test_browser_e2e.py`: 1 passed (Playwright 실제 Chromium E2E: 종료만 수정 시 시작 마이크로초 `.123456` 보존, 시작만 수정 시 종료 불변, 제목만 수정 시 양쪽 불변, 서울 자정 경계, 페이지네이션, 토큰 무효화 401 전수 통과)
  - `tests/test_ui_and_e2e_flow.py`: 4 passed
  - `tests/test_schedule_extraction.py`: 32 passed (23개 픽스처 전수 일치 + 재검수 반례 9건 전수 통과)
  - `tests/test_schedules.py`: 27 passed (5대 유형 CRUD, BOLA 격리, 엄격 스키마)
  - `tests/test_auth_persistence.py`: 14 passed
  - `tests/test_codex_round2_fixes.py`: 12 passed
  - `tests/test_codex_fixes.py`: 10 passed
  - `tests/test_retrieval_grounding.py`: 7 passed
  - `tests/test_date_parsing.py`: 43 passed

### 4.2 프론트엔드 프로덕션 빌드
```bash
npm run build --prefix frontend-web
```
- **실행 결과**:
  ```text
  vite v6.4.3 building for production...
  ✓ 27 modules transformed.
  dist/index.html                   1.00 kB │ gzip:  0.58 kB
  dist/assets/index-BamWOvKk.css   25.69 kB │ gzip:  5.74 kB
  dist/assets/index-BG7XO7t6.js   194.40 kB │ gzip: 58.26 kB
  ✓ built in 251ms
  ```

### 4.3 RAG 로컬 데이터 10사례 전수 대조
```bash
.venv/bin/python scripts/verify_rag_eval_evidence.py
```
- **실행 결과**:
  ```text
  [PASS] SHA-256 Hash Verified.
  [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)
  ```

### 4.4 `data/` 디렉터리 SHA-256 무결성 검증 (940개 파일 전수)
```bash
.venv/bin/python -c '
import os, hashlib
def hash_dir(path):
    h = hashlib.sha256()
    count = 0
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            with open(p, "rb") as fp:
                h.update(fp.read())
            count += 1
    return count, h.hexdigest()
c, d_hash = hash_dir("data")
print(f"data files: {c}, sha256: {d_hash}")
assert c == 940
assert d_hash == "7ce71284b38e1fb7c61539d1d96d4fb7ffb186d6f1c90d03cdcfca5d0bf4eba8"
print("[PASS] EXACT SHA-256 HASH MATCH!")
'
```
- **실행 결과**:
  ```text
  data files: 940, sha256: 7ce71284b38e1fb7c61539d1d96d4fb7ffb186d6f1c90d03cdcfca5d0bf4eba8
  [PASS] EXACT SHA-256 HASH MATCH!
  ```
- **결론**: 저장소 `data/` 940개 파일은 단 1비트도 변조되지 않았음이 완벽히 입증됨.

---

## 5. 남은 제한 및 경계 사항 (Scope & Limitations)

1. **RAG 본문 전달 범위**:
   - 챗봇 검색 결과에서 일정 추출 모달로 전달되는 본문은 **유사도 검색으로 색인된 첫 청크의 최대 2,000자**입니다.
   - 공지 전체 원문이 2,000자를 초과하고 마감 시각이 후속 청크나 별도 첨부파일에만 존재하는 경우, 본문에 마감 시각이 포함되지 않아 날짜 전용 일정으로 추출되거나 추가 입력을 요구할 수 있습니다.
2. **테스트 슈트 범위**:
   - 실행된 150개 테스트는 핵심 기능 회귀를 보장하기 위해 선별된 9개 주요 테스트 파일의 결과이며, 저장소 전체(25개 테스트 파일) 대상이 아닙니다.
3. **운영 알림(F7) 처리 상태**:
   - 외부 알림 발송(카카오톡/SMS/이메일 등)은 상용 운영 인프라 연동, 알림 템플릿 심사, 발송 주기 및 사용자 동의 정책 등 구체적인 구현 및 범위 결정이 과제로 남아있어 제안/유보 상태를 유지합니다.
4. **Git 상태**:
   - `git commit` 및 `git push`는 일절 실행하지 않았습니다.
