# R1-B 수정본 재검수 — URL 검증 추가 수정 필요

검수일: 2026-09-23. 수정 보고서와 API 가이드, 실제 코드 및 테스트를 확인했다. walkthrough.md는 저장소에서 찾지 못했다.

## 판정

이전 동시 PATCH 데이터 유실과 마이크로초 절단 문제는 수정됐다. migration 보존·롤백 검사도 보강됐다. 다만 기존 source_url 검증 지적은 일부만 해결되어 최종 승인을 보류한다. 남은 코드 수정은 URL 검증에 한정한다.

## 확인된 해결 사항

- PATCH의 BEGIN IMMEDIATE가 SELECT보다 먼저 실행되어 읽기→병합→검증→UPDATE를 보호한다. 응답에 사용할 행도 커밋 전에 회수한다. DELETE는 잠금 하에 삭제하고 rowcount로 404를 판정한다. 동시 수정 및 수정/삭제 경합 회귀가 통과했다.
- `.100000+09:00`~`.900000+09:00` 행사를 독립 HTTP 검사로 다시 생성했다. POST 201, 제목 PATCH 200이며 UTC 값 `.100000Z`와 `.900000Z`가 보존됐다. 범위 초과 422 회귀도 통과했다.
- 기존 비밀번호 재로그인과 기존 세션을 이용한 v1→v2 업그레이드 검사가 통과했다. v2 중간 실패 후 테이블/버전 기록 롤백 및 재적용 검사가 통과했다.
- 이전 잘못된 URL `https://`, `https://not a host`, `http://?query`는 CREATE/PATCH 모두 422로 수정됐다.

## 잔여 결함: [P2] URL의 포트·제어문자 검증 누락

위치: backend/schemas.py:198–225, `_validate_source_url`.

독립 임시 SQLite + TestClient에서 다음을 확인했다.

| source_url 입력 | POST | PATCH |
|---|---:|---:|
| `https://example.com:abc` | 201 | 200 |
| `https://example.com:99999` | 201 | 200 |
| `http://localhost:abc` | 201 | 200 |
| `https://exa\tmple.com` (실제 탭 문자) | 201 | 200 |

urlsplit 호출 및 hostname 검사만으로 포트 형식/범위가 검증되지는 않는다. parsed.port를 확인하지 않아 비숫자·범위 초과 포트가 통과한다. 또한 ASCII 공백 하나만 검사하고 urlsplit이 제거한 탭을 원본 문자열에서는 그대로 저장한다. 결과적으로 가이드의 공백 거부 및 유효한 http/https URL 저장 계약을 충족하지 못한다.

검증된 URL 타입 또는 완전한 파서 검증을 사용하여 포트와 원본 입력의 제어문자를 검사한다. localhost/IP의 조기 return 전에 공통 검증을 수행한다. 네트워크 요청은 필요 없다. CREATE와 PATCH 모두에서 위 입력을 422로 거부하고 잘못된 PATCH 후 기존 데이터가 바뀌지 않는지 검사한다.

## 실제 실행 결과

`.venv/bin/python`에서 pytest.main으로 다음 인자를 실행했다:

```text
tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```

- **92 passed, 1 warning, 27.50초**. 경고는 기존 Starlette/AnyIO deprecation이다.
- 부모 pytest 프로세스의 sqlite3.connect가 저장소 data 아래 DB를 열면 실패하도록 audit hook을 적용했다. 자식 프로세스는 임시 경로 사용을 코드로 확인했다.
- 실행 전후 DB 및 sidecar 파일 집합/SHA-256: **7개 파일 동일**.
- 별도 임시 DB에서 URL 7종 × CREATE/PATCH **14응답**을 관측했고, 마이크로초 생성/수정 **2응답**을 추가 확인했다. 위 잔여 결함을 모두 PASS로 집계하지 않는다.

## 증거 표현 보완

`test_v2_migration_synthetic_failure_rollbacks_cleanly`는 v1 사용자만 만들고 세션은 삽입하지 않는다. 수정 보고서의 “실패 후 사용자와 세션 보존 확인”은 현재 코드보다 넓은 주장이다. 실패 테스트에 실제 유효 세션을 추가해 검증하거나 보고서를 사용자 보존으로 한정한다. 성공적인 업그레이드의 세션 보존 검사는 별도로 존재한다.

동시 요청 테스트는 HTTP 호출 시작만 barrier로 맞춘다. 현재 잠금 위치는 코드상 적절하지만, 이전 코드의 취약한 읽기 구간을 반드시 재현하는 회귀는 아니다. 추후 잠금 안의 검증 시 conn.in_transaction 확인 또는 제어된 DB 접근 순서 검사로 강화할 수 있다.

애플리케이션 코드 변경·실제 모델 호출·크롤링·배포·commit/push는 수행하지 않았다.
