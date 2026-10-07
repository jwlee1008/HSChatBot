# CampusMate R1-A 완료 보고서 — 계정·인증·영속 저장 기반 (Gemini)

- **작성 일자:** 2026-09-23
- **작성자:** 구현 담당 (Gemini)
- **검수 수신:** 설계·검수 총괄 (Codex)
- **대상 작업:** `docs/gemini_round1a_prompt.md` (R1-A 계정·인증·영속 저장 기반)

---

## 1. 개요 및 구현 범위

R0 검수 완료 상태와 기존 서비스 계약(`/health`, `/api/query`, `/api/retrieve`)을 온전히 보존하면서, 파일 기반 SQLite 영속 저장소와 서버 저장형 Opaque Bearer 세션 토큰 기반의 계정 및 인증 체계(R1-A)를 신설하였습니다.
개인 일정 CRUD(R1-B), 추출/캘린더 UI 및 알림은 구현 범위에서 엄격히 제외하였습니다.

---

## 2. 주요 설계 선택 및 아키텍처

### 2.1 파일 기반 SQLite 영속 저장소 (`backend/db/`)
- **DB 경로 주입 및 격리:** Chroma 벡터 DB와 완전 분리된 `config.AUTH_DB_PATH`(기본: `data/campusmate.db`)를 사용하며, 테스트 시에는 임시 디렉터리 경로를 주입합니다.
- **연결 제약 및 무결성:** 모든 SQLite 커넥션에 `PRAGMA foreign_keys = ON;` 및 `PRAGMA journal_mode = WAL;`을 강제 적용하고 `sqlite3.Row` 팩토리를 설정하였습니다. 모든 쿼리는 `?` 파라미터 바인딩을 사용합니다.
- **버전 관리형 마이그레이션 (`backend/db/migrations.py`):**
  - `schema_migrations` 테이블로 버전을 추적하며, 임의의 drop/reset 없이 기존 데이터를 보존합니다.
  - **Version 1 스키마:**
    - `users`: `id` (UUID PK), `username` (TEXT UNIQUE NOT NULL), `password_hash` (TEXT NOT NULL), `created_at` (TEXT UTC ISO), `updated_at` (TEXT UTC ISO).
    - `sessions`: `id` (UUID PK), `user_id` (TEXT FK -> users.id CASCADE), `token_hash` (TEXT UNIQUE NOT NULL), `created_at` (TEXT UTC ISO), `expires_at` (TEXT UTC ISO), `revoked_at` (TEXT NULL).
    - 인덱스: `idx_users_username`, `idx_sessions_token_hash`, `idx_sessions_user_id`.
  - `init_db`를 반복 실행해도 이미 적용된 버전은 건너뛰어(Idempotent) 데이터가 안전하게 유지됩니다.

### 2.2 사용자명(username) 정책
- **일반 ID 정의:** 학번이나 학교 이메일 소유권 검증을 주장하지 않는 일반 로그인 아이디입니다.
- **정규화 및 유효성:** 앞뒤 공백 제거 및 소문자 정규화(`.strip().lower()`)를 적용하며, 영문·숫자·`_`·`.`·`-` 문자 3~50자(`^[a-zA-Z0-9_.-]{3,50}$`)만 허용합니다. 공백이 중간에 포함되거나 범위를 벗어나면 422 Unprocessable Entity를 반환합니다.
- **중복 및 동시성 충돌:** DB `username UNIQUE` 제약으로 처리하며, 충돌 시 `409 Conflict` (`"이미 등록된 사용자명입니다."`)를 반환합니다.

### 2.3 비밀번호 보안 정책
- **라이브러리:** 검증된 공식 `bcrypt` (v5.0.0) 라이브러리를 사용합니다.
- **긴 유니코드(한글 등) 안전 처리:** bcrypt의 72바이트 입력 길이 제한을 극복하고 절단(truncation) 공격을 방지하기 위해, UTF-8 인코딩 후 **SHA-256 사전 해싱(Pre-hashing, 32바이트)**을 거쳐 `bcrypt.hashpw`를 적용합니다.
- **길이 제약:** 최소 8자 이상, 최대 128자 이하로 제한하여 DoS를 방지하고 긴 패스프레이즈를 수용합니다.
- **비밀정보 미노출:** 평문 비밀번호 및 해시값은 응답 본문이나 로그에 일절 노출되지 않습니다.
- **타이밍 공격 완화:** 존재하지 않는 사용자로 로그인 시도 시에도 더미 해시 검증을 수행한 뒤, 비밀번호 불일치와 완전히 동일한 안전한 에러 문구(`"사용자명 또는 비밀번호가 올바르지 않습니다."`, 401)를 반환합니다.

### 2.4 서버 저장형 Opaque Bearer 세션 토큰 (`backend/auth/`)
- **토큰 생성:** `secrets.token_urlsafe(32)`를 통한 256비트 암호학적 난수 생성.
- **DB 해시 저장:** 데이터베이스 `sessions` 테이블에는 토큰의 **SHA-256 hex digest(64자)만 저장**하며 원문 토큰은 DB에 기록하지 않습니다.
- **만료 및 폐기:**
  - 기본 만료 시간은 24시간(`config.SESSION_EXPIRE_SECONDS = 86400`)이며 설정으로 변경 가능합니다.
  - 로그아웃(`POST /api/v1/auth/logout`) 시 해당 세션의 `revoked_at`에 현재 UTC 시각을 기록하여 즉시 무효화합니다. 동일 사용자의 다른 활성 세션(다른 기기/브라우저)은 영향을 받지 않고 유지됩니다.
- **클라이언트 전송:** `Authorization: Bearer <token>` 헤더 전송 방식이며, 로그인 응답에는 `Cache-Control: no-store` 헤더를 적용합니다.

### 2.5 RAG 의존성 분리 및 응답 계약 보존
- `config.PREWARM_RAG_ON_STARTUP` 설정을 도입하여, 테스트 환경에서는 RAG 백그라운드 사전 적재를 건너뛰도록 격리하였습니다.
- `/health`, `/api/query`, `/api/retrieve` 엔드포인트의 기존 계약은 100% 보존되었습니다.

---

## 3. API 엔드포인트 계약 준수 현황

| Method | 경로 | 상태 코드 | 주요 동작 및 검증 결과 |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 201 Created | username/password 수신, 계정 생성, id/username/created_at 반환. 자동 로그인 안 함 |
| `POST` | `/api/v1/auth/login` | 200 OK | 자격 증명 검증, access_token/token_type/expires_at 반환, `Cache-Control: no-store` 적용 |
| `GET` | `/api/v1/auth/me` | 200 OK | 유효 Bearer 토큰으로 본인 공개 정보(id, username, created_at) 조회 |
| `POST` | `/api/v1/auth/logout` | 204 No Content | 현재 세션 폐기(`revoked_at` 설정), 동일 계정 타 세션 유지 |

- **오류 상태 코드:**
  - 중복 username / 정규화 충돌: `409 Conflict`
  - 제약 위반, 형식 오류, 불법 필드 주입(extra field): `422 Unprocessable Entity`
  - 자격 증명 오류, 토큰 누락, 형식 오류, 변조, 만료, 폐기 토큰: `401 Unauthorized`
  - DB 원시 예외 및 스택트레이스 응답 미노출

---

## 4. 변경 파일 목록

| 파일 경로 | 구분 | 주요 내용 |
|---|---|---|
| `.gitignore` | [MODIFY] | `*.db`, `*.sqlite`, `data/*.db` 패턴 추가하여 런타임 SQLite 파일 추적 방지 |
| `requirements.txt` | [MODIFY] | `bcrypt>=4.0.0` 의존성 추가 |
| `config.py` | [MODIFY] | `AUTH_DB_PATH`, `SESSION_EXPIRE_SECONDS`, `PREWARM_RAG_ON_STARTUP`, 길이 제한 상수 추가 |
| `backend/schemas.py` | [MODIFY] | `UserRegisterRequest`, `UserLoginRequest`, `UserResponse`, `TokenResponse` 추가 (`extra="forbid"`) |
| `backend/db/database.py` | [NEW] | SQLite 연결 팩토리 (`PRAGMA foreign_keys = ON;`, `row_factory = Row`), `get_db` 의존성 |
| `backend/db/migrations.py` | [NEW] | 버전 관리형 스키마 마이그레이션 (`schema_migrations`, v1 `users`/`sessions` 생성, idempotent) |
| `backend/db/__init__.py` | [NEW] | DB 패키지 export |
| `backend/auth/security.py` | [NEW] | SHA-256 pre-hash bcrypt 해싱/검증, opaque 토큰 생성/해싱, username 정규화 |
| `backend/auth/service.py` | [NEW] | `AuthService`: register(409), login(401 타이밍 보호), get_user_by_session_token, logout |
| `backend/auth/dependencies.py` | [NEW] | `extract_bearer_token`, `get_current_user` 의존성 (R1-B 재사용 가능) |
| `backend/auth/__init__.py` | [NEW] | auth 패키지 export |
| `backend/routers/auth.py` | [NEW] | `/api/v1/auth` 라우터 (register, login, me, logout) |
| `backend/routers/__init__.py` | [NEW] | routers 패키지 export |
| `backend/main.py` | [MODIFY] | auth router 마운트, lifespan 내 `init_db` 실행 및 RAG 조건부 사전 적재 |
| `tests/test_auth_persistence.py` | [NEW] | 7대 요구조건(수명주기, 유효성/충돌, 토큰보안/만료, 다중세션격리, 재시작보존, 비밀정보미노출, 헬스체크) 전수 검증 (10개 테스트) |

---

## 5. 실행 명령 및 실제 검증 결과

### 5.1 신규 인증·영속성 테스트 슈트 (`tests/test_auth_persistence.py`)

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_auth_persistence.py -v
  ```
- **실행 결과:**
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0 -- /Users/jwlee/study1/aisw/.venv/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/jwlee/study1/aisw
  plugins: langsmith-0.12.4, anyio-4.15.1
  collecting ... collected 10 items                                                             

  tests/test_auth_persistence.py::test_auth_full_lifecycle PASSED          [ 10%]
  tests/test_auth_persistence.py::test_duplicate_and_normalization_registration PASSED [ 20%]
  tests/test_auth_persistence.py::test_invalid_username_and_password_validation PASSED [ 30%]
  tests/test_auth_persistence.py::test_long_unicode_password_support PASSED [ 40%]
  tests/test_auth_persistence.py::test_login_failure_identical_message PASSED [ 50%]
  tests/test_auth_persistence.py::test_token_security_and_expiration PASSED [ 60%]
  tests/test_auth_persistence.py::test_multi_user_and_multi_session_isolation PASSED [ 70%]
  tests/test_auth_persistence.py::test_persistence_across_restarts_and_repeat_migrations PASSED [ 80%]
  tests/test_auth_persistence.py::test_no_plaintext_passwords_or_tokens_stored_and_no_hash_leaks PASSED [ 90%]
  tests/test_auth_persistence.py::test_health_check_contract_preserved PASSED [100%]

  ======================== 10 passed, 1 warning in 7.00s =========================
  ```

### 5.2 프로세스 재시작 및 영속성 보존 증거
`tests/test_auth_persistence.py::test_persistence_across_restarts_and_repeat_migrations`를 통해 다음을 증명하였습니다:
1. `client1`에서 사용자 등록 및 토큰 발급 후 커넥션 완전 종료.
2. `init_db`를 추가 2회 반복 호출하여 `schema_migrations` 확인 및 기존 테이블 drop/reset 없이 0건 추가 적용 확인.
3. 완전히 새로운 `client2`를 생성하여 동일 파일 DB에 연결했을 때, 기존 토큰으로 `/api/v1/auth/me` 호출 시 200 OK 및 동일한 사용자 UUID와 정보를 정상 반환.
4. 기존 비밀번호로 신규 로그인 시에도 200 OK 정상 인증 확인.

### 5.3 기존 회귀 테스트 슈트 무결성 확인
- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
  ```
- **실행 결과:**
  ```text
  ................................................................         [100%]
  64 passed, 1 warning in 4.46s
  ```

### 5.4 R0 RAG 평가 근거 검증 무결성 확인
- **실행 명령:**
  ```bash
  .venv/bin/python scripts/verify_rag_eval_evidence.py
  ```
- **실행 결과:**
  ```text
  [PASS] SHA-256 Hash Verified.
  [최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)
  ```

---

## 6. 미검증 사항 및 남은 범위 (R1-B 안내)

1. **개인 일정 CRUD 및 시간 필드 검증 (R1-B):**
   - 본 작업은 계정 및 인증 토큰 발급까지만 구현하였으며, 개인 캘린더 일정 모델(`PersonalSchedule`), 시간 필드(Date-only vs Datetime) 검증 및 소유권 격리(BOLA/IDOR 차단) CRUD는 R1-B에서 구현됩니다.
2. **쿠키 기반 인증 및 프론트엔드 연동:**
   - 본 API는 순수 `Authorization: Bearer` 헤더 API로 구현되었으며, 웹 브라우저 쿠키/세션스토리지 저장 및 프론트엔드 화면 연동은 후속 단계에서 검수합니다.
3. **운영용 PostgreSQL 마이그레이션:**
   - 로컬 MVP는 파일 기반 SQLite로 완결되었으며, 클라우드 배포 시 PostgreSQL 전환은 후속 인프라 작업으로 분리되어 있습니다.
4. **실제 LLM 모델 호출 및 배포:**
   - R1-A 요구사항에 따라 실제 Gemini API 호출 및 클라우드 배포는 수행하지 않았습니다.

---

**보고서 경로:** `docs/gemini_round1a_report.md`  
Codex의 R1-A 검수를 요청합니다.
