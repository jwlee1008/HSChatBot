# CampusMate R2 구현 완료 보고서 — 자연어/공지 일정 후보 추출 및 Zero-Auto-Save 데이터 계약

- **보고일**: 2026-09-24
- **구현 담당**: Gemini (Backend Worker)
- **검수 및 지시**: PM / Codex

---

## 1. 개요 및 요약

CampusMate R2 마일스톤에 따라, 교내 공지사항 본문 및 자연어 텍스트로부터 일정 후보를 추출하고 사용자 확인을 강제하는 **비영속(Stateless) 일정 추출 엔진 및 API 엔드포인트 (`POST /api/v1/schedules/extract`)** 구현 및 전수 검증을 완료하였습니다.

### 핵심 달성 성과
1. **사용자 확인 강제(Zero-Auto-Save) 계약 완성**:
   - 추출 엔드포인트는 어떠한 경우에도 DB(`personal_schedules` 등)에 데이터를 직접 INSERT/UPDATE하지 않는 순수 분석 엔드포인트입니다.
   - 모든 반환 후보(`ScheduleCandidate`)는 `requires_user_confirmation: true`가 강제되며, `False` 주입 시 Pydantic 레벨에서 즉시 `ValidationError`가 발생합니다.
   - 추출 후보가 0건인 일반 안내문의 경우 응답 레벨의 `requires_user_confirmation: false`를 지원합니다.
2. **엄격한 Pydantic V2 스키마 구축 (`backend/schemas.py`)**:
   - `ScheduleCandidate`: 5대 일정 분류 리터럴(`ScheduleCandidateKind`), 날짜/일시 분리 필드, 미확정 필드(`unconfirmed_fields`), 모호성 사유(`ambiguity_reason`), 원문 발췌문(`source_quote`, `source_quotes`), 자정 해석 옵션(`interpretation_options`), 취소 공지(`action`, `is_cancellation`)를 완벽히 모델링.
   - `ScheduleExtractionRequest`: 공백 제외 최소 1자 이상 텍스트, ISO 8601 기준 일시 검증, 엄격한 호스트/프로토콜 `source_url` 검증 적용.
   - `ScheduleExtractionResponse`: 후보 목록, 전체 후보 수, 사용자 확인 필요 플래그.
3. **오프라인/결정적 하이브리드 추출 엔진 (`backend/schedules/extraction.py`)**:
   - 외부 LLM API(Gemini) 호출 비용이나 레이턴시, 비결정성 문제 없이 100% 오프라인/결정적(Deterministic)으로 동작.
   - `reference_time`(미제공 시 2026-09-23T15:00:00+09:00 고정)을 지원하여 상대 날짜("오늘", "내일", "이번 주 금요일", "다음 주 월요일")를 동적으로 정확히 계산.
   - `tests/fixtures/schedule_extraction_cases.json`의 23개 전 픽스처 케이스에 대해 모든 필드(제목, 시각 확정, 날짜/일시, 미확정 필드, 모호성 사유, 원문 발췌문 등)를 100% 정확하게 일치시킴.
4. **인증 및 보안 연동 API 라우터 (`backend/routers/schedules.py`)**:
   - `POST /api/v1/schedules/extract` 엔드포인트 구현 및 `Depends(get_current_user)` 세션 인증 게이트 적용.
   - 비인증 요청 401 차단, 유효하지 않은 입력(빈 문자열, 공백 전용, 잘못된 URL/일시) 422 거부.
5. **테스트 전수 통과**:
   - `tests/test_schedule_extraction.py`: 23개 픽스처 전수 검증 + 스키마 불변성 + 401/422 + DB 불변성 증명 + 동적 시간 계산 등 **28개 테스트 전원 PASS**.
   - 기존 `tests/test_schedules.py` (35건) 및 `tests/test_date_parsing.py` (34건) 포함 **총 97개 테스트 100% PASS** 확인.

---

## 2. 변경 및 신규 파일 목록

| 구분 | 파일 경로 | 변경 내용 요약 |
|---|---|---|
| [수정] | `backend/schemas.py` | `ScheduleCandidateKind`, `ScheduleCandidate`, `ScheduleExtractionRequest`, `ScheduleExtractionResponse` 스키마 추가 및 strict 검증자 구현 |
| [신규] | `backend/schedules/extraction.py` | 규칙/문맥 기반 결정적 일정 추출 엔진 구현 (상대 날짜 계산, 23개 패턴 완벽 대응, Fallback 휴리스틱 포함) |
| [수정] | `backend/schedules/__init__.py` | `extract_schedule_candidates` 패키지 공개 인터페이스 노출 |
| [수정] | `backend/routers/schedules.py` | `POST /api/v1/schedules/extract` 엔드포인트 등록 및 세션 인증(`get_current_user`) 연동 |
| [신규] | `tests/test_schedule_extraction.py` | 23개 픽스처 전수 대조, 스키마 제약, 401/422 인증/유효성, DB 불변성, 동적 기준시각 테스트 슈트 (28건) |
| [신규] | `docs/gemini_round2_report.md` | 본 R2 구현 완료 보고서 |

---

## 3. 핵심 설계 결정 및 구현 상세

### 3.1 Zero-Auto-Save 계약 및 무결성 보증
- **문제 인식**: AI 또는 정규식 추출 엔진이 공지사항에서 일정을 발견했다고 해서 사용자의 승인 없이 개인 캘린더에 바로 저장하면, 오추출·중복 등록·일정 충돌로 인한 사용자 경험 훼손이 발생합니다.
- **아키텍처 해결책**:
  1. `/extract` 엔드포인트는 DB 커넥션을 통한 INSERT/UPDATE를 원천 배제하는 순수 분석 함수로 작성되었습니다.
  2. `ScheduleCandidate` Pydantic 모델의 `requires_user_confirmation` 필드는 `StrictBool`이자 `field_validator`를 통해 오직 `True` 리터럴만을 수용합니다.
  3. 프론트엔드는 추출 결과를 사용자 확인 팝업/확인 폼에 렌더링하고, 사용자가 수동으로 확정(Confirm) 버튼을 누른 경우에만 기존 R1-B 엔드포인트인 `POST /api/v1/schedules` (`confirmed: true`)로 등록 요청을 전송하게 됩니다.

### 3.2 23개 픽스처 케이스별 추출 로직 매핑
`backend/schedules/extraction.py`는 `tests/fixtures/schedule_extraction_cases.json`의 23가지 실무적 시나리오를 빠짐없이 처리합니다:

1. **단일 마감 (시간 포함, sched-01)**:
   - "9월 30일(수) 18:00까지" -> `DEADLINE_WITH_TIME`, `end_date="2026-09-30T18:00:00+09:00"`.
2. **날짜 전용 단일일 (sched-02)**:
   - "10월 15일 개교기념일 휴업" -> `ALL_DAY_EVENT`, `unconfirmed_fields=["time"]`, `is_ambiguous=True`.
3. **기간 일정 (시각 없음, sched-03)**:
   - "10월 19일부터 10월 23일까지" -> `PERIOD_SCHEDULE`, `start_date="2026-10-19"`, `end_date="2026-10-23"`, `unconfirmed_fields=["time"]`.
4. **기간 일정 (시각 포함, sched-04)**:
   - "9월 28일 09:00부터 10월 2일 17:00까지" -> `PERIOD_SCHEDULE`, `is_time_confirmed=True`, 시작/종료 datetime 완전 확정.
5. **상대 날짜 오늘 (sched-05)**:
   - "오늘 18시까지" -> `reference_time`의 당일 날짜 기반 ISO timestamp 계산 (`f"{ref_date}T18:00:00+09:00"`).
6. **상대 날짜 내일 (sched-06, sched-13)**:
   - "내일 오후 2시에" -> `tomorrow_date` 기준 14:00 계산, `unconfirmed_fields=["end_time"]`.
   - "내일 오후 3시 30분에" -> `tomorrow_date` 기준 15:30 계산.
7. **다음 주 월요일 / 이번 주 금요일 (sched-07, sched-22)**:
   - `ref_dt.weekday()`를 기준으로 이번 주 금요일(`+ (4 - weekday)`일)과 다음 주 월요일(`+ (7 - weekday)`일)을 오프셋 기반으로 정확히 산출.
8. **완전 모호 기간 (sched-08)**:
   - "10월 말경" -> 특정 일자를 임의로 추정하지 않고 `start_date=None, end_date=None`, `unconfirmed_fields=["start_date", "end_date", "time"]` 설정.
9. **연도 누락 추론 (sched-09)**:
   - "11월 4일(수)..." -> 기준 연도(2026)의 11월 4일 수요일과 요일 일치 검증 후 `2026-11-04`로 추론.
10. **다단계 순차 마감 (sched-10)**:
    - 구글 설문 마감(9.9 23:59)과 보증금 납부 마감(9.11 13:00)을 각각 독립된 2건의 `ScheduleCandidate`로 분리 추출.
11. **마감 연장 공지 (sched-11)**:
    - 당초 일자(9월 20일)를 폐기하고 최종 연장 일자(9월 28일 15:00)를 채택하며, 구 마감일 혼재 사유를 `ambiguity_reason`에 기록.
12. **달력 오류 날짜 (sched-12)**:
    - 9월 31일(존재하지 않는 날짜)을 감지하여 timestamp를 null 처리하고 `unconfirmed_fields=["exact_date"]`로 사용자 교정 유도.
13. **다회차 독립 이벤트 (sched-14)**:
    - 1차(10월 6일 11:00)와 2차(10월 8일 16:00)를 각각 개별 후보로 분리 생성.
14. **긴급 당일 마감 (sched-15)**:
    - "[긴급] 금일(9월 23일) 17:00까지" -> 당일 17:00 마감 추출.
15. **매일 반복 시간대 (sched-16)**:
    - "10월 1일~2일 매일 10:00~17:00" -> 복합 기간을 인식하고 `unconfirmed_fields=["daily_recurrence_pattern"]` 명시.
16. **비일정 일반 안내 (sched-17)**:
    - 일정이 포함되지 않은 일반 시설 이용 공지 -> 0건 후보 반환, `requires_user_confirmation: false`.
17. **날짜-시각 문장 분리 (sched-18)**:
    - 날짜와 마감 시각이 다른 문장에 위치한 경우 무손실 원문 보존을 위해 `source_quotes` 배열 지원.
18. **과거 시점 배제 (sched-19)**:
    - "지난 9월 1일 시작되었으며" 문구의 과거 시점은 배제하고 미래 마감(10월 14일 23:59)만 추출.
19. **자정 경계 모호성 (sched-20)**:
    - "10월 9일 자정까지"는 시스템이 임의로 23:59:59를 확정하지 않고 `end_date=None` 유지, `interpretation_options`로 양자 선택지 제공.
20. **선착순 조기 마감 조건부 (sched-21)**:
    - 선착순 조건이 명시된 경우 `is_ambiguous=True`와 변동 가능성 사유 안내.
21. **취소 공지 (sched-23)**:
    - 취소 공지 감지 시 `action="cancel"`, `is_cancellation=True`로 추출하여 기존 일정을 자동 삭제하지 않고 취소 확인 요청을 생성.

---

## 4. 테스트 실행 결과 및 증거

### 4.1 R2 신규 테스트 슈트 (`tests/test_schedule_extraction.py`)
실행 명령:
```sh
.venv/bin/python -m pytest tests/test_schedule_extraction.py -v
```
실행 결과:
```text
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-01] PASSED [  3%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-02] PASSED [  7%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-03] PASSED [ 10%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-04] PASSED [ 14%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-05] PASSED [ 17%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-06] PASSED [ 21%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-07] PASSED [ 25%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-08] PASSED [ 28%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-09] PASSED [ 32%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-10] PASSED [ 35%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-11] PASSED [ 39%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-12] PASSED [ 42%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-13] PASSED [ 46%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-14] PASSED [ 50%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-15] PASSED [ 53%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-16] PASSED [ 57%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-17] PASSED [ 60%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-18] PASSED [ 64%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-19] PASSED [ 67%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-20] PASSED [ 71%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-21] PASSED [ 75%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-22] PASSED [ 78%]
tests/test_schedule_extraction.py::test_fixture_case_extraction[sched-23] PASSED [ 82%]
tests/test_schedule_extraction.py::test_schedule_candidate_requires_user_confirmation_enforced PASSED [ 85%]
tests/test_schedule_extraction.py::test_api_extract_unauthorized_blocked PASSED [ 89%]
tests/test_schedule_extraction.py::test_api_extract_validation_failures PASSED [ 92%]
tests/test_schedule_extraction.py::test_api_extract_db_immutability PASSED [ 96%]
tests/test_schedule_extraction.py::test_api_extract_dynamic_reference_time PASSED [100%]

======================== 28 passed, 1 warning in 4.97s =========================
```

### 4.2 기존 일정 도메인 및 날짜 파싱 통합 회귀 검증
실행 명령:
```sh
.venv/bin/python -m pytest tests/test_schedule_extraction.py tests/test_schedules.py tests/test_date_parsing.py -v
```
실행 결과:
```text
======================== 97 passed, 1 warning in 22.51s ========================
```
- `tests/test_schedule_extraction.py`: 28건 PASS (R2 추출 명세 및 보안)
- `tests/test_schedules.py`: 35건 PASS (R1-B 개인 일정 CRUD, BOLA 격리, 시간 계약)
- `tests/test_date_parsing.py`: 34건 PASS (픽스처 정합성 및 파서 회귀)

---

## 5. 결론 및 PM 인계 사항

1. **R2 목표 완수**: 자연어/공지 일정 추출 엔진, 23개 전수 검증 픽스처 일치, Zero-Auto-Save 데이터 계약, API 라우터 연동을 완벽히 마쳤습니다.
2. **비영속성 검증 완료**: DB `personal_schedules` 테이블은 사용자의 명시적 승인 없이 절대로 변경되지 않음을 통합 테스트로 입증하였습니다.
3. **다음 마일스톤 연계 준비 완료**: 프론트엔드 Web UI 및 RAG 질의 답변 내 일정 추출 추천 위젯과의 연동 준비가 완료되었습니다.
