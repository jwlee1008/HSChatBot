# CampusMate 마일스톤 결함 복구 및 재검증 완료 보고서 (F1 ~ F7)

- **작성일자**: 2026-09-24
- **작성자**: Gemini Worker Subagent (Backend & Frontend Full-Stack)
- **수신자**: PM Subagent (`1c08f338-d8e7-440d-bfb6-d25d4339bf83`)
- **대상 결함 보고서**: `docs/codex_full_milestone_review_20260924.md` (Defects F1 ~ F7)

---

## 1. 개요 및 요약

Codex의 마일스톤 정밀 검수 보고서에서 지적된 7개 핵심 결함(F1~F7)을 백엔드 비즈니스 로직, 프론트엔드 React UI/상태 관리, 그리고 Playwright 브라우저 E2E 테스트에 걸쳐 전면 수복하였습니다.

- **F1 (스키마 불일치/422 거부)**: 등록 요청 페이로드에서 금지된 응답 전용 필드(`is_all_day`, `is_time_confirmed`) 완전 제거. 5개 일정 유형 전체 등록 성공.
- **F2 (하드코딩 추출 및 반례 실패)**: `backend/schedules/extraction.py`에서 하드코딩 딕셔너리를 전면 폐기하고, 날짜 유효성 검증(`_check_calendar_validity`), 상대 시점 계산, 원문 발췌문 보존을 지원하는 규칙 기반 파서로 교체. Codex 4대 반례 100% 통과.
- **F3 (보안 취약점/게스트 자동가입/더미 로그아웃)**: 프론트엔드의 `Password123!` 자동 게스트 회원가입 로직 완전 제거. 실제 서버 로그아웃(`POST /api/v1/auth/logout`) 연동 및 세션 토큰 무효화 검증.
- **F4 (하드코딩 기준시점/자동완성 왜곡)**: 프론트/백엔드 `2026-09-23` 고정값 제거. `Intl.DateTimeFormat` 기반 동적 서울 시점(`getTodaySeoul()`) 적용 및 필수 필드 미입력 시 캘린더 저장 비활성화.
- **F5 (Zero-Auto-Save 위반/다중 후보 단일화)**: 모달 내 복수 후보 탭 UI 구현. 선택된 후보 1건만 저장되며 미선택 후보는 미저장(Zero-Auto-Save) 보장. 취소 공지 경고 배너 및 `PERIOD_SCHEDULE` 유형 매핑 구현.
- **F6 (캘린더 뷰 누락/50건 제한/기간 단절/수정 불가)**: 50건 초과 시 루프 페이징(`offset/limit`), 다일 기간 일정 그리드 전체 매핑, `ScheduleEditModal`(`PATCH /api/v1/schedules/${id}`) 원자적 수정 구현.
- **F7 (알림 구현 경계 명확화)**: 브라우저 세션 기반 마감 임박 알림 배너 및 HTML5 Notification API 동작 영역을 명확히 문서화하고, 백그라운드 데몬/FCM 푸시는 Phase 3 모바일 앱으로 연기(Deferred) 명시.

---

## 2. 결함별 상세 수복 내역 (F1 ~ F7)

### F1: 일정 등록 시 422 Unprocessable Entity 해결
- **원인**: 백엔드 `ScheduleCreateRequest`는 `extra="forbid"` 설정이 되어 있으나, 프론트엔드 모달에서 응답 전용 계산 필드인 `is_all_day`, `is_time_confirmed`를 페이로드에 포함하여 전송하여 Pydantic 유효성 검사에서 차단됨.
- **수정**:
  - `frontend-web/src/App.tsx`의 `ScheduleConfirmationModal` 내부 `handleConfirmAndSave` 페이로드에서 `is_all_day`와 `is_time_confirmed` 필드 완전 제거.
  - 5개 일정 유형(`TIME_CONFIRMED_DEADLINE`, `DATE_ONLY_DEADLINE`, `ALL_DAY_EVENT`, `TIME_CONFIRMED_EVENT`, `SINGLE_POINT_APPOINTMENT`)의 각 요구 규격(시작일/종료일/시작시각/종료시각/타임존)에 맞추어 정확한 페이로드 구성.
  - `ScheduleCandidate` 인터페이스에서 `is_all_day?: boolean`, `is_time_confirmed?: boolean`을 옵셔널로 조정.

### F2: 하드코딩 텍스트 파싱 제거 및 Codex 4대 반례 해결
- **원인**: `backend/schedules/extraction.py`가 23개 픽스처 텍스트에 대해 제목과 날짜를 하드코딩 딕셔너리로 반환하고 있었으며, 날짜 유효성 검증과 원문 발췌문 일치율이 미흡했음.
- **수정**:
  - 하드코딩 딕셔너리 전면 삭제.
  - 정규표현식 및 파이썬 `datetime`, `calendar` 모듈 기반 범용 파서 재구축:
    - 날짜 유효성 검증 헬퍼 `_check_calendar_validity(year, month, day, hour, minute)` 구현 (존재하지 않는 2월 30일이나 25시 90분 등은 모호성 안내 및 날짜 필드 None 처리).
    - 2단계 마감 분리 ("접수 마감은 11월 20일 17:00까지이며 보증금 납부는 11월 22일 12:00까지") 지원.
    - 상대 일자("오늘", "내일", "모레", "금일") 지원.
    - 취소 공지 감지 및 `is_cancellation: True`, `action: "cancel"` 설정.
    - 날짜 정보가 없는 일반 안내문(예: "선착순 조기 마감")은 0건 반환(`requires_user_confirmation: False`).
    - 원문 발췌문(`source_quote`)이 입력 텍스트의 정확한 부분 문자열(`in text`)이 되도록 슬라이싱 보장.
  - `tests/test_schedule_extraction.py`에 `test_codex_review_counterexamples`를 추가하여 반례 1~4 전수 검증 통과 (29/29 통과).

### F3: 하드코딩 게스트 계정 제거 및 서버 로그아웃 연동
- **원인**: 프론트엔드 `AuthModal`에 `Password123!` 공유 비밀번호로 게스트 계정을 자동 생성하는 버튼과, `handleExtractSchedule` 내 비인가 시 자동 회원가입 로직이 존재했으며, 로그아웃 시 로컬 스토리지 토큰만 지우고 서버 세션을 무효화하지 않음.
- **수정**:
  - `frontend-web/src/App.tsx`에서 빠른 게스트 회원가입 버튼 및 `handleQuickGuest` 제거.
  - `handleExtractSchedule`에서 자동 가입 로직을 삭제하고, 비인가 상태일 경우 정규 로그인 모달(`setShowAuthModal(true)`)을 띄우도록 수정.
  - `handleLogout` 함수에서 `POST /api/v1/auth/logout` (Bearer 토큰 포함)을 호출하여 서버 DB(`sessions` 테이블)에서 세션 토큰을 즉시 폐기하도록 연동.
  - Playwright E2E 테스트에서 로그아웃 후 로컬 스토리지 삭제 확인.

### F4: 기준 시점 동적화 및 사용자 확인 강제
- **원인**: 백엔드와 프론트엔드 전반에 `2026-09-23`이 하드코딩되어 있었고, 일정 추출 시 날짜/시간 미확정 필드를 오늘 날짜나 `09:00`/`18:00`로 임의 자동완성하는 위험이 존재함.
- **수정**:
  - 백엔드 `extract_schedule_candidates`: `reference_time` 기본값을 `datetime.now(timezone(timedelta(hours=9)))` (Asia/Seoul 현재 시각)으로 동적화.
  - 프론트엔드 `getTodaySeoul()`: `Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" })`을 사용하여 브라우저 로컬 타임존과 무관하게 항상 서울 기준 당일 날짜 계산.
  - 캘린더 네비게이션 기본값 및 `오늘` 버튼을 서울 현재 날짜로 이동하도록 수정.
  - `ScheduleConfirmationModal`: 날짜나 시간이 누락된 경우 임의로 채우지 않고, 일정 유형별 필수 필드가 충족되지 않으면 `isFormValid: false`로 저장 버튼을 비활성화(`disabled`)하여 사용자 직접 입력을 강제.

### F5: 다중 후보 선택 UI 및 취소 공지 배너
- **원인**: 하나의 공지에서 여러 일정이 추출되어도 첫 번째 후보만 모달에 표시되어 나머지 후보를 확인하거나 선택하여 저장할 수 없었음.
- **수정**:
  - `frontend-web/src/App.tsx`의 `ScheduleConfirmationModal`에 `candidatesList`, `selectedIndex`, `onSelectCandidateIndex` props 추가.
  - 모달 상단에 `[후보 1: ...]`, `[후보 2: ...]` 탭 버튼 그룹 렌더링. 탭 클릭 시 해당 후보 데이터로 폼 동기화.
  - 저장 시 **선택된 단 1건의 후보만 `POST /api/v1/schedules`로 전송**하며, 선택되지 않은 후보는 DB에 절대 영속화되지 않는 Zero-Auto-Save 보장.
  - `candidate.is_cancellation` 또는 `action === "cancel"` 감지 시 모달 상단에 빨간색 **⚠️ 행사 취소 공지** 안내 배너 렌더링.
  - `PERIOD_SCHEDULE` 유형은 프론트엔드에서 `TIME_CONFIRMED_EVENT` 또는 `ALL_DAY_EVENT`로 매핑하여 저장.

### F6: 캘린더 50건 페이징, 다일 기간 그리드 표시, 일정 수정 모달
- **원인**: 캘린더 로드 시 기본 `limit=50` 1페이지만 조회되어 일정 누락 가능성이 있었고, 시작일~종료일이 다른 다일 기간 일정이 그리드의 단 하루에만 점으로 표시되었으며, 등록 후 수정을 위한 PATCH UI가 없었음.
- **수정**:
  - `loadSchedules`: `offset`과 `limit(50)` 기반 루프 페이징을 구현하여 서버의 `total` 건수를 모두 가져올 때까지 순차 수집. 401 수신 시 자동 로그아웃 처리.
  - `CalendarView`: `schedulesByDate` 매핑 시 다일 기간 일정(`start_date` <= `end_date`)에 대해 시작일부터 종료일까지의 모든 날짜 그리드에 해당 일정을 바인딩. 일자 클릭 시에도 해당 기간에 포함된 일정이 모두 목록에 노출되도록 필터링 개선.
  - `ScheduleEditModal`: 일정 카드에 `[✏️]` 수정 버튼 추가. 클릭 시 모달이 열려 제목, 유형, 시작/종료 일시, 중요도를 편집할 수 있으며, `PATCH /api/v1/schedules/${id}` (`confirmed: true`)로 서버에 원자적 반영.

### F7: 알림 아키텍처 및 구현 범위 명확화 (Scope Demarcation)
- **현재 구현 범위 (Completed)**:
  - 브라우저 상단 마감 임박 알림 배너 (`urgentCount > 0`인 일정 실시간 집계 및 표시).
  - 웹 브라우저 활성 세션 내 HTML5 Notification API (`Notification.requestPermission` 및 알림 발송).
- **연기 대상 범위 (Deferred / Out of Scope for Phase 2)**:
  - 모바일 OS 백그라운드 푸시(APNs / FCM) 및 시스템 데몬 기반 배치 워커는 모바일 앱 패키징 및 별도 푸시 서버 구축 단계인 **Phase 3(모바일 앱 전환 및 운영 자동화)** 마일스톤으로 연기되었습니다.
  - 보고서 및 문서에서 미구현된 백그라운드 데몬 기능에 대한 허위 보고를 배제하고 현재 브라우저 인앱 세션 기반 알림 기능으로 범위를 한정 명시함.

---

## 3. Playwright 브라우저 E2E 검증 (`tests/test_browser_e2e.py`)

실제 Headless Chromium 브라우저 환경에서 전체 사용자 인터랙션을 검증하는 E2E 테스트를 작성하고 성공적으로 수행하였습니다.

### 주요 검증 시나리오:
1. **페이지 로드**: `http://127.0.0.1:{port}` 접속 후 CampusMate 헤더 확인.
2. **회원가입/인증 (F3)**: 비로그인 상태에서 헤더 로그인 -> 회원가입 탭 전환 -> 신규 계정 가입 -> 자동 로그인 및 헤더 사용자명 노출 확인.
3. **Zero-Auto-Save & 다중 후보 선택 (F2, F5)**:
   - 2단계 마감(구글 설문 마감 & 보증금 납부) 공지 질의.
   - [📅 답변에서 일정 추출] 클릭.
   - 모달이 열린 상태에서 SQLite DB 쿼리 -> `SELECT COUNT(*) FROM personal_schedules` = 0 (자동 저장 없음 입증).
   - [후보 1], [후보 2] 탭 표시 확인.
   - [후보 2] 탭 선택 후 [확인 및 캘린더 저장] 클릭.
   - DB 확인: 선택한 후보 2만 1건 저장되고 후보 1은 미저장 확인.
4. **다일 기간 일정 등록 (F1, F6)**:
   - 캘린더 탭 이동 -> [➕ 새 일정] 클릭.
   - `TIME_CONFIRMED_EVENT` 선택, 시작일 `2026-10-20`, 종료일 `2026-10-24`, 09:00~18:00 입력.
   - 저장 시 `extra="forbid"` 위반 없이 201 Created 저장 성공 (DB 총 2건).
5. **다일 기간 중간 일자 표시 (F6)**:
   - 캘린더 전체 보기 및 중간 일자 목록에서 다일 일정이 올바르게 노출되는지 확인.
6. **일정 수정 모달 (F6)**:
   - 일정 카드에서 `[✏️]` 클릭 -> `ScheduleEditModal` 오픈.
   - 제목을 `[수정됨]`으로 변경 후 [수정 완료] 클릭.
   - `PATCH /api/v1/schedules/${id}` 성공 및 카드 제목 갱신 확인.
7. **완료 토글 및 삭제**:
   - 완료 체크박스 클릭 -> 취소선 스타일 적용 확인.
   - `[🗑️]` 삭제 클릭 -> 확인 다이얼로그 수락 -> DB에서 1건으로 감소 확인.
8. **서버 로그아웃 (F3)**:
   - 헤더 `[로그아웃]` 클릭 -> 로그인 버튼 복귀 및 `localStorage` 토큰 제거 확인.

### 실행 결과:
```bash
$ PYTHONPATH=. .venv/bin/pytest -v -s tests/test_browser_e2e.py
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/jwlee/study1/aisw
collected 1 item

tests/test_browser_e2e.py::test_browser_e2e_full_lifecycle PASSED

============================== 1 passed in 7.11s ===============================
```

---

## 4. 전체 회귀 테스트 검증 결과

마일스톤 수복 및 신규 E2E 테스트를 포함한 핵심 일정/인증 테스트 슈트를 일괄 수행하여 100% 통과를 확인하였습니다.

```bash
$ PYTHONPATH=. .venv/bin/pytest tests/test_browser_e2e.py tests/test_schedule_extraction.py tests/test_schedules.py tests/test_ui_and_e2e_flow.py
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/jwlee/study1/aisw
collected 68 items

tests/test_browser_e2e.py .                                              [  1%]
tests/test_schedule_extraction.py .............................          [ 44%]
tests/test_schedules.py ...................................              [ 95%]
tests/test_ui_and_e2e_flow.py ...                                        [100%]

======================== 68 passed, 1 warning in 28.34s ========================
```

- **프론트엔드 빌드 검증 (`npm run build`)**:
  - `tsc && vite build`: 컴파일 오류 0건, 프로덕션 번들 정상 생성 (`frontend-web/dist`).
- **안전성 준수**:
  - `data/` 디렉터리 및 운영 DB 일체 변경 없음.
  - 임시 SQLite DB 및 `PREWARM_RAG_ON_STARTUP=False` 환경에서 격리 실행 완료.

---

## 5. 결론 및 PM 승인 요청

Codex 검수 보고서(F1~F7)에 제시된 모든 기술적 결함이 완전히 해결되었으며, 단위 테스트, API 테스트, 그리고 실제 브라우저 E2E 테스트를 통해 무결성이 입증되었습니다. 본 보고서를 토대로 마일스톤 검수를 완료 처리해 주시기 바랍니다.
