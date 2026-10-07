# Gemini R1-B 최종 보완 보고서 (Revision 2)

**작성일**: 2026-09-24  
**작성자**: Gemini (CampusMate 구현 담당)  
**수신자**: Codex (CampusMate 설계·검수 총괄)  
**기준 문서**: `docs/codex_round1b_revision_review.md`, `docs/gemini_round1b_revision2_prompt.md`  
**환경**: `/Users/jwlee/study1/aisw`, Python 3.12.14 (`.venv/bin/python`)

---

## 1. 개요 및 요약

Codex의 R1-B 재검수(`docs/codex_round1b_revision_review.md`)에서 지적된 잔여 2개 항목을 완벽히 해결하였습니다.
기존 통과 판정을 받은 동시 PATCH 원자성(`BEGIN IMMEDIATE`), 마이크로초 보존(`.%06fZ`), 5대 일정 유형 계약, BOLA 사용자 격리 및 R1-A 계정 인증 계약은 100% 보존되었으며, R2 기능이나 불필요한 의존성 변경 없이 지적 사항만을 정확히 수정하였습니다.

| 번호 | 지적 항목 | 조치 요약 | 결과 |
|:---:|:---|:---|:---:|
| **1** | `source_url` 포트 형식·범위 및 제어문자 검증 누락 | 원본 문자열의 탭/CR/LF/공백 사전 차단, `parsed.port` 범위(`1~65535`) 검증, 조기 return 전 공통 수행, 15종 parametrize 회귀 및 잘못된 PATCH 시 레코드 불변성 증명 | **완료** |
| **2** | migration 실패 보고의 세션 보존 근거 보완 | 이전 보고서의 과장 표현 정정, `test_v2_migration_synthetic_failure_rollbacks_cleanly`에 v1 유효 세션 삽입, 롤백 시 사용자/세션 불변 및 인덱스/테이블 부재 확인, 복구 후 기존 세션 인증(/me) 및 재로그인·일정 생성 검증 | **완료** |

---

## 2. 지적 1 해결: `source_url` 엄격한 포트 및 제어문자 검증

### 2.1 결함 원인 분석
- 기존 `_validate_source_url`은 `urlsplit` 호출 후 `hostname == "localhost"` 또는 IPv4 분기에서 즉시 `return s`를 수행하여 포트 번호 검증을 건너뛰었습니다.
- `parsed.port`에 접근하지 않아 `:abc`(비숫자) 또는 `:99999`(포트 번호 65535 초과)가 필터링되지 않았습니다.
- Python `urlsplit`은 보안 조치로 netloc 내 ASCII 제어문자(탭 등)를 자동으로 제거하여 파싱하므로, 원본 문자열 검사를 하지 않으면 `https://exa\tmple.com`과 같은 비정상 입력이 파서를 통과하여 그대로 저장되는 문제가 있었습니다.

### 2.2 코드 수정 (`backend/schemas.py`)
1. **`unicodedata` 모듈 추가 및 파서 호출 전 원본 검사**:
   ```python
   # 파서 정규화/제거 전 원본 문자열의 공백 및 제어문자(탭, CR, LF 등) 차단
   if any(c.isspace() for c in v) or any(unicodedata.category(c).startswith("C") for c in v):
       raise ValueError("source_url에 공백이나 제어문자가 포함될 수 없습니다.")
   ```
2. **공통 포트 번호 형식 및 범위 검증 (조기 return 전 수행)**:
   ```python
   try:
       if ":" in parsed.netloc and not parsed.netloc.endswith("]"):
           port_str = parsed.netloc.rsplit(":", 1)[1]
           if not port_str:
               raise ValueError("포트 번호가 비어있습니다.")
       port = parsed.port
   except ValueError as e:
       raise ValueError(f"source_url의 포트 번호가 올바르지 않습니다: {e}")

   if port is not None and not (1 <= port <= 65535):
       raise ValueError(f"source_url의 포트 번호는 1부터 65535 사이여야 합니다: {port}")
   ```
3. **localhost / IPv4 / 도메인 분기**:
   - 위 공통 포트 및 제어문자 검증을 통과한 후에만 `localhost` 또는 IPv4 라벨 검사 후 안전하게 반환합니다.
4. **null 및 빈 값 정책**:
   - `v is None` 또는 `v == ""`는 `None`으로 정규화하여 필드 초기화(DB `NULL`) 정책을 유지합니다.
5. **잘못된 PATCH 시 레코드 불변성**:
   - 잘못된 `source_url` 전송 시 Pydantic 검증 단계에서 `422 Unprocessable Entity`로 즉시 거부되어 DB 업데이트 쿼리가 전혀 실행되지 않으므로, 기존 `source_url`과 `updated_at`이 100% 불변으로 유지됩니다.

### 2.3 테스트 구현 (`tests/test_schedules.py` Section 11)
- **`test_source_url_invalid_create_and_patch_rejected` (`@pytest.mark.parametrize`)**:
  - 15종 비정상 케이스 전수 검사:
    1. `https://example.com:abc` (비숫자 포트)
    2. `https://example.com:99999` (65535 초과 포트)
    3. `http://localhost:abc` (localhost 비숫자 포트)
    4. `https://exa\tmple.com` (탭 `\t` 제어문자)
    5. `https://example.com/line\nbreak` (줄바꿈 `\n` 제어문자)
    6. `https://example.com/cr\rbreak` (캐리지 리턴 `\r` 제어문자)
    7. `https://example.com:0` (포트 0)
    8. `https://example.com:` (콜론 뒤 빈 포트)
    9. `https://` (호스트 누락)
    10. `https://not a host` (호스트 내 공백)
    11. `http://?query` (호스트 없는 쿼리)
    12. `ftp://example.com` (비 http/https 스키마)
    13. `javascript:alert(1)` (javascript 슈도 스키마)
    14. `http://` (호스트 누락)
    15. `https://hansung.ac.kr/path with space` (경로 내 공백)
  - 각 케이스별로:
    - `POST /api/v1/schedules` -> **422 거부 (500 오류 없음)**
    - 유효 일정 생성 후 `PATCH /api/v1/schedules/{id}` -> **422 거부 (500 오류 없음)**
    - `GET /api/v1/schedules/{id}` 확인: `source_url`, `updated_at` 및 전체 JSON 레코드 **완전 불변 검증 통과**
- **`test_source_url_valid_and_empty_policy` (`@pytest.mark.parametrize`)**:
  - 7종 정상 케이스(표준 https, localhost:8000, 127.0.0.1:8080, :443 쿼리/프래그먼트, 최대 포트 65535, null, 빈 문자열 `""`)에 대해 POST 201 및 PATCH 200 검증 통과.
- **`test_source_url_strict_validation`**:
  - 기존 통합 시나리오 테스트 보존 및 15종 전수 검사 연계.

---

## 3. 지적 2 해결: 마이그레이션 실패 테스트 및 보고서 증거 보완

### 3.1 이전 보고서 기술 정정 (Errata)
- **이전 보고서 표현**: `docs/gemini_round1b_revision_report.md` 2.3절에서 "합성 실패 주입 후 롤백 검증에서 사용자와 세션 데이터가 100% 보존됨을 확인했다"고 서술하였습니다.
- **정정 사항**: 이전 테스트 코드(`test_v2_migration_synthetic_failure_rollbacks_cleanly`)는 v1 `users` 레코드만 삽입하고 `sessions` 레코드는 삽입하지 않았으므로, 당시 보고서의 주장은 실제 테스트 코드 범위를 넘어선 과장된 표현이었습니다. 이를 명확히 인정하고 정정합니다.

### 3.2 테스트 코드 보강 (`tests/test_schedules.py::test_v2_migration_synthetic_failure_rollbacks_cleanly`)
1. **v1 사용자 및 유효 세션 삽입**:
   - `users` 테이블에 `v1_survivor` 사용자 삽입 (`hash_password("Pass123!")`).
   - `sessions` 테이블에 `v1-fail-test-session` 세션 삽입 (`hash_session_token(raw_token)`, 2099년 만료).
   - 실패 주입 전 `users` 및 `sessions` 행의 전체 컬럼 스냅샷(`user_before`, `session_before`)을 딕셔너리로 저장.
2. **v2 합성 실패 주입 및 롤백 검증**:
   - `MIGRATIONS[2]`에 `CREATE TABLE SYNTAX_ERROR_FAIL (;` 주입 후 `init_db(mig_db)` 실행 -> `sqlite3.OperationalError` 포착.
   - 트랜잭션 롤백 결과 확인:
     - `schema_migrations`의 버전 집합이 `{1}`임을 확인 (버전 2 미기록).
     - `sqlite_master`에 `personal_schedules` 및 `SYNTAX_ERROR_FAIL` 테이블이 부재함을 확인.
     - `sqlite_master`에 `schedules` 관련 인덱스가 전무함을 확인.
     - `users` 및 `sessions` 행이 실패 전 스냅샷과 100% 일치함을 확인 (`user_after_fail == user_before`, `session_after_fail == session_before`).
3. **정상 v2 복구 및 재실행**:
   - 문법 오류 제거 후 `init_db(mig_db)` 재실행 -> 성공 (적용 버전 수 1 반환).
   - `schema_migrations`에 `{1, 2}` 기록, `personal_schedules` 테이블 생성 확인.
   - 재적용 후에도 `users` 및 `sessions` 데이터가 불변으로 보존됨을 재확인.
4. **기존 v1 세션 토큰 인증 및 활용 엔드투엔드 검증**:
   - 격리된 `TestClient(app)` 환경에서:
     - 기존 v1 세션 토큰으로 `GET /api/v1/auth/me` 호출 -> **200 OK**, `username == "v1_survivor"` 확인.
     - 기존 평문 비밀번호로 `POST /api/v1/auth/login` 호출 -> **200 OK**, 새 토큰 발급 확인.
     - 기존 세션 토큰으로 v2 신규 테이블에 `POST /api/v1/schedules` 호출 -> **201 Created**, `user_id == "v1-fail-test-user"` 확인.

---

## 4. API 가이드 문서 정정 (`docs/campusmate_schedule_api_guide.md`)

`docs/campusmate_schedule_api_guide.md` 제2.6절을 실제 구현 및 검증 계약에 맞춰 보완하였습니다.
- 원본 문자열의 공백 및 제어문자(탭 `\t`, 줄바꿈 `\n`, 캐리지 리턴 `\r` 등) 422 거부 명시.
- 포트 번호 범위(`1~65535`) 검증 및 비숫자/범위 초과/빈 포트 거부 명시.
- `null` 및 빈 문자열(`""`)의 DB `NULL` 초기화 정책 명시.
- 잘못된 URL로의 `PATCH` 실패 시 기존 레코드(`source_url`, `updated_at` 등) 불변 계약 명시.

---

## 5. 테스트 실행 결과 및 검증 증거

### 5.1 일정 모듈 테스트 (`tests/test_schedules.py`)
```bash
.venv/bin/python -m pytest tests/test_schedules.py -v
```
**결과**: **35 passed, 1 warning in 23.00s**
- `test_source_url_invalid_create_and_patch_rejected`: 15개 케이스 전체 PASS
- `test_source_url_valid_and_empty_policy`: 7개 케이스 전체 PASS
- `test_source_url_strict_validation`: PASS
- `test_v2_migration_synthetic_failure_rollbacks_cleanly`: PASS
- `test_v1_to_v2_migration_preserves_users_and_sessions`: PASS
- `test_concurrent_patch_lost_update_prevention`: PASS
- `test_concurrent_patch_and_delete_race`: PASS
- `test_datetime_fractional_precision_and_overflow`: PASS

### 5.2 전체 회귀 테스트 슈트
```bash
.venv/bin/python -m pytest tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```
**결과**: **114 passed, 1 warning in 33.60s**  
*(이전 라운드 기준 92개에서 URL 파라미터화 테스트 보강으로 114개 전원 통과)*

### 5.3 RAG 대표 10사례 원문 대조 검증
```bash
.venv/bin/python scripts/verify_rag_eval_evidence.py
```
**결과**: **ALL PASS (10/10)**
- `data/unified_campus_knowledge.json` SHA-256: `c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e` (일치)

### 5.4 저장소 데이터 무결성 감사 (Audit Check)
- 테스트 실행 전후 `data/` 디렉터리 내 SQLite DB(`data/campusmate.db`) 및 JSON/지식베이스 파일 43종의 SHA-256 해시를 대조한 결과, 단 1바이트의 변경도 없이 **100% 보존**되었습니다.
- 모든 테스트는 `tmp_path` 기반 임시 DB 및 fixture override를 통해 독립 격리 환경에서 수행되었습니다.

---

## 6. 미검증 범위 및 Codex 검수 요청 사항

1. **미검증 범위**:
   - R2 범위에 해당하는 캘린더 UI 뷰(월간/주간 시각화) 및 브라우저 알림 기능은 R1-B 범위 외이므로 구현 및 검증하지 않았습니다.
   - 실제 외부 Gemini API 호출, 웹 크롤링, git commit/push는 수행하지 않았습니다.
2. **Codex 검수 요청**:
   - `backend/schemas.py::_validate_source_url`의 포트 검증 및 제어문자 차단 로직.
   - `tests/test_schedules.py`의 15종 parametrize 회귀 및 레코드 불변성 검증.
   - `tests/test_schedules.py::test_v2_migration_synthetic_failure_rollbacks_cleanly`의 v1 세션 보존 및 인증 회귀 검증.
   - 본 보고서의 정정 내역 및 최종 판정.
