# CampusMate 마일스톤 repair3 수정 및 최종 검증 보고서

**작성 일시**: 2026-09-25  
**검증자**: Gemini (Antigravity Agent)  
**참조 보고서**: `docs/codex_milestone_repair2_review_20260925.md`  
**목표**: 잔여 3대 결함(A, B, C)의 근본적 해결, 신규 기능 확장 배제, 계약 및 데이터 무결성 보존.

---

## 1. 개요 및 요약

`docs/codex_milestone_repair2_review_20260925.md`에서 보류 판정의 사유로 지적된 3대 결함(**A**: 추출 엔진 전 분기 공통 검증 누락, **B**: 근거 없는 기본 시각 및 하드코딩 업무명 생성, **C**: `ScheduleEditModal`에서 시작/종료 개별 수정 시 반대편 마이크로초 정밀도 손실)을 전면 수정하고 실증 검증을 완료하였습니다.

| 결함 항목 | 핵심 원인 | 조치 및 해결 내용 | 검증 결과 |
| :--- | :--- | :--- | :--- |
| **A (P1)**: 전 분기 공통 검증 누락 | 취소, 휴업일, 기간, 선착순 등 일부 분기가 `_check_calendar_validity` 없이 원시 파싱값을 반환하거나 모호 플래그만 설정 후 잘못된 날짜 문자열 유지 | 추출 엔진의 모든 규칙(Rule 1~20) 반환 경로를 단일 게이트인 `_build_response` -> `_validate_and_normalize_candidates` 파이프라인으로 통합. 실제 달력 날짜(윤년 등), 시각 범위(00:00~23:59), 시작<=종료 기간 순서, 명시적 연도(2027 등) 보존 강제. 오류값은 확정 일시 필드에서 완전 null 클리어 및 `unconfirmed_fields` 명시 | **해결 완료** (회귀 31건 전수 PASS) |
| **B (P1)**: 시각 날조 및 업무명 하드코딩 | 마감 시각 미매칭 시 17:30(분리 문장), 15:00(연장) 강제 주입 및 "제3전공 이수신청" 고정 제목 사용 | 하드코딩 시각 기본값(17:30, 15:00 등)과 고정 제목을 코드베이스에서 영구 제거. 원문에서 시각이 확인되지 않으면 날짜 전용 또는 미확정(`end_datetime=None`, `is_time_confirmed=False`)으로 처리. 제목은 원문 문맥 기반 동적 추출 적용 | **해결 완료** (반례 전수 PASS) |
| **C (P2)**: 한쪽 시각 수정 시 반대편 정밀도 손실 | `ScheduleEditModal`에서 `isDateOrKindModified`로 시작과 종료를 통합 감지하여, 한쪽만 수정해도 양쪽 모두를 분 단위 UI 값으로 직렬화 전송 | 시작(`isStartModified`)과 종료(`isEndModified`) 필드 변경 감지를 완전 독립화. 유형이 같을 때 미수정된 쪽은 PATCH payload에서 완전히 OMIT하여 DB의 원본 UTC 문자열 및 마이크로초(`.123456Z`)를 byte-for-byte 보존. 유형 변경 시에만 전수 재구성 및 null 정리 | **해결 완료** (Playwright 실 브라우저 E2E PASS) |

---

## 2. 결함별 상세 수정 내용 및 반례 검증

### 2.1 결함 A: 모든 추출 분기에 공통 검증/정규화 게이트 적용

#### 수정 내용
- **파일**: [`backend/schedules/extraction.py`](file:///Users/jwlee/study1/aisw/backend/schedules/extraction.py)
- **통합 파이프라인 구조**:
  - `_validate_and_normalize_candidates(candidates, cleaned_text, ref_year, tz_str)`:
    1. **명시적 연도 보존**: 본문 및 발췌문에서 4자리 연도(`2027`, `2028` 등)가 감지된 경우 기준 연도(`ref_year`)로 오염되지 않도록 연도 필드 정밀 교정.
    2. **달력 날짜 유효성 검증**: 시작 및 종료 일시에 대해 `_validate_date_tuple(y, mo, d)`를 실행하여 2월 30일, 4월 31일, 윤년이 아닌 2월 29일 등의 존재하지 않는 달력 날짜 감지.
    3. **시각 범위 유효성 검증**: `_validate_time_tuple(h, mn)`를 실행하여 25:90, 24:00 등의 유효하지 않은 시각 감지.
    4. **기간 순서 검증 (시작 <= 종료)**: 시작 일시와 종료 일시가 모두 유효한 경우 `dt_start <= dt_end`를 검증하여 시작이 종료보다 늦은 순서 역전 오류 감지.
    5. **오류값 완전 격리 및 유보 처리**: 달력 날짜 오류, 시각 오류, 기간 역전 오류 발생 시, 잘못된 값이 확정 일시 필드(`start_date`, `end_date`, `start_datetime`, `end_datetime`)에 남아있지 않도록 모두 `None`으로 클리어하고, `is_ambiguous=True`, `is_time_confirmed=False`, `unconfirmed_fields` 및 `ambiguity_reason`에 구체적 사유 기재.
  - **전 반환 경로 강제 적용**: 규칙 1(취소), 규칙 2(자정), 규칙 3(당일 긴급), 규칙 4(분리 문장), 규칙 5(선착순), 규칙 6(매일 반복), 규칙 7(다단계), 규칙 8(연장), 규칙 9(말경), 규칙 10(과거 시점 배제), 규칙 11~19(상대 날짜, 요일 매칭, 단일 마감 등)의 모든 `return` 문을 `_build_response(...)`로 라우팅.

#### 반례 재현 및 검증 결과
[`tests/test_schedule_extraction.py`](file:///Users/jwlee/study1/aisw/tests/test_schedule_extraction.py) 내 `test_codex_round3_unified_validation_and_grounding_counterexamples` 테스트 함수를 작성하여 전수 검증:

1. **취소 분기 오류 입력**: `[취소공지] 2027년 2월 30일 25:90 세미나 행사가 취소되었습니다.`
   - 결과: `is_cancellation=True`, `action="cancel"`, `start_date=None, end_date=None, start_datetime=None, end_datetime=None`, `is_ambiguous=True`, `is_time_confirmed=False`, `unconfirmed_fields=["exact_date", "time"]` (정상 클리어 및 유보).
2. **취소 분기 정상 미래 연도 입력**: `[취소공지] 2027년 11월 20일 세미나 행사가 취소되었습니다.`
   - 결과: `start_date="2027-11-20"`, `is_ambiguous=False`, 2026년으로 덮어써지지 않고 2027년 정확 보존.
3. **기간 분기 시작일 오류 입력**: `신입생 오리엔테이션은 2026년 2월 30일 09:00부터 2026년 3월 5일 18:00까지 진행됩니다.`
   - 결과: `start_date=None, end_date=None, start_datetime=None, end_datetime=None`, `is_ambiguous=True`, `unconfirmed_fields=["exact_date"]`.
4. **기간 순서 역전 오류 입력**: `2026학년도 집중이수 기간은 2026년 11월 10일부터 2026년 11월 5일까지입니다.`
   - 결과: `start_date=None, end_date=None, start_datetime=None, end_datetime=None`, `is_ambiguous=True`, `unconfirmed_fields=["period_order"]`.
5. **휴업일 분기 날짜 오류 입력**: `2026년 2월 30일은 개교기념일로 전체 휴업일입니다.`
   - 결과: `start_date=None, end_date=None`, `is_ambiguous=True`, `unconfirmed_fields=["exact_date"]`.

---

### 2.2 결함 B: 근거 없는 시각 기본값(17:30, 15:00) 및 고정 업무명 제거

#### 수정 내용
- **파일**: [`backend/schedules/extraction.py`](file:///Users/jwlee/study1/aisw/backend/schedules/extraction.py)
- **조치 내역**:
  1. 분리 문장 규칙(규칙 4)에서 시각이 매칭되지 않았을 때 주입되던 `17:30` 기본값을 삭제. 시각이 없으면 `start_datetime=None, end_datetime=None, is_time_confirmed=False, unconfirmed_fields=["start_time", "end_time"]`의 날짜 전용 기간 일정(`PERIOD_SCHEDULE`)으로 확정.
  2. 연장 마감 규칙(규칙 8)에서 시각이 매칭되지 않았을 때 주입되던 `15:00` 기본값을 삭제. 시각이 없으면 `start_datetime=None, end_datetime=None, is_time_confirmed=False, unconfirmed_fields=["time"]`의 날짜 전용 마감 일정(`DATE_ONLY_DEADLINE`)으로 확정.
  3. "제3전공 이수신청" 등 특정 업무명 하드코딩 제거: 원문 문맥(예: `[과제/신청/보고서 등]은 ...`)에서 접두사를 정규식으로 안전하게 추출하고, 추출 불가 시 중립적인 기본명(예: "일정 안내", "신청 마감")을 사용하도록 리팩터링.
  4. 후보 검증 게이트(Step 4)에서 `is_time_confirmed=True`로 반환되더라도 원문과 발췌문에 시각 표현(시각 포맷 `\d{1,2}:\d{2}`, `시/분`, `자정`, `오전/오후`)이 일절 존재하지 않으면 강제로 시각을 무효화하고 날짜 전용/미확정으로 전환하는 이중 안전망 구축.

#### 반례 재현 및 검증 결과
1. **입력**: `장학금 신청은 11월 1일부터 11월 5일까지이며 마감일에 전산 마감됩니다.`
   - **기존 (오류)**: 제목 "제3전공 이수신청", 종료 `2026-11-05T17:30:00+09:00`, `is_time_confirmed=True`.
   - **수정 후 (정상)**:
     - 제목: `"장학금 신청"` (동적 추출 성공)
     - `start_date`: `"2026-11-01"`, `end_date`: `"2026-11-05"`
     - `start_datetime`: `None`, `end_datetime`: `None` (17:30 날조 완전 배제)
     - `is_time_confirmed`: `False`, `unconfirmed_fields`: `["start_time", "end_time"]`
2. **입력**: `장학금 신청 마감일이 당초 11월 1일에서 11월 5일로 연장되었습니다.`
   - **기존 (오류)**: 종료 `2026-11-05T15:00:00+09:00`, `is_time_confirmed=True`.
   - **수정 후 (정상)**:
     - 제목: `"장학금 신청 마감(연장)"`
     - `end_date`: `"2026-11-05"`
     - `end_datetime`: `None` (15:00 날조 완전 배제)
     - `is_time_confirmed`: `False`, `unconfirmed_fields`: `["time"]`

---

### 2.3 결함 C: `ScheduleEditModal` 시작/종료 독립 변경 추적 및 정밀도 보존

#### 수정 내용
- **파일**: [`frontend-web/src/App.tsx`](file:///Users/jwlee/study1/aisw/frontend-web/src/App.tsx)
- **독립 변경 감지 로직**:
  ```typescript
  const isKindModified = scheduleKind !== initialKind;
  const isStartModified = startDate !== initialStartDate || startTime !== initialStartTime;
  const isEndModified = endDate !== initialEndDate || endTime !== initialEndTime;
  ```
- **선택적 PATCH 페이로드 전송 정책**:
  1. `isKindModified === true` (유형 변경 시):
     - 대상 `scheduleKind`의 스키마에 맞추어 필수 필드를 채우고, 불필요한 필드는 명시적으로 `null`로 세팅하여 백엔드 검증 통과.
  2. `isKindModified === false` (유형 유지 시):
     - `isStartModified === true`인 경우에만 `start_date` 및 `start_datetime`을 `patchPayload`에 추가.
     - `isStartModified === false`이면 `start_date` 및 `start_datetime`을 **일절 포함하지 않고 OMIT**.
     - `isEndModified === true`인 경우에만 `end_date` 및 `end_datetime`을 `patchPayload`에 추가.
     - `isEndModified === false`이면 `end_date` 및 `end_datetime`을 **일절 포함하지 않고 OMIT**.
  3. 백엔드 `ScheduleService.patch_schedule`는 미전송(OMIT)된 필드에 대해 기존 DB 레코드 값을 그대로 유지하므로, DB에 저장되어 있던 원본 UTC 문자열 및 마이크로초(`.123456Z`)가 단 1바이트의 오차도 없이 온전하게 보존됨.

#### 실제 Chromium Playwright E2E 검증 (`tests/test_browser_e2e.py`)
- **초기 DB 주입 상태**:
  - `start_datetime`: `2026-11-20T00:00:45.123456Z` (KST 09:00:45.123456)
  - `end_datetime`: `2026-11-20T01:00:55.654321Z` (KST 10:00:55.654321)
- **테스트 케이스 1: 제목만 수정 (Section 6)**
  - UI 입력: 제목을 `정밀 타임스탬프 원본 일정 [제목만수정]`으로 변경 후 저장.
  - DB 결과:
    - `start_datetime`: `2026-11-20T00:00:45.123456Z` (100% 동일)
    - `end_datetime`: `2026-11-20T01:00:55.654321Z` (100% 동일)
- **테스트 케이스 2: 종료 시각(endTime)만 10:00 -> 11:00 수정 (Section 6-B, Defect C 핵심)**
  - UI 입력: 시작 시각(09:00)은 그대로 두고, 종료 시각만 11:00으로 변경 후 저장.
  - DB 결과:
    - `start_datetime`: **`2026-11-20T00:00:45.123456Z` (마이크로초 .123456 byte-for-byte 완벽 보존!)**
    - `end_datetime`: `2026-11-20T02:00:00Z` (11:00 KST에 맞춰 정상 갱신)
- **테스트 케이스 3: 시작 시각(startTime)만 09:00 -> 08:00 수정 (Section 6-C)**
  - UI 입력: 시작 시각만 08:00으로 변경하고 종료 시각(11:00)은 유지 후 저장.
  - DB 결과:
    - `start_datetime`: `2026-11-19T23:00:00Z` (08:00 KST에 맞춰 정상 갱신)
    - `end_datetime`: `2026-11-20T02:00:00Z` (100% 동일 보존)

---

## 3. 검증 실행 명령어 및 전수 결과

### 3.1 9개 핵심 회귀 테스트 슈트 실행
```bash
.venv/bin/pytest tests/test_browser_e2e.py tests/test_ui_and_e2e_flow.py tests/test_schedule_extraction.py tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -v
```
- **실행 결과**:
  ```text
  ======================= 149 passed, 1 warning in 43.90s ========================
  ```
- **상세 내역**:
  - `tests/test_browser_e2e.py`: 1 passed (실제 Chromium 전체 수명주기 및 6-B/6-C 정밀도 보존 통과)
  - `tests/test_ui_and_e2e_flow.py`: 4 passed
  - `tests/test_schedule_extraction.py`: 31 passed (23개 픽스처 + 재검수 반례 8건 전수 통과)
  - `tests/test_schedules.py`: 27 passed (5대 유형 CRUD, BOLA 격리, 엄격한 스키마 검증)
  - `tests/test_auth_persistence.py`: 14 passed
  - `tests/test_codex_round2_fixes.py`: 12 passed
  - `tests/test_codex_fixes.py`: 10 passed
  - `tests/test_retrieval_grounding.py`: 7 passed
  - `tests/test_date_parsing.py`: 43 passed

### 3.2 프론트엔드 프로덕션 빌드
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
  ✓ built in 300ms
  ```

### 3.3 RAG 로컬 데이터 10사례 전수 대조
```bash
.venv/bin/python scripts/verify_rag_eval_evidence.py
```
- **실행 결과**:
  ```text
  [PASS] SHA-256 Hash Verified.
  [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)
  ```

### 3.4 `data/` 디렉터리 SHA-256 무결성 검증 (940개 파일 전수)
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
- **결론**: 저장소 `data/` 내의 파일은 단 1비트도 변조되지 않았음이 완벽히 입증됨.

---

## 4. 명시적 한계 및 경계 사항 (Scope & Boundaries)

Codex 재검수 보고서의 지침에 따라 아래의 시스템 범위 및 한계를 가감 없이 명확히 기록합니다:

1. **RAG 본문 전달 범위의 한계**:
   - 현재 챗봇 응답에서 일정 추출 모달로 전달되는 본문은 전체 공지 원문이 아니며, **유사도 검색으로 색인된 첫 번째 청크의 최대 2,000자**입니다.
   - 단일 공지가 여러 청크로 분할되어 있고 마감 시각 표현이 2,000자 이후의 후속 청크나 첨부파일에만 존재하는 경우, 본문에 마감 시각이 포함되지 않아 날짜 전용 일정으로 추출되거나 추가 입력을 요구할 수 있습니다.
   - "전체 공지 원문 전수 전달"이 아니며, "검색 청크(최대 2,000자) 기반 추출"로 범위를 한정합니다.
2. **테스트 슈트 범위의 한계**:
   - 본 보고서에서 검증한 149개 테스트는 핵심 기능 회귀를 보장하기 위해 선별된 9개 주요 테스트 파일의 결과이며, 저장소 내의 전체 25개 테스트 파일 전체를 실행한 결과가 아닙니다.
3. **운영 알림(F7) 처리 상태**:
   - 카카오톡/SMS/이메일 등 외부 푸시를 통한 자동 일정 리마인더는 사용자 동의 없는 무단 발송 및 스팸 위험을 방지하기 위해 상용 운영 연동 단계로 보류/제안된 상태를 유지합니다.

---

## 5. 결론

- **결함 A (전 분기 공통 검증 게이트 통합)**: 20개 모든 규칙이 단일 검증 및 정규화 게이트를 통과하도록 구조화되어 2월 30일, 25:90, 시작>종료 등 무효값이 확정 일시 필드에 일절 남지 않도록 해결되었습니다.
- **결함 B (날조 기본값 및 고정 업무명 배제)**: 17:30, 15:00 및 제3전공 하드코딩이 완전히 제거되었으며, 원문에 시각이 없는 경우 날짜 전용/미확정으로 정직하게 표현됩니다.
- **결함 C (시작/종료 독립 변경 추적)**: 종료 시각만 수정할 때 시작 시각의 원본 UTC 문자열 및 마이크로초(`.123456Z`)가 100% byte-for-byte 보존됨을 실 브라우저 Playwright E2E로 증명하였습니다.
- 저장소 `data/` 940개 파일 무결성(SHA-256 일치), 백엔드 보안 계약(`extra="forbid"`, `confirmed=True`, BOLA 격리), 프론트엔드 Vite 프로덕션 빌드 통과를 모두 완료하였습니다.
