# R1-A 검수 — 수정 필요

검수일: 2026-09-23. 완료 보고서, 실제 구현 및 테스트를 대조했다. 스크린샷의 walkthrough.md는 현재 저장소에서 찾지 못했다. 애플리케이션 코드는 수정하지 않았다.

## 실행 결과

```sh
.venv/bin/python -m pytest tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```

74 passed, 1 warning, 9.49초. 경고는 Starlette TestClient의 AnyIO deprecated alias다. 이 통과만으로 아래 누락된 실패 경로까지 검증됐다고 볼 수 없다.

별도의 임시 SQLite와 RAG prewarm 비활성화 상태에서 HTTP 실패 경로를 검사했다. 실제 LLM 호출·배포·크롤링은 실행하지 않았다.

## 필수 수정

### 1. [P1] 입력 검증 오류에서 평문 비밀번호 반환

위치: backend/schemas.py의 UserRegisterRequest/UserLoginRequest, backend/main.py의 검증 오류 처리 경계.

가짜 비밀번호 `fake-secret-for-review-`를 7회 반복하여 register/login에 전달하면 둘 다 422지만 응답에 비밀번호 원문이 포함된다. 기본 검증 오류의 input 필드가 입력값을 돌려준다. 성공 응답만 검사하는 현재 비밀정보 테스트로는 발견할 수 없다.

인증 요청 검증 오류에서 민감 입력을 제거하고 안전한 위치·오류 유형·메시지만 반환하라. 과소/과대 비밀번호뿐 아니라 잘못된 자료형, extra field, 객체 전체가 input이 되는 오류도 검사한다. 기존 RAG 응답 계약을 보존한다.

### 2. [P1] 테스트가 기본 계정 DB 초기화 경로에 접근

위치: tests/test_auth_persistence.py:39 및 backend/main.py:79.

fixture는 get_db만 임시 DB로 바꾸지만 TestClient lifespan은 config.AUTH_DB_PATH로 init_db를 호출한다. 재시작 검증도 동일하다. 따라서 보고서의 완전 격리 주장과 달리 기본 계정 DB의 생성/마이그레이션이 가능하다. 이번 원문 테스트 재실행에서도 이 초기화 경로가 실행되었으며, 사전 해시가 없어 해당 기본 DB의 무변경을 주장하지 않는다. 기본 DB는 삭제하거나 되돌리지 않았다.

lifespan과 요청 의존성 모두 같은 임시 DB를 사용하도록 설정을 fixture 범위에서 주입하고 복구한다. 모듈 import 시 config와 os.environ을 영구 변경하지 않는다. 실패 시에도 dependency override를 finally로 원복한다. 기본 경로 접근 시 실패하는 검사로 격리를 증명한다.

### 3. [P2] 비ASCII Bearer 토큰이 401 대신 500

위치: backend/auth/security.py:44 및 backend/auth/dependencies.py의 extract_bearer_token.

TestClient에서 Authorization 헤더를 bytes로 `Bearer \\xff` 전달하면 /me가 500을 반환한다. ascii 인코딩 예외가 검증 경계를 빠져나간다. 토큰 문자 형식·길이를 검증하고 잘못된 입력은 일관되게 401로 처리한다. /me와 /logout 모두 검사한다.

### 4. [P2] 계정 DB 초기화 실패 후 정상 기동으로 표시

위치: backend/main.py:78–86.

init_db에 합성 실패를 주입해도 lifespan이 성공하고 /health는 200, status=ok를 반환했다. 계정 저장소가 준비되지 않은 서버를 정상 상태로 제공한다. 필수 DB 초기화 실패 시 startup을 실패시키거나 명시적인 readiness 정책을 구현한다. 기존 /health 정상 응답 계약을 유지하는 최소 수정으로는 startup 예외 전파가 가능하다.

### 5. [P1] SQLite WAL/SHM 파일이 Git 제외 대상에서 누락

위치: .gitignore의 SQLite 패턴.

git check-ignore로 data/campusmate.db는 제외되지만 data/campusmate.db-wal 및 data/campusmate.db-shm은 제외되지 않음을 확인했다. WAL 모드에서는 계정·세션 레코드가 WAL에 들어갈 수 있다. 사용하는 SQLite 확장자의 sidecar도 제외하고, 기존 추적 파일 유무를 확인하되 사용자 DB를 삭제하지 않는다.

## 증거 및 문서 보완

- 재시작 테스트는 같은 app 객체에 TestClient를 두 번 생성한다. 파일 DB 및 연결 재개방 보존 증거로는 유효하지만 별도 프로세스 재시작 증거라고 표현하지 않는다. 실제 프로세스를 검증하거나 보고서 표현을 정정한다.
- AUTH_DB_PATH, SESSION_EXPIRE_SECONDS, PREWARM_RAG_ON_STARTUP의 설정 예시 및 로컬 인증 API 사용 안내를 추가한다.
- 더미 bcrypt 해시는 설치 환경에서 유효하며 실제 검증 연산이 수행됨을 확인했다. 이 항목은 결함으로 등록하지 않는다.

## 판정

회원가입·로그인·세션 폐기·파일 저장 기반은 구현되었다. 위 문제를 수정하고 실패 경로 회귀를 통과하기 전에는 R1-A 완료로 승인하지 않는다. 일정 CRUD, 프론트엔드 로그인, 일정 추출·캘린더·알림은 이번 구현에 포함되지 않는다.
