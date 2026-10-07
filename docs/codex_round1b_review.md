# R1-B 검수 — 수정 필요

검수일: 2026-09-23. 완료 보고서·API 가이드와 실제 구현을 대조했다. walkthrough.md는 현재 저장소에서 찾지 못했다. 애플리케이션 코드는 수정하지 않았다.

## 판정

기본 일정 CRUD, 소유자 범위 SQL, 사용자 확인 계약, v2 migration 및 테스트는 구현되어 있다. 그러나 동시 수정 데이터 유실과 날짜·시각 정규화의 불변식 위반을 재현했으므로 R1-B 완료 승인은 보류한다. R2 추출 기능을 추가하기 전에 아래 항목을 수정한다.

## 1. [P1] 동시 PATCH가 성공한 다른 필드 변경을 덮어씀

위치: backend/schedules/service.py:528–565 및 전체 필드를 쓰는 UPDATE.

PATCH는 트랜잭션 밖에서 기존 행을 읽고 최종 상태를 구성한 뒤 BEGIN IMMEDIATE를 시작한다. 두 요청이 같은 상태를 읽으면 먼저 완료된 변경을 두 번째 요청이 이전 값으로 덮어쓴다. 전송하지 않은 필드 보존 계약을 위반한다.

재현: 임시 DB에 title=review, description=null인 일정을 생성하고, 같은 사용자로 title='new title' PATCH와 description='new description' PATCH를 동시에 보냈다. validate_schedule_state의 계산 결과 반환 직전에 threading.Barrier(2)를 두어 두 요청이 기존 상태를 모두 읽도록 했다. 실제 API 처리 결과는 [200, 200]이었지만 최종 상태는 title='new title', description=null로 설명 변경이 유실됐다. DB 쓰기·조회 결과를 mock한 것이 아니라 요청 순서만 제어했다.

수정: 쓰기 잠금/트랜잭션이 읽기→병합→검증→쓰기 전체를 보호하도록 하거나 버전 기반 충돌 검사를 적용한다. 모든 종료 경로에서 rollback/정리를 보장하고 잠금 대기 실패를 안전하게 처리한다. 수정과 삭제가 경합할 때도 없는 행을 성공 응답으로 변환하다 500이 나지 않게 한다. 회귀는 sleep에 의존하지 말고, 올바른 직렬화 구현에서도 barrier 때문에 교착되지 않는 방식으로 요청 시작/DB 접근을 제어한다.

## 2. [P2] 소수점 초 절단으로 저장된 일정이 자체 검증에 실패

위치: backend/schedules/service.py:98–100.

datetime 파서는 소수점 초를 허용하고 원래 datetime으로 시작<종료를 검사하지만 strftime은 초 이하를 버린다.

재현 입력:

```json
{
  "title": "fractional",
  "schedule_kind": "TIME_CONFIRMED_EVENT",
  "start_date": "2026-10-01",
  "end_date": "2026-10-01",
  "start_datetime": "2026-10-01T10:00:00.100000+09:00",
  "end_datetime": "2026-10-01T10:00:00.900000+09:00",
  "confirmed": true
}
```

POST는 201이지만 저장·응답의 시작과 종료가 모두 `2026-10-01T01:00:00Z`가 된다. 이어서 title만 PATCH하면 422로 실패한다.

수정: 지원하는 소수점 정밀도를 보존하거나, 지원하지 않는 정밀도는 저장 전에 명시적으로 422로 거부한다. 조용한 절단은 허용하지 않는다. 정규화된 저장값 자체가 재검증을 통과해야 한다. 날짜 경계 및 offset 변환에서 발생하는 범위 초과도 안전한 422로 처리하는 검사를 보강한다.

## 3. [P2] source_url이 실제 URL인지 검사하지 않음

위치: backend/schemas.py:186–196.

http/https 접두사만 확인하여 `https://`, `https://not a host`, `http://?query` 모두 정상 일정으로 201 저장됐다. 이후 UI가 정상 출처 링크로 표시할 수 없는 값이다.

수정: 검증된 URL parser/type으로 http/https scheme, 유효한 host, 길이를 검사한다. CREATE와 PATCH에 동일한 규칙을 적용하고 nullable 동작은 유지한다. 서버에서 해당 URL을 조회하지 않는다. 정상 URL과 잘못된 host/공백/다른 scheme의 회귀를 추가한다.

## 검증 및 증거 보완

- Codex 재실행: **87 passed, 1 warning, 25.81초**. 테스트 인자는 `tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q`이며, 접근 가드를 설치한 `.venv/bin/python`의 pytest.main으로 실행했다. 경고는 기존 Starlette/AnyIO deprecated alias다.
- 실행 전후 저장소 data 아래 DB/sidecar 파일 집합 및 SHA-256 비교: **7개 파일 동일**.

- 테스트의 v1→v2 검증은 사용자·세션을 SQL fixture로 삽입하며 비밀번호 해시가 dummy_hash다. 기존 토큰과 레코드 보존 증거는 유효하지만 기존 비밀번호 재로그인 보존까지 검증한 것은 아니다. 실제 비밀번호 해시와 재로그인 검사를 추가한다.
- 요구된 migration 실패 시 부분 반영 방지 회귀가 tests/test_schedules.py에 없다. v2 도중 합성 실패를 주입하여 테이블·인덱스·버전 기록이 함께 롤백되고 기존 v1 사용자·세션이 보존되는지 확인한다.
- 8개 테스트 함수가 여러 사례를 묶어 검사하고 있다. 통과 개수는 테스트 함수 수이며 모든 경계·경합 조건의 완전성을 의미하지 않는다.
- 운영 DB를 열지 않도록 부모 pytest 프로세스의 sqlite3.connect 접근 가드를 적용하고 파일 해시로 전후 상태를 비교한다. 자식 프로세스는 테스트 소스에서 임시 경로 사용을 확인했다.

실제 LLM 호출·크롤링·배포·commit/push는 수행하지 않았다. 재현은 합성 계정과 임시 SQLite에서 실행했다.
