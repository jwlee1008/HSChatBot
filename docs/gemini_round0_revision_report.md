# CampusMate R0 수정 라운드 완료 보고서 (Gemini)

- **작성 일자:** 2026-09-23
- **작성자:** 구현 담당 (Gemini)
- **검수 수신:** 설계·검수 총괄 (Codex)
- **대상 검토 문서:** `docs/codex_round0_review.md` 및 `docs/gemini_round0_revision_prompt.md`

---

## 1. 지적사항별 수정 내역

### 1.1 [P1] 정답표 원문 대조 및 오류 수정 (`docs/campusmate_evaluation_baseline.md`)

로컬 지식 베이스 파일(`data/unified_campus_knowledge.json`, SHA-256: `c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e`)과 10대 대표 사례를 전수 재대조하여 사실과 다른 내용 및 추측성 서술을 정정하였습니다.

1. **사례 6 (TOPCIT 정기평가):**
   - **이전 오류:** 보증금을 '1만원'으로 기재.
   - **원문 대조 결과:** 공지 224626 (ID: `7315051911dd61481bf87fa8f2347f5b01e7be395623a44d9e41bdd14fa5d308`) 본문 확인.
   - **수정:** **보증금 현금 20,000원** (시험 응시 후 7일 이내 환급)과 **응시료 전액 지원 10,000원**을 명확히 분리하여 정답표에 반영.
2. **사례 3 (졸업유예/학사학위취득유예):**
   - **이전 오류:** 6234(일반 졸업안내)를 인용하고 원문에 없는 '건축학부 10학기' 등의 조건을 기재.
   - **원문 대조 결과:** 졸업유예 전용 안내 페이지인 6237 (ID: `f16516639046a6dbcf85d538fdada707cfa4ee3e84a249b4b44303e76a018fcd`, URL: `https://www.hansung.ac.kr/hansung/6237/subview.do`) 확인.
   - **수정:** 근거 URL을 6237로 바로잡고, 자격(8학기 이상 등록, 졸업요건 충족 예정), 신청 단위(학기 단위 최대 2개 학기), **제외 대상(외국인 유학생, 수료자, 조기졸업 신청자 불가 / 편입생 가능)**을 원문 그대로 반영. 미확인 조건은 완전 배제.
3. **사례 4 (휴학):**
   - **이전 오류:** 지정 페이지(6248)에 없는 '편입생 3학기 이내'를 예외 요건으로 기재.
   - **수정:** 6248 본문(ID: `57ff96ebbafdcc71acea368b70bcf6a6a304f4207718dfefd7c92ce75b12fb7b`)에 명시된 재학기간 통산 3년(6학기) 이내, 1회 1~2학기, 신입생 입학 첫해 휴학 불가 규정만 정확히 반영하고 편입생 예외 추정 삭제.
4. **사례 7 (진로·취업멘토링 일정 충돌):**
   - **이전 결함:** '과거 공지 오기', '본문 정정 이력' 등 원문에 없는 편집 배경을 단정.
   - **수정:** 제목의 일자 문자열`(9.10.목~6.11.목 15:00)`과 본문 2항의 `2026. 09. 10.(목) ~ 2026. 09. 17.(목) 15:00까지` 간의 날짜 충돌을 관찰된 사실로 기술하고, 본문 일자를 답변하되 제목 일자는 배제(negative constraint)하는 기준으로 정리.
5. **사례 2 (국가장학금 2차 신청 OCR 검수 메모):**
   - 로컬 본문이 포스터 이미지 OCR(`content_status: ocr`)로 추출되었으며, 서류제출 마감 시각 표기('18시' -> '184]') 등 OCR 노이즈가 존재함을 명시하고, 정확한 숫자 표기는 원문 이미지 대조 및 추가 검수가 필요함으로 기록.
6. **메타데이터 기록:**
   - 10개 대표 사례 전부에 실제 문서 ID, URL, 정확한 원문 발췌문, 입력 데이터 SHA-256을 완전 명시.

---

### 1.2 [P1] 사용자 확인 정책 준수 및 모호한 마감 처리 (`tests/fixtures/schedule_extraction_cases.json`)

1. **저장 전 사용자 확인 필수 정책 전면 적용:**
   - 정보의 모호함 여부와 무관하게, **모든 추출된 일정 후보는 개인 캘린더에 자동 저장되지 않고 사용자 확인을 거쳐야 한다**는 PRD 원칙을 반영.
   - 후보가 1건 이상 존재하는 모든 케이스(sched-01~16, 18~23)의 케이스 레벨 및 후보 레벨에 `requires_user_confirmation: true` 적용.
   - 후보가 0건인 상시 안내문(sched-17)만 `requires_user_confirmation: false` 유지.
2. **사용자 확인과 모호성 여부 분리:**
   - 각 후보 객체에 `is_ambiguous: bool`을 추가하여, 모호성이 없는 경우 `is_ambiguous: false, ambiguity_reason: null`, 모호한 경우 `is_ambiguous: true, ambiguity_reason: "..."`로 명확히 분리.
3. **sched-20 (자정 마감) 임의 타임스탬프 확정 금지:**
   - 모호한 "10월 9일 자정까지"에 대해 가공된 `2026-10-09T23:59:59+09:00`을 부여하지 않고, `end_date: null`, `is_time_confirmed: false`로 설정.
   - 추출된 날짜 표현(`extracted_date: "2026-10-09"`)은 보존하고, `interpretation_options: ["2026-10-09T23:59:59+09:00", "2026-10-09T00:00:00+09:00"]`으로 해석 후보를 분리 제공.
4. **sched-18 원문 발췌 보존:**
   - 생략 부호(`...`)가 포함된 재작성 문자열을 제거하고, 원문 본문에 실제로 존재하는 정확한 부분 문자열(`source_quote: "10월 26일부터 10월 28일까지"`, `source_quotes: ["10월 26일부터 10월 28일까지", "마감일 17:30에 전산 마감됩니다."]`)로 교체.
5. **취소 공지 사례 추가 (sched-23):**
   - "[취소공지] 9월 29일 14:00 예정되었던 총장과의 대화 행사는 교내 사정으로 취소되었습니다." 사례 신설 (`is_cancellation: true`, `action: "cancel"`).
   - 취소 공지가 추출되어도 기존 사용자 일정을 시스템이 임의로 자동 삭제하지 않으며, 사용자 확인 알림을 거쳐야 함(`requires_user_confirmation: true`)을 명시.
6. **Fixture 정합성 테스트 강화 (`tests/test_date_parsing.py`):**
   - 모든 후보의 `requires_user_confirmation: true` 필수 여부 검증.
   - 모든 `source_quote`가 원문 `input_text`의 실제 부분 문자열인지 전수 assertion 검증.
   - sched-20의 `end_date is None` 및 해석 선택지 제공 검증.
   - 취소 공지 사례 존재 및 확인 필수 정책 검증.

---

### 1.3 [P2] 날짜 파서 허용 범위 회귀 및 잘못된 입력 수용 (`scripts/build_unified_dataset.py`)

1. **잘못된 오프셋 분/시 엄격 거부:**
   - 오프셋 시(`00`~`23`) 및 분(`00`~`59`)에 대한 사전 유효성 검증 로직 추가.
   - `2026-09-23T15:00:00+09:99` (분 99), `2026-09-23T15:00:00-00:60` (분 60), `+24:00` (시 24), `+2500` 등을 `timedelta`에 의한 비정상 시간 정규화 없이 즉시 `None`으로 거부.
2. **혼합 구분자 엄격 거부:**
   - 하이픈 패턴(`_PATTERN_HYPHEN`)과 점 구분 패턴(`_PATTERN_DOT`)을 독립적인 정규식으로 분리.
   - `2026-09.23`, `2026.09-23` 등 하이픈과 점이 섞인 입력은 일절 매칭되지 않고 `None`을 반환하도록 차단.
3. **정상 ISO 입력 호환성 복원:**
   - 구분자 없는 기본 ISO 형식(`20260923`) 패턴(`_PATTERN_BASIC`)을 추가하여 정상 UTC datetime으로 수용 (HEAD 호환성 복원).
   - 콜론 없는 오프셋(`2026-09-23T15:00:00+0900`, `2026.09.23 15:00:00+0900`)도 정상 파싱하여 UTC로 변환 (HEAD 호환성 복원).
4. **회귀 테스트 보강 (`tests/test_date_parsing.py`):**
   - 기본 ISO 8601, 콜론 없는 오프셋, 비정상 오프셋 분/시(5종), 혼합 구분자(4종)에 대한 단위 테스트 추가 (해당 테스트 파일 34개 전체 통과).

---

### 1.4 [P2] R1 데이터 계약의 날짜-only 보존 필드 및 모델 분리 (`docs/campusmate_evaluation_baseline.md`)

1. **시간 모델의 Date-only vs Datetime 분리:**
   - 기존의 nullable datetime(`start_at`, `end_at`)만으로는 "10월 15일 개교기념일" 같은 날짜 전용 일정을 저장할 때 임의의 시각(`00:00` 또는 `23:59`)을 지어내야 하고, UTC 변환 시 날짜가 전날로 밀리는 결함이 발생함을 명시.
   - 손실 없는 보존을 위해 `start_date`, `end_date` (YYYY-MM-DD 문자열)와 `start_datetime`, `end_datetime` (UTC ISO 8601 datetime)을 분리 정의.
2. **5대 일정 유형 및 필드 조합 제약 정의:**
   - `ALL_DAY_EVENT`: `is_all_day=True`, `is_time_confirmed=False`, `start_date`/`end_date` 필수, datetime 필드는 Null.
   - `DATE_ONLY_DEADLINE`: `is_all_day=False`, `is_time_confirmed=False`, `end_date` 필수, datetime 필드는 Null.
   - `TIME_CONFIRMED_DEADLINE`: `is_all_day=False`, `is_time_confirmed=True`, `end_date`, `end_datetime` 필수.
   - `TIME_CONFIRMED_EVENT`: 시작/종료 일시 및 날짜 필드 모두 확정.
   - `SINGLE_POINT_APPOINTMENT`: 시작 일시만 확정, 종료 필드는 Null.
3. **미확정 추출 초안(`ExtractedScheduleDraft`)과 확정 저장 모델(`PersonalSchedule`) 분리:**
   - AI/추출기가 생성하는 모호성/해석옵션 포함 초안 JSON과, 사용자가 최종 확인·수정하여 영속 DB에 저장되는 확정 JSON 예시를 분리 명시.
   - R0 범위 준수: 실제 DB 테이블, ORM 모델 및 API 코드는 R1에서 구현함을 재확인.

---

### 1.5 보고 정확성 보완 (`docs/campusmate_evaluation_baseline.md` 및 본 보고서)

1. **3차원 평가 상태 모델 도입:**
   - 실행 모드(MOCK / LIVE), 호출 결과(SUCCESS / API_ERROR / NOT_RUN / NO_CALL_ABSTAIN), 정답 판정(PASS / FAIL / NEEDS_REVIEW)을 독립적으로 분리 정의.
   - `FAIL`(허위 사실 생성, 팩트 누락)과 `API_ERROR`(인프라/한도 장애)를 명확히 구분.
   - 학내 무관 질의에 대해 LLM 호출 없이 검색 단계에서 올바르게 유보된 상태를 `NO_CALL_ABSTAIN`으로 정의.
2. **정답률 분모 및 지연 시간 집계 원칙 명시:**
   - 정답률 분모는 오직 실제 생성이 완료된 표본(`PASS + FAIL`)만으로 산출하며, `NOT_RUN`과 `API_ERROR`는 분모에서 완전 격리하여 별도 '장애율'로 보고.
   - `latency_p50/p95/mean` 집계 시 `NOT_RUN`(0초)과 `API_ERROR`(0.2초 등)는 완전 제외.
3. **과거 기술 내용 정정:**
   - 'timedelta 누락'은 기존 저장소의 결함이 아니라 Gemini의 수동 오프셋 구현 과정에서 필요했던 import였음을 정정.
   - 원래 HEAD 상태에서는 `parse_iso_datetime`에 `re` 미정의로 인해 `invalid` 및 점 구분 날짜에서 `NameError`가 발생했으며, `2026.09.23garbage` 부분 일치 문제는 종단 앵커(`$`) 부재로 인한 취약점이었음을 명문화.
   - 통과한 테스트(현재 64개)는 지정된 격리 회귀 테스트 슈트의 통과이며, 전체 서비스 검증이 아님을 명시.

---

## 2. 변경 파일 목록

| 파일 경로 | 구분 | 주요 수정 내용 |
|---|---|---|
| `scripts/build_unified_dataset.py` | [MODIFY] | `parse_iso_datetime`: 하이픈/점 패턴 분리(혼합 구분자 거부), 기본 ISO(`YYYYMMDD`) 지원, 콜론 없는 오프셋 지원, 오프셋 분(00~59)/시(00~23) 엄격 검증, docstring 보강 |
| `tests/test_date_parsing.py` | [MODIFY] | 비정상 오프셋 분/시(5종), 혼합 구분자(4종), 기본 ISO, 콜론 없는 오프셋 테스트 추가; fixture 사용자 확인 필수, sched-20 null timestamp, 원문 부분문자열 일치, 취소 공지 전수 검증 추가 (총 34개 테스트) |
| `tests/fixtures/schedule_extraction_cases.json` | [MODIFY] | 23건 케이스: 모든 후보 `requires_user_confirmation: true`, `is_ambiguous` 분리, sched-20 timestamp null 처리 및 interpretation_options 추가, sched-18 원문 무손실 발췌, sched-23 취소 공지 신설 |
| `docs/campusmate_evaluation_baseline.md` | [MODIFY] | 10대 대표 사례 원문 전수 대조(TOPCIT 보증금 20,000원/응시료 10,000원 분리, 졸업유예 6237 페이지 및 자격 정정, 휴학 6248 정정, OCR 노이즈 메모), 다차원 상태 보고 정의, R1 시간 모델(Date-only vs Datetime) 분리 계약 명세 |
| `docs/gemini_round0_revision_report.md` | [NEW] | Codex 지적 1~4번 및 보고 정확성 보완에 대한 수정 내역, 실행 명령, 실제 결과 보고서 (본 문서) |

---

## 3. 실행 명령 및 실제 결과

### 3.1 4개 지정 테스트 파일 전체 실행

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
  ```
- **실행 결과:**
  ```text
  ................................................................         [100%]
  =============================== warnings summary ===============================
  tests/test_codex_round2_fixes.py::test_api_exception_sanitized_and_no_leak_in_answer_and_http
    /Users/jwlee/study1/aisw/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  64 passed, 1 warning in 5.68s
  ```
  - **통과 수:** 64 passed (Codex 지정 기존 3개 파일 30건 + 신규 날짜/fixture 검증 34건)
  - **실패 수:** 0 failed
  - **경고:** 1 warning (Starlette testclient의 third-party deprecation 경고)

### 3.2 Fixture 전수 정합성 검증 확인
`tests/test_date_parsing.py::test_schedule_extraction_fixture_integrity`를 통해 아래 항목이 100% 검증되었습니다:
- 23개 전체 사례 중 후보 일정이 있는 22개 사례 모두 케이스 및 후보 레벨 `requires_user_confirmation: true`.
- 후보가 0건인 상시 안내문(sched-17) 1건만 `requires_user_confirmation: false`.
- sched-20의 확정 타임스탬프(`end_date`)는 `null`이며, `interpretation_options` 2건 제공.
- 모든 후보의 `source_quote`가 원본 `input_text` 내에 정확한 부분 문자열로 존재.
- sched-23 취소 공지 사례가 존재하며 사용자 확인 필수로 지정됨.

---

## 4. 미검증 사항 및 남은 위험

1. **지정 회귀 테스트 범위의 한계:**
   - 64개 테스트 통과는 격리된 단위/Mock 회귀 테스트의 통과이며, 실제 라이브 Gemini API 엔드-투-엔드 응답 품질, 실제 SQLite/PostgreSQL DB 연동, 웹 배포 상태를 검증한 것이 아닙니다.
2. **실제 LLM 모델 호출 미실행:**
   - R0 범위 지침에 따라 실제 Gemini API를 호출하지 않았으므로, 429 한도 리셋 여부 및 라이브 모델의 답변 정밀도는 미검증 상태입니다.
3. **R1 착수 시 다중 사용자 소유권 격리 필수 구현:**
   - R1에서 실제 `PersonalSchedule` 테이블 및 CRUD 엔드포인트를 구현할 때, 타 사용자의 `schedule_id`를 통한 접근 차단(IDOR/BOLA 방어) 테스트가 최우선으로 검증되어야 합니다.

---

**보고서 경로:** `docs/gemini_round0_revision_report.md`  
Codex의 재검수를 요청합니다.
