# CampusMate R1-B 구현 완료 보고서 — 개인 일정 CRUD 및 사용자별 접근 격리

보고일: 2026-09-23  
구현 담당: Gemini  
설계·검수 총괄: Codex  

---

## 1. 개요 및 요약

CampusMate R1-B 마일스톤에 따라, 기존 R1-A 계정·인증 및 파일 기반 영속 저장소를 기반으로 **사용자가 확인한 개인 일정의 CRUD 및 사용자별 접근 격리(BOLA/IDOR 방어) 백엔드**를 성공적으로 구현하고 검증을 완료했습니다.

### 주요 달성 결과
1. **SQLite 마이그레이션 v2 구축**: 기존 v1 `users` 및 `sessions` 테이블과 데이터를 100% 보존하며 신규 `personal_schedules` 테이블 및 2종 인덱스를 추가했습니다.
2. **5대 일정 유형(ScheduleKind) 시간 계약 및 서울 날짜 일치 보증**:
   - `ALL_DAY_EVENT`, `DATE_ONLY_DEADLINE`, `TIME_CONFIRMED_DEADLINE`, `TIME_CONFIRMED_EVENT`, `SINGLE_POINT_APPOINTMENT`의 필수/금지 필드 엄격 분리.
   - ISO 8601 일시 문자열을 `Asia/Seoul`로 변환했을 때의 달력 날짜와 대응 날짜 필드(`start_date`/`end_date`)의 일치성을 검증하여 불일치 시 `422` 반환.
   - naive datetime, epoch 숫자 타임스탬프, 평년 윤일(2026-02-29), 역전 기간 엄격 차단.
3. **사용자 확인 필수 정책 (`confirmed: true`)**: 일정 생성 및 수정 요청 시 `confirmed: StrictBool`이 반드시 `true`여야 하며, 누락, `false`, 문자열 `"true"`, 숫자 `1`은 즉시 `422`로 거부됩니다.
4. **소유권 기반 접근 제어 (BOLA/IDOR 방어)**: 타인의 UUID 또는 존재하지 않는 UUID 조회/수정/삭제 요청에 대해 일관되게 안전한 `404 Not Found`를 반환하며, 모든 DB 작업은 `WHERE ... AND user_id = ?`로 엄격히 한정됩니다.
5. **PATCH 의미 및 원자적 롤백**: 미전송 필드 보존, nullable 필드 명시적 null 지원, non-nullable 필드 null 차단, 변경 필드 부재(`confirmed` 단독) 차단, 유형 전환 시 잔여 금지 필드 잔존 차단, 검증 실패 시 DB 부분 변경 없는 원자적 롤백을 구현했습니다.
6. **캘린더 및 목록 조회 필터링**: `date_from`/`date_to` 동시 필수 제공, 월 경계를 넘는 다일 기간 일정 겹침 필터링, 정렬(`COALESCE(start_date, end_date) ASC, id ASC`), 페이지네이션 및 total 건수 정확도를 확보했습니다.
7. **테스트 전수 통과**: 신규 8개 테스트 스위트 통과, 기존 79개 회귀 테스트 포함 총 **87 passed, 1 warning (24.17초)** 달성, RAG 대표 10사례 로컬 데이터 전수 대조 10/10 PASS 달성.

---

## 2. 변경 및 신규 파일 목록

| 구분 | 파일 경로 | 변경 내용 요약 |
|---|---|---|
| [수정] | `backend/db/migrations.py` | `MIGRATIONS` 딕셔너리에 버전 2 추가 (`personal_schedules` 테이블 및 인덱스) |
| [수정] | `backend/schemas.py` | `ScheduleKind`, `Priority` enum, `ScheduleCreateRequest`, `SchedulePatchRequest`, `ScheduleResponse`, `ScheduleListResponse` 스키마 추가 |
| [신규] | `backend/schedules/__init__.py` | 개인 일정 패키지 초기화 파일 |
| [신규] | `backend/schedules/service.py` | 5대 일정 유형 계약 검증, 서울 달력 날짜 일치 검증, CRUD 및 BOLA 격리 서비스 구현 |
| [신규] | `backend/routers/schedules.py` | `/api/v1/schedules` RESTful API 라우터 구현 (POST, GET 목록/상세, PATCH, DELETE) |
| [수정] | `backend/main.py` | `schedules_router` 등록 (정적 파일 서빙 mount 전 등록) |
| [수정] | `tests/test_auth_persistence.py` | Codex R1-A 최종 검수 피드백 반영: `dependency_overrides` 사본 저장/복구, 기본 DB 미접근 assertion 강화, 숫자 비밀번호 assert 분리 |
| [신규] | `tests/test_schedules.py` | 5대 유형 CRUD, BOLA 격리, 서버 관리 필드 차단, 서울 날짜 일치, PATCH 의미, 캘린더 필터, v1->v2 보존, 서브프로세스 영속성 테스트 |
| [신규] | `docs/campusmate_schedule_api_guide.md` | 개인 일정 REST API 개발자 및 사용자 가이드 (요청 예시, PATCH null 의미, 필터링 등) |
| [신규] | `docs/gemini_round1b_report.md` | 본 R1-B 완료 보고서 |

---

## 3. 핵심 설계 결정 및 구현 상세

### 3.1 5대 일정 유형의 날짜·시각 모델 계약
- **필수 및 금지 필드 분리**:
  - `ALL_DAY_EVENT`: `start_date`, `end_date` 필수, `start_datetime`, `end_datetime` null.
  - `DATE_ONLY_DEADLINE`: `end_date` 필수, 나머지 null.
  - `TIME_CONFIRMED_DEADLINE`: `end_date`, `end_datetime` 필수, 나머지 null.
  - `TIME_CONFIRMED_EVENT`: 4개 필드 모두 필수, `start_datetime < end_datetime`.
  - `SINGLE_POINT_APPOINTMENT`: `start_date`, `start_datetime` 필수, 나머지 null.
- **서울 기준 달력 날짜 일치 (`match_seoul_calendar_date`)**:
  - 클라이언트가 UTC 일시(`2026-09-30T15:30:00Z`) 또는 오프셋 일시(`2026-10-01T00:30:00+09:00`)를 보냈을 때, 이를 `Asia/Seoul` 시간대로 변환한 달력 날짜가 대응 날짜 필드(`2026-10-01`)와 정확히 일치하는지 대조합니다.
  - 임의로 날짜를 보정하지 않고 불일치 시 `422`를 즉시 반환하여 정합성을 유지합니다.
- **날짜/일시 전용 파싱**:
  - 날짜 필드에는 `re.match(r"^\d{4}-\d{2}-\d{2}$")` 및 `datetime.strptime`을 적용하여 평년 윤일(예: 2026-02-29)을 `422`로 거부.
  - 일시 필드에는 naive 일시, 날짜-only 문자열, epoch 숫자를 `422`로 엄격히 차단.

### 3.2 사용자 확인 플래그 (`confirmed: StrictBool`)
- Pydantic의 `StrictBool` 타입을 적용하여, JSON의 `true` 리터럴만을 허용.
- `"true"`(문자열), `1`(정수), 누락, `false`는 모두 `422`로 차단.
- 생성 및 PATCH 모두 확인이 필수이며, AI 추출이나 원문 기반 자동 저장을 방지하는 계약상 기준을 확립.

### 3.3 PATCH 원자성 및 필드 전환 규칙
- `request.model_fields_set`을 활용하여 요청에 명시적으로 포함된 필드만 추출.
- `confirmed` 외 변경 필드가 0개인 경우 `422` 반환.
- non-nullable 필드(`title`, `schedule_kind`, `timezone`, `priority`, `is_completed`)에 `null` 전송 시 `422` 반환.
- 기존 DB 레코드와 병합한 전체 상태에 대해 5대 유형 계약을 재검증. 유형 전환 시 기존 금지 필드를 명시적 `null`로 비우지 않은 경우 `422` 반환.
- 검증 실패 시 DB 트랜잭션이 롤백되어 어떠한 부분 데이터 변경도 발생하지 않음.

### 3.4 BOLA / IDOR 접근 격리
- `SELECT`, `UPDATE`, `DELETE`, `COUNT` 모든 쿼리가 `user_id = ?` 파라미터를 강제.
- 타인 소유의 UUID 또는 존재하지 않는 UUID 접근 시 동일하게 `HTTPException(status_code=404, detail="일정을 찾을 수 없습니다.")`를 반환하여 리소스 존재 여부 자체를 은닉.

### 3.5 목록 및 캘린더 기간 겹침 쿼리
- `date_from`과 `date_to`는 둘 다 제공되거나 둘 다 생략되어야 함 (위반 시 `422`).
- 겹침 판정 조건:
  $$\text{COALESCE}(start\_date, end\_date) \le date\_to \quad \land \quad \text{COALESCE}(end\_date, start\_date) \ge date\_from$$
- 월 경계를 넘는 기간 행사(예: 2026-09-28 ~ 2026-10-03)가 10월 조회 시에도 정확하게 포함됨을 검증.

---

## 4. 테스트 실행 결과 및 증거

### 4.1 신규 일정 테스트 슈트 (`tests/test_schedules.py`)
실행 명령:
```sh
.venv/bin/python -m pytest tests/test_schedules.py -v
```
실행 결과:
```text
tests/test_schedules.py::test_5_schedule_kinds_crud_lifecycle PASSED     [ 12%]
tests/test_schedules.py::test_multi_user_bola_isolation PASSED           [ 25%]
tests/test_schedules.py::test_server_managed_fields_confirmed_and_auth_gate PASSED [ 37%]
tests/test_schedules.py::test_date_and_time_strict_contract PASSED       [ 50%]
tests/test_schedules.py::test_patch_semantics_and_atomicity PASSED       [ 62%]
tests/test_schedules.py::test_calendar_and_list_filtering PASSED         [ 75%]
tests/test_schedules.py::test_v1_to_v2_migration_preserves_users_and_sessions PASSED [ 87%]
tests/test_schedules.py::test_subprocess_schedule_persistence PASSED     [100%]

======================== 8 passed, 1 warning in 13.86s =========================
```

### 4.2 전체 회귀 테스트 결합 실행
실행 명령:
```sh
.venv/bin/python -m pytest tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```
실행 결과:
```text
........................................................................ [ 82%]
...............                                                          [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  /Users/jwlee/study1/aisw/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

87 passed, 1 warning in 24.17s
```
- 기존 79개 테스트 + 신규 8개 테스트 = **총 87개 테스트 전수 통과**.
- 유일한 경고는 Starlette TestClient의 AnyIO deprecation 경고임 (기능 결함 아님).

### 4.3 RAG 대표 10사례 근거 검증 스크립트
실행 명령:
```sh
.venv/bin/python scripts/verify_rag_eval_evidence.py
```
실행 결과:
```text
========================================================================
 CampusMate RAG 대표 10사례 근거 전수 대조 검증 (Read-Only)
========================================================================
Data file: data/unified_campus_knowledge.json (4,782,727 bytes)
Expected SHA-256: c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e
Actual   SHA-256: c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e
[PASS] SHA-256 Hash Verified.

Loaded 1,366 documents into memory.
...
========================================================================
 [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)
========================================================================
```

---

## 5. 데이터 보존 및 격리 증거

### 5.1 v1 -> v2 마이그레이션 데이터 보존 증명
`tests/test_schedules.py::test_v1_to_v2_migration_preserves_users_and_sessions`를 통해 다음을 검증했습니다:
1. v1 마이그레이션만 적용된 임시 SQLite DB에 사용자 `v1_student`와 활성 세션 토큰을 등록.
2. `init_db`를 호출하여 v2 마이그레이션 적용 (적용 버전 수: 1).
3. 기존 사용자와 세션 토큰 해시가 손실 없이 100% 보존됨을 확인.
4. FastAPI TestClient를 통해 이전 세션 토큰으로 `/api/v1/auth/me` 호출 성공 및 `/api/v1/schedules`로 신규 일정 등록 성공 확인.
5. `init_db`를 재실행해도 추가 변경 없이 0건이 반환되는 멱등성 확인.

### 5.2 사용자 소유권 격리 (BOLA/IDOR) 증명
`tests/test_schedules.py::test_multi_user_bola_isolation`을 통해 다음을 검증했습니다:
1. User Alice와 User Bob이 각각 일정을 등록.
2. Alice의 목록에 Bob의 일정이 포함되지 않고 Bob의 목록에 Alice 일정이 포함되지 않음 (`total` 분리).
3. Alice가 Bob의 일정 UUID로 `GET`, `PATCH`, `DELETE` 요청 시 모두 `404 Not Found` 반환.
4. Alice의 요청 실패 후 Bob의 데이터와 `updated_at`이 전혀 변경되지 않고 유지됨을 확인.

### 5.3 서브프로세스 간 파일 기반 영속성 증명
`tests/test_schedules.py::test_subprocess_schedule_persistence`를 통해 다음을 검증했습니다:
1. 독립된 OS 서브프로세스 1에서 계정 등록, 로그인 및 일정 생성 완료 후 종료.
2. 완전히 새로운 별도 OS 서브프로세스 2에서 동일 DB 파일 및 발급된 토큰으로 일정을 조회 및 수정(`PATCH`) 성공.

---

## 6. R1-A 검수 보완 사항 반영 보고

Codex의 R1-A 최종 재검수 피드백 3건을 `tests/test_auth_persistence.py`에 충실히 반영했습니다:
1. **`dependency_overrides` 사본 저장 및 복원**: fixture 시작 시 `orig_overrides = dict(app.dependency_overrides)`를 저장하고 `finally`에서 `clear()` 후 `update(orig_overrides)`로 복구하도록 개선.
2. **`test_default_account_db_isolation` 검증 강화**: `config.AUTH_DB_PATH`가 실제 임시 경로를 가리키고 `data/campusmate.db`와 상이함을 assert하며, v1/v2 테이블(`personal_schedules` 포함) 생성을 명시적으로 검증.
3. **숫자 비밀번호 assert 분리**: `or` 조건문을 제거하고 `assert "12345678" not in reg_type.text`와 `assert any(err["type"] == "string_type" for err in reg_type.json()["detail"])`를 독립적으로 검증.

---

## 7. 미검증 사항 및 범위 경계

1. **R2 일정 자연어 추출**: 공지사항 본문 및 LLM 질의 결과로부터 개인 일정을 자동/반자동 추출하는 로직은 이번 R1-B 범위가 아니며, 후속 R2에서 진행합니다.
2. **R3 UI 및 브라우저 연동**: React/Streamlit 웹 인터페이스, 캘린더 시각화 뷰, 알림 모달 UI는 R3 범위입니다.
3. **알림 발송 및 외부 캘린더 연동**: 푸시/이메일 알림 및 구글/애플 캘린더 iCal 동기화는 후속 라운드 범위입니다.
4. **프로덕션 uvicorn 데몬 배포**: 본 검증은 로컬 임시 SQLite 파일 DB 및 FastAPI TestClient, subprocess 재기동 수준의 영속성을 검증한 것이며 실제 프로덕션 서버 데몬 배포는 수행하지 않았습니다.
