# CampusMate R1-A 수정 라운드 완료 보고서 (Gemini)

- **작성 일자:** 2026-09-23
- **작성자:** 구현 담당 (Gemini)
- **검수 수신:** 설계·검수 총괄 (Codex)
- **대상 검토 문서:** `docs/codex_round1a_review.md` 및 `docs/gemini_round1a_prompt.md`

---

## 1. 개요 및 수정 범위

Codex의 R1-A 검수 결과(`docs/codex_round1a_review.md`)에서 지적된 5가지 필수 수정 사항과 증거/문서 보완 요구를 전수 해결하였습니다.
개인 일정 CRUD, 프론트엔드 UI, 일정 추출 및 알림 기능은 R1-B 이후 범위로서 일절 추가하지 않았으며, 기존 서비스 계약(`/health`, `/api/query`, `/api/retrieve`)을 100% 보존하였습니다.

---

## 2. 지적사항별 수정 내역

### 2.1 [P1] 입력 검증 오류(422)에서 평문 비밀번호 및 민감 입력 제거
- **문제점:** Pydantic v2 기본 동작으로 인해 과소/과대 비밀번호, 잘못된 자료형 등 422 오류 발생 시 응답 JSON의 `input` 필드에 평문 비밀번호 문자열이 그대로 노출되었음.
- **수정 조치:**
  - `backend/main.py`에 `@app.exception_handler(RequestValidationError)`를 구현하여, `/api/v1/auth`로 시작하는 인증 요청에 대해 응답의 `detail` 목록에서 `input` 필드를 완전히 제거하고 안전한 위치(`loc`), 유형(`type`), 메시지(`msg`), 제한값(`ctx`)만 반환하도록 처리하였습니다.
  - Pydantic 커스텀 validator에서 발생한 `ValueError` 객체가 `ctx["error"]`에 포함될 경우 발생하는 JSON 직렬화 오류를 방지하기 위해 `jsonable_encoder` 및 예외 객체 문자열 변환 처리를 적용하였습니다.
  - 기존 RAG 엔드포인트(`/api/query`, `/api/retrieve`)에 대한 요청은 FastAPI 기본 핸들러(`request_validation_exception_handler`)로 위임하여 기존 응답 계약을 완벽히 보존하였습니다.

### 2.2 [P1] 테스트의 lifespan 및 요청 DB 경로 완전 임시 디렉터리 격리
- **문제점:** 기존 테스트 fixture가 `get_db`만 임시 DB로 오버라이드하고 `TestClient`의 lifespan은 `config.AUTH_DB_PATH`(기본 `data/campusmate.db`)로 `init_db`를 호출하여 기본 DB에 접근할 수 있었음.
- **수정 조치:**
  - `tests/test_auth_persistence.py` 모듈 상단의 전역 환경변수 영구 변경(`os.environ[...] = ...`)을 완전히 제거하였습니다.
  - `isolated_auth_env` fixture를 신설하여, TestClient lifespan 진입 전에 `config.AUTH_DB_PATH = str(test_db)`, `os.environ["AUTH_DB_PATH"] = str(test_db)`, `config.PREWARM_RAG_ON_STARTUP = False`를 주입하여 lifespan의 `init_db`와 요청의 `get_db`가 동일한 임시 DB만 사용하도록 격리하였습니다.
  - `try ... finally` 블록을 통해 테스트 성공/실패 여부와 무관하게 `config.AUTH_DB_PATH`, `config.PREWARM_RAG_ON_STARTUP`, `os.environ`, `app.dependency_overrides`를 원래 값으로 100% 안전하게 복원하도록 보장하였습니다.
  - `test_default_account_db_isolation` 테스트를 추가하여 기본 계정 DB 경로가 아닌 임시 DB 파일에만 테이블이 생성되고 사용됨을 증명하였습니다.

### 2.3 [P2] 비ASCII 및 Malformed Bearer 토큰 401 차단
- **문제점:** TestClient에서 bytes 헤더 `Bearer \xff` 전송 시 `backend/auth/security.py`의 `hash_session_token`에서 `UnicodeEncodeError`가 발생하여 500 오류가 반환되었음.
- **수정 조치:**
  - `backend/auth/dependencies.py`의 `extract_bearer_token`에 토큰 ASCII 검증(`token.isascii()`), 길이 범위 검증(`16 <= len <= 256`), RFC 6750 호환 문자열 정규식 검증(`^[a-zA-Z0-9_.~+/-]+=*$`)을 추가하였습니다.
  - `backend/auth/security.py`의 `hash_session_token`에 `UnicodeEncodeError` 방어 로직(`token.encode("utf-8", errors="replace")`)을 적용하였습니다.
  - 비ASCII 헤더, 잘못된 형식, 이모지, 과대/과소 토큰이 `/api/v1/auth/me`와 `/api/v1/auth/logout` 모두에서 500이 아닌 일관된 `401 Unauthorized`로 차단됨을 테스트(`test_malformed_and_non_ascii_bearer_tokens_return_401`)로 검증하였습니다.

### 2.4 [P2] 계정 DB 초기화 실패 시 기동 중단 (예외 전파)
- **문제점:** `backend/main.py`의 lifespan에서 `init_db` 실패 시 `logger.error`만 남기고 예외를 삼켜, 계정 저장소가 없는 상태에서도 서버가 정상 기동되고 `/health`가 200을 반환하였음.
- **수정 조치:**
  - `backend/main.py` lifespan에서 `init_db` 예외를 삼키던 `try-except`를 제거하여, DB 마이그레이션 실패 시 예외가 즉시 전파되어 서버 startup이 명확히 중단되도록 수정하였습니다.
  - `test_db_migration_failure_fails_startup` 테스트를 추가하여, `init_db`에 합성 `OperationalError`를 주입했을 때 TestClient startup이 예외를 발생시키며 즉시 실패함을 검증하였습니다.

### 2.5 [P1] SQLite WAL/SHM sidecar 파일 Git 제외
- **문제점:** `.gitignore`에 `*.db`만 등록되어 있어, WAL 모드 동작 시 생성되는 `*.db-wal`, `*.db-shm` 파일이 git 추적 대상에 노출되었음.
- **수정 조치:**
  - `.gitignore`에 `*.db-wal`, `*.db-shm`, `*.db-journal`, `*.sqlite-wal`, `*.sqlite-shm`, `data/*.db*`, `data/*.sqlite*`를 명시적으로 추가하였습니다.
  - `git check-ignore` 명령으로 `data/campusmate.db-wal`, `data/campusmate.db-shm` 등 모든 sidecar가 완전히 제외됨을 확인하였습니다.
  - 기존 git 추적 파일 목록(`git ls-files`)을 확인하여 사용자의 기존 DB 파일이 추적되지 않음을 검증하였으며, 사용자 DB 파일은 일절 삭제하거나 수정하지 않았습니다.

### 2.6 설정 예시, 로컬 가이드 및 실제 프로세스 재시작 영속성 검증
- **가이드 문서 작성:** [`docs/campusmate_auth_api_guide.md`](file:///Users/jwlee/study1/aisw/docs/campusmate_auth_api_guide.md)를 작성하여 `AUTH_DB_PATH`, `SESSION_EXPIRE_SECONDS`, `PREWARM_RAG_ON_STARTUP` 설정 예시와 uvicorn 로컬 기동법, curl 예시를 상세히 문서화하였습니다.
- **독립 OS 프로세스 재시작 검증 (`test_real_subprocess_restart_persistence`):**
  - 단순 동일 app TestClient 재생성이 아닌, `subprocess.run`을 통해 완전히 별개의 독립 Python 인터프리터 프로세스 2개를 순차 실행하여, 프로세스 1에서 발급된 Opaque 토큰과 계정이 프로세스 2에서 정상적으로 인증(200 OK)됨을 증명하였습니다.
  - 기존 동일 app 재개방 테스트는 `test_connection_reopening_and_repeat_migrations`로 명칭을 정정하여 "연결 재개방 및 반복 마이그레이션 보존 증거"임을 정확히 규정하였습니다.

---

## 3. 변경 파일 목록

| 파일 경로 | 구분 | 주요 수정 내용 |
|---|---|---|
| `.gitignore` | [MODIFY] | `*.db-wal`, `*.db-shm`, `*.db-journal`, `data/*.db*` 등 SQLite sidecar 패턴 추가 |
| `backend/main.py` | [MODIFY] | 422 입력 검증 오류 sanitizer 예외 핸들러 등록, lifespan 내 `init_db` 실패 시 기동 중단 예외 전파 |
| `backend/auth/dependencies.py` | [MODIFY] | `extract_bearer_token`에 ASCII 검증, 길이(16~256자) 및 RFC 6750 문자 형식 정규식 검증 추가 |
| `backend/auth/security.py` | [MODIFY] | `hash_session_token` 내 `UnicodeEncodeError` 방어 인코딩 적용 |
| `tests/test_auth_persistence.py` | [MODIFY] | 15개 테스트로 확대: 완전 임시 DB lifespan 격리, 기본 DB 비접근 검증, 422 비밀번호 미노출(과대/과소/자료형/extra/객체) 검증, 비ASCII 토큰 401 검증, startup 실패 검증, subprocess 실제 프로세스 재시작 검증 |
| `docs/campusmate_auth_api_guide.md` | [NEW] | 설정 예시, 로컬 uvicorn 기동, curl 사용법 및 영속성 구조 안내 문서 |
| `docs/gemini_round1a_revision_report.md` | [NEW] | Codex 검수 지적 1~5번 및 문서 보완 조치 완료 보고서 (본 문서) |

---

## 4. 실행 명령 및 실제 검증 결과

### 4.1 신규 인증·영속성 테스트 슈트 (15개 테스트 전수 통과)

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
  collecting ... collected 15 items                                                             

  tests/test_auth_persistence.py::test_default_account_db_isolation PASSED [  6%]
  tests/test_auth_persistence.py::test_422_validation_error_strips_sensitive_password_input PASSED [ 13%]
  tests/test_auth_persistence.py::test_malformed_and_non_ascii_bearer_tokens_return_401 PASSED [ 20%]
  tests/test_auth_persistence.py::test_db_migration_failure_fails_startup PASSED [ 26%]
  tests/test_auth_persistence.py::test_auth_full_lifecycle PASSED          [ 33%]
  tests/test_auth_persistence.py::test_duplicate_and_normalization_registration PASSED [ 40%]
  tests/test_auth_persistence.py::test_invalid_username_and_password_validation PASSED [ 46%]
  tests/test_auth_persistence.py::test_long_unicode_password_support PASSED [ 53%]
  tests/test_auth_persistence.py::test_login_failure_identical_message PASSED [ 60%]
  tests/test_auth_persistence.py::test_token_expiration PASSED             [ 66%]
  tests/test_auth_persistence.py::test_multi_user_and_multi_session_isolation PASSED [ 73%]
  tests/test_auth_persistence.py::test_connection_reopening_and_repeat_migrations PASSED [ 80%]
  tests/test_auth_persistence.py::test_real_subprocess_restart_persistence PASSED [ 86%]
  tests/test_auth_persistence.py::test_no_plaintext_passwords_or_tokens_stored_and_no_hash_leaks PASSED [ 93%]
  tests/test_auth_persistence.py::test_health_check_contract_preserved PASSED [100%]

  ======================== 15 passed, 1 warning in 13.35s ========================
  ```

### 4.2 전체 회귀 및 인증 결합 실행 (79개 테스트 전수 통과)

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
  ```
- **실행 결과:**
  ```text
  ........................................................................ [ 91%]
  .......                                                                  [100%]
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:53
    /Users/jwlee/study1/aisw/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  79 passed, 1 warning in 15.38s
  ```

### 4.3 Git Sidecar 제외 검증 결과

- **실행 명령:**
  ```bash
  git check-ignore data/campusmate.db data/campusmate.db-wal data/campusmate.db-shm test.db test.db-wal test.db-shm
  ```
- **결과:** 6개 경로 모두 정상 제외됨 (종료 코드 0).

---

## 5. 미검증 사항 및 남은 범위 (R1-B 안내)

1. **개인 일정 CRUD 및 시간 필드 검증 (R1-B):**
   - 계정 인증 토큰을 통해 사용자별 일정을 격리하고 저장하는 `PersonalSchedule` 모델 및 CRUD 엔드포인트는 R1-B에서 구현합니다.
2. **쿠키 기반 인증 및 프론트엔드 연동:**
   - 본 API는 순수 `Authorization: Bearer` 헤더 API로 구현되었으며, 브라우저 쿠키 및 프론트엔드 연동은 후속 단계에서 진행합니다.
3. **운영용 PostgreSQL 전환:**
   - 로컬 MVP는 파일 기반 SQLite로 완결되었으며, 운영 DB 마이그레이션은 후속 인프라 작업으로 분리되어 있습니다.
4. **실제 LLM 모델 호출 및 클라우드 배포:**
   - 지침에 따라 실제 Gemini API 호출 및 클라우드 배포는 수행하지 않았습니다.

---

**보고서 경로:** `docs/gemini_round1a_revision_report.md`  
Codex의 R1-A 최종 승인을 요청합니다.
