# CampusMate R1-B 수정 완료 보고서

보고일: 2026-09-23  
구현 담당: Gemini  
설계·검수 총괄: Codex  

---

## 1. 개요

Codex의 R1-B 검수 결과(`docs/codex_round1b_review.md` 및 `docs/gemini_round1b_revision_prompt.md`)에서 지적된 4대 결함(동시 PATCH 데이터 유실, 소수점 초 절단으로 인한 불변식 파괴, `source_url` 형식 검증 미흡, migration 증거 부족)에 대한 재현, 수정 및 회귀 테스트 보강을 완료했습니다.

기존 일정 모델/API 계약, R1-A 계정·인증 체계, RAG API 계약을 100% 보존하였으며, R2 자연어 추출이나 UI 기능은 추가하지 않았습니다.

---

## 2. 결함별 재현 및 수정 내용

### 2.1 [P1] 동시 PATCH 데이터 유실 차단 및 수정/삭제 경합 안전성 확보
- **문제 원인**: 기존 `patch_schedule`은 트랜잭션 외부에서 행을 `SELECT`하여 `candidate_state`를 구성하고 검증한 후 `BEGIN IMMEDIATE;`를 시작하여 `UPDATE`를 수행했습니다. 두 요청이 동시에 도착해 동일한 이전 상태를 읽으면, 먼저 커밋된 필드 변경을 두 번째 요청이 이전 값으로 덮어쓰는 Lost Update 문제가 발생했습니다.
- **수정 내용**:
  - `patch_schedule` 시작 시 즉시 `conn.execute("BEGIN IMMEDIATE;")`를 호출하여 **읽기(`SELECT`) → 병합 → 검증(`validate_schedule_state`) → 쓰기(`UPDATE`) 전체를 단일 배타적 트랜잭션**으로 보호했습니다.
  - `cursor.rowcount == 0` 및 최종 행 재조회 실패 시 롤백 후 `404 Not Found`를 발생시키며, `in_tx` 플래그와 `finally`/`except` 블록을 통해 예외, 404, 422 등 모든 종료 경로에서 안전한 `ROLLBACK`을 보장했습니다.
  - `delete_schedule`도 `BEGIN IMMEDIATE;` 하에서 `DELETE`를 직접 실행하고 `cursor.rowcount == 0`일 때 404를 반환하도록 개선하여 조회-삭제 간 경합을 제거했습니다.
  - `backend/db/database.py`의 SQLite 커넥션에 `timeout=30.0` 및 `PRAGMA busy_timeout = 30000;`을 설정하여 동시 트랜잭션이 즉시 잠금 에러를 내지 않고 대기 후 순차 처리되도록 보장했습니다.
- **회귀 검증**:
  - `test_concurrent_patch_lost_update_prevention`: 두 스레드가 동일 일정에 대해 각각 title과 description을 동시에 PATCH(`threading.Barrier(2)`로 동시 진입 제어)할 때, 둘 다 200 성공하고 최종 DB에 title과 description이 모두 반영됨을 증명.
  - `test_concurrent_patch_and_delete_race`: PATCH와 DELETE 동시 경합 시 500 에러 없이 200/204/404로 안전 처리됨을 검증.

### 2.2 [P2] 일시 소수점 초 정밀도 보존 및 변환 범위 오버플로우 안전 처리
- **문제 원인**: `datetime.fromisoformat`은 마이크로초를 수용했으나 `strftime("%Y-%m-%dT%H:%M:%SZ")`로 포맷하면서 소수점 초를 절단했습니다. 이로 인해 마이크로초 단위로 구분된 `start < end` 일정이 저장 후 `start == end`가 되어, 제목만 PATCH해도 시간 불변식 위반(422)으로 실패했습니다. 또한 연도 한계 초과 시 `OverflowError`로 인한 500 오류 가능성이 있었습니다.
- **수정 내용**:
  - `backend/schedules/service.py`의 `validate_and_normalize_datetime_str`에서 `dt_utc.microsecond != 0`인 경우 `.%06fZ` 형식으로 마이크로초 정밀도를 온전히 보존하도록 수정했습니다 (`microsecond == 0`이면 기존처럼 `Z`로 포맷).
  - 저장된 정규화 문자열이 마이크로초를 유지하므로, 저장 후 재조회 및 PATCH 시에도 동일한 마이크로초가 유지되어 `start < end` 불변식이 100% 유지됩니다.
  - 소수점 초까지 동일하여 실제로 `start == end`인 입력은 저장 전 422로 엄격히 거부합니다.
  - 연도 지원 범위(1000~9999년) 검증을 추가하고, UTC/서울 변환 시 `OverflowError`를 포괄 처리하여 500 대신 안전한 `422`를 반환하도록 보강했습니다.
- **회귀 검증**:
  - `test_datetime_fractional_precision_and_overflow`: Codex의 재현 입력(`.100000+09:00`, `.900000+09:00`)으로 201 저장 후, 제목만 PATCH 시 200 성공 및 마이크로초 보존 확인.
  - 동일 마이크로초(start == end) 422 거부 확인, 연도 오버플로우 422 안전 거부 확인.

### 2.3 [P2] `source_url` 엄격한 호스트 및 스키마 검증
- **문제 원인**: 기존에는 단순 `http://` 또는 `https://` 접두사 여부만 검사하여 `https://`, `https://not a host`, `http://?query` 등이 유효한 URL로 통과되었습니다.
- **수정 내용**:
  - `backend/schemas.py`의 `_validate_source_url`에 `urllib.parse.urlsplit` 기반의 엄격한 유효성 검증을 도입했습니다.
  - 공백 문자 포함 시 즉시 거부, `scheme.lower() in ("http", "https")` 확인 (ftp, javascript 등 거부).
  - 유효한 호스트 존재 여부 및 호스트 라벨 형식 정규식(`^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$`) 검증.
  - `localhost`, IPv4(`127.0.0.1`), 표준 2단계 이상 도메인 라벨(`hansung.ac.kr`)만 허용.
  - CREATE와 PATCH에 동일 적용하며, nullable(`None`, `""`) 동작 유지.
- **회귀 검증**:
  - `test_source_url_strict_validation`: `https://`, `https://not a host`, `http://?query`, `ftp://example.com`, 공백 포함 URL이 CREATE 및 PATCH 모두에서 422로 차단됨을 검증. 정상 URL(`https://www.hansung.ac.kr`, `http://localhost:8000`) 및 `None` 정상 허용 확인.

### 2.4 [P2] 마이그레이션 증거 보강 (실제 비밀번호 재로그인 및 실패 롤백)
- **문제 원인**: 기존 v1→v2 마이그레이션 테스트는 더미 비밀번호 해시를 사용하여 실제 비밀번호를 통한 재로그인을 검증하지 않았으며, v2 마이그레이션 중간 실패 시의 원자적 롤백 회귀 테스트가 누락되어 있었습니다.
- **수정 내용**:
  - `tests/test_schedules.py::test_v1_to_v2_migration_preserves_users_and_sessions`: `backend.auth.security.hash_password`로 생성한 실제 bcrypt 해시를 가진 v1 사용자를 삽입. v2 적용 후 기존 세션 토큰 유효성 검증과 더불어 원래 평문 비밀번호로 `/api/v1/auth/login`을 호출하여 정상 재로그인 및 신규 토큰 발급, 신규 일정 생성, 반복 마이그레이션 멱등성을 전수 검증.
  - `tests/test_schedules.py::test_v2_migration_synthetic_failure_rollbacks_cleanly` 추가: v2 마이그레이션 SQL 목록에 의도적 문법 오류를 주입하여 `init_db` 실행 시 `OperationalError` 발생 확인. 트랜잭션 롤백으로 `schema_migrations`에 2가 기록되지 않고, `personal_schedules` 테이블도 생성되지 않은 채 v1 사용자와 세션이 온전히 보존됨을 확인. 오류 복구 후 재실행 시 정상 v2가 적용됨을 검증.

---

## 3. 테스트 실행 결과

모든 테스트는 격리된 임시 SQLite 파일 DB 및 `.venv/bin/python` 환경에서 실행되었습니다.

### 3.1 신규 및 보강된 일정 테스트 슈트 (`tests/test_schedules.py`)
```sh
.venv/bin/python -m pytest tests/test_schedules.py -v
```
실행 결과:
```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0 -- /Users/jwlee/study1/aisw/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/jwlee/study1/aisw
plugins: langsmith-0.12.4, anyio-4.15.1
collected 13 items                                                             

tests/test_schedules.py::test_5_schedule_kinds_crud_lifecycle PASSED     [  7%]
tests/test_schedules.py::test_multi_user_bola_isolation PASSED           [ 15%]
tests/test_schedules.py::test_server_managed_fields_confirmed_and_auth_gate PASSED [ 23%]
tests/test_schedules.py::test_date_and_time_strict_contract PASSED       [ 30%]
tests/test_schedules.py::test_patch_semantics_and_atomicity PASSED       [ 38%]
tests/test_schedules.py::test_calendar_and_list_filtering PASSED         [ 46%]
tests/test_schedules.py::test_v1_to_v2_migration_preserves_users_and_sessions PASSED [ 53%]
tests/test_schedules.py::test_v2_migration_synthetic_failure_rollbacks_cleanly PASSED [ 61%]
tests/test_schedules.py::test_subprocess_schedule_persistence PASSED     [ 69%]
tests/test_schedules.py::test_concurrent_patch_lost_update_prevention PASSED [ 76%]
tests/test_schedules.py::test_concurrent_patch_and_delete_race PASSED    [ 84%]
tests/test_schedules.py::test_datetime_fractional_precision_and_overflow PASSED [ 92%]
tests/test_schedules.py::test_source_url_strict_validation PASSED        [100%]

======================== 13 passed, 1 warning in 15.75s ========================
```

### 3.2 전체 회귀 결합 테스트
```sh
.venv/bin/python -m pytest tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```
실행 결과:
```text
........................................................................ [ 78%]
....................                                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  /Users/jwlee/study1/aisw/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

92 passed, 1 warning in 25.38s
```
- 기존 79개 + R1-B 13개 = **총 92개 테스트 전수 통과**.
- Starlette TestClient의 AnyIO deprecation 경고 외 기능 에러 0건.

### 3.3 RAG 대표 10사례 근거 검증 스크립트
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
...
 [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)
========================================================================
```

---

## 4. 데이터베이스 및 런타임 격리 확인

1. **테스트 환경 격리**: 모든 테스트는 `tmp_path` 기반의 임시 SQLite DB를 생성하여 `AUTH_DB_PATH`를 주입하고, `PREWARM_RAG_ON_STARTUP=False`로 무거운 RAG 로딩 없이 안전하게 실행되었습니다.
2. **저장소 파일 불변성**: `data/` 디렉터리 내의 기존 데이터 파일 및 Chroma 벡터스토어는 전혀 수정되거나 초기화되지 않았습니다.
3. **Git 제외 상태 유지**: 모든 임시 `.db`, WAL/SHM sidecar 파일은 `.gitignore` 규칙에 따라 Git 추적에서 제외되었습니다.

---

## 5. 변경 파일 요약

| 파일 | 변경 요약 |
|---|---|
| `backend/schemas.py` | `_validate_source_url`에 `urlsplit` 기반 스키마/호스트/공백 엄격 검증 적용 |
| `backend/schedules/service.py` | 마이크로초 정밀도 보존 및 오버플로우 422 처리, `patch_schedule` 및 `delete_schedule`을 `BEGIN IMMEDIATE` 기반 직렬화 트랜잭션으로 보호 |
| `backend/db/database.py` | `timeout=30.0` 및 `PRAGMA busy_timeout = 30000;` 설정으로 동시 트랜잭션 대기 지원 |
| `tests/test_schedules.py` | 동시 PATCH 유실 방지, PATCH/DELETE 경합, 마이크로초 보존/오버플로우, 엄격 URL 검증, 실제 비밀번호 재로그인, 합성 실패 롤백 등 5개 테스트 추가 및 보강 |
| `docs/campusmate_schedule_api_guide.md` | 일시 소수점 정밀도 보존 정책 및 `source_url` 검증 규칙 보강 |
| `docs/gemini_round1b_revision_report.md` | 본 수정 완료 보고서 작성 |

---

## 6. 미검증 범위 및 후속 라운드

- **R2 일정 자연어 추출**: 학사 공지 본문으로부터의 규칙/LLM 기반 일정 추출은 R2 범위입니다.
- **R3 프론트엔드 UI**: 캘린더 화면, 일정 생성 모달 및 로그인 연동 UI는 R3 범위입니다.
- **배포 및 외부 알림**: uvicorn 서비스 데몬 배포, 백그라운드 푸시 알림 발송은 후속 마일스톤에서 진행합니다.
