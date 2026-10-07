> 역사 기록: 2026-09-27 제품 범위가 챗봇으로 변경되었습니다. 개인 일정·인증·캘린더·알림 계획은 비활성 보관 상태입니다. 현재 범위는 `docs/campusmate_chatbot_scope_20260927.md`를 따릅니다.

# CampusMate 인증 API 및 로컬 실행 가이드 (R1-A)

본 문서는 CampusMate R1-A 계정·인증·영속 저장 기반의 설정 예시, 로컬 서버 기동 및 REST API 사용법을 안내합니다.

---

## 1. 환경 설정 및 구성 (`config.py`)

CampusMate는 `.env` 파일 또는 환경 변수를 통해 계정 DB 및 세션 수명 주기를 제어합니다.

### 1.1 주요 환경 변수

| 환경 변수명 | 기본값 | 설명 |
|---|---|---|
| `AUTH_DB_PATH` | `data/campusmate.db` | 계정(`users`) 및 세션(`sessions`)을 저장하는 SQLite 파일 경로 |
| `SESSION_EXPIRE_SECONDS` | `86400` (24시간) | 서버 저장형 Opaque Bearer 세션 토큰의 유효 기간(초) |
| `PREWARM_RAG_ON_STARTUP` | `true` | 서버 시작 시 RAG 모델(Chroma/SentenceTransformer) 백그라운드 사전 로드 여부 (`false` 시 경량 기동) |

### 1.2 `.env` 설정 예시 (비밀값 없는 예시)

```bash
# 계정 및 인증 설정
AUTH_DB_PATH=data/campusmate.db
SESSION_EXPIRE_SECONDS=86400
PREWARM_RAG_ON_STARTUP=true

# RAG 모델 설정 (기존 설정 유지)
LLM_PROVIDER=local
CHROMA_COLLECTION_NAME=campus_knowledge
```

---

## 2. 로컬 실행 방법

### 2.1 일반 운영 기동 (RAG 사전 로드 포함)
```bash
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
- 서버 기동 시 SQLite 마이그레이션이 자동 실행되어 `users`, `sessions`, `schema_migrations` 테이블이 생성/확인됩니다.
- RAG 모델이 백그라운드 태스크로 사전 로드되어 챗봇 검색 및 질의가 준비됩니다.

### 2.2 경량/인증 전용 기동 (RAG 비활성화)
```bash
PREWARM_RAG_ON_STARTUP=false .venv/bin/uvicorn backend.main:app --port 8000
```
- 무거운 트랜스포머 모델이나 ChromaDB 로딩 없이 0.1초 만에 즉시 기동되어 인증 및 계정 API를 테스트할 수 있습니다.

---

## 3. 인증 REST API 사용 가이드

모든 요청/응답은 `application/json` 형식이며, 인증 보호 엔드포인트는 `Authorization: Bearer <access_token>` 헤더를 요구합니다.

### 3.1 회원가입 (`POST /api/v1/auth/register`)
- **설명:** 신규 계정을 생성합니다.
- **제약:**
  - `username`: 3~50자, 영문·숫자·`_`·`.`·`-`만 허용. 앞뒤 공백은 자동 제거되며 소문자로 정규화됩니다.
  - `password`: 8~128자 (긴 다국어 유니코드 지원).
  - 외부 필드 주입(`extra="forbid"`) 차단.
- **요청 예시:**
  ```bash
  curl -X POST http://localhost:8000/api/v1/auth/register \
    -H "Content-Type: application/json" \
    -d '{"username": "student2026", "password": "MyStrongPassword123!"}'
  ```
- **성공 응답 (201 Created):**
  ```json
  {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "username": "student2026",
    "created_at": "2026-09-23T07:15:00.123456+00:00"
  }
  ```
  *(비밀번호 평문/해시는 절대 반환되지 않으며, 자동 로그인은 수행되지 않습니다)*
- **실패 응답:**
  - 중복 아이디: `409 Conflict` (`{"detail": "이미 등록된 사용자명입니다."}`)
  - 유효성 위반: `422 Unprocessable Entity` *(평문 비밀번호 등 민감 입력은 응답에서 제거됨)*

---

### 3.2 로그인 및 세션 토큰 발급 (`POST /api/v1/auth/login`)
- **설명:** 사용자 자격 증명을 검증하고 256비트 암호학적 난수 Opaque Bearer 토큰을 발급합니다.
- **보안 특성:**
  - 응답 헤더에 `Cache-Control: no-store` 적용.
  - DB에는 원문 토큰이 아닌 SHA-256 hex digest만 저장.
  - 계정 미존재와 비밀번호 불일치 시 동일한 401 오류 문구 반환 (계정 탐색 방지).
- **요청 예시:**
  ```bash
  curl -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username": "student2026", "password": "MyStrongPassword123!"}'
  ```
- **성공 응답 (200 OK):**
  ```json
  {
    "access_token": "cmp_8dF92aK...xL9_2b1q",
    "token_type": "bearer",
    "expires_at": "2026-09-24T07:15:00.123456+00:00"
  }
  ```

---

### 3.3 현재 사용자 본인 정보 조회 (`GET /api/v1/auth/me`)
- **설명:** 유효한 Bearer 세션 토큰으로 본인의 공개 계정 정보를 조회합니다.
- **요청 예시:**
  ```bash
  curl -X GET http://localhost:8000/api/v1/auth/me \
    -H "Authorization: Bearer cmp_8dF92aK...xL9_2b1q"
  ```
- **성공 응답 (200 OK):**
  ```json
  {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "username": "student2026",
    "created_at": "2026-09-23T07:15:00.123456+00:00"
  }
  ```
- **실패 응답 (401 Unauthorized):**
  - 토큰 누락, 비ASCII/잘못된 토큰 형식, 만료된 토큰, 로그아웃으로 폐기된 토큰.

---

### 3.4 세션 로그아웃 (`POST /api/v1/auth/logout`)
- **설명:** 현재 사용 중인 세션 토큰을 즉시 폐기합니다 (`revoked_at` 기록). 동일 계정의 다른 기기/세션은 유지됩니다.
- **요청 예시:**
  ```bash
  curl -X POST http://localhost:8000/api/v1/auth/logout \
    -H "Authorization: Bearer cmp_8dF92aK...xL9_2b1q"
  ```
- **성공 응답:** `204 No Content` (본문 없음)

---

## 4. 데이터 영속성 및 프로세스 재시작 보증 구조

1. **파일 기반 SQLite 및 WAL 모드:**
   - 서버가 비정상 종료되거나 uvicorn 프로세스가 재시작되어도 `data/campusmate.db` 파일에 저장된 계정과 세션은 온전히 보존됩니다.
   - WAL 및 SHM sidecar 파일(`*.db-wal`, `*.db-shm`)은 `.gitignore`에 등록되어 git 추적에서 제외됩니다.
2. **검증된 영속성 테스트:**
   - **연결 재개방 및 반복 마이그레이션 (`test_connection_reopening_and_repeat_migrations`):** 동일한 SQLite 파일에 대해 DB 커넥션을 닫고 `init_db`를 여러 번 반복 호출해도 데이터가 삭제되지 않고 온전히 유지됨을 검증.
   - **독립 OS 서브프로세스 재시작 (`test_real_subprocess_restart_persistence`):** Python 인터프리터를 `subprocess.run`으로 완전히 종료한 뒤 새로운 프로세스로 기동하여 이전 프로세스가 발급한 토큰 및 비밀번호를 검증 완료.
