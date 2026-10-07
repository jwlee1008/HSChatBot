# R1-A 최종 재검수 — 승인

검수일: 2026-09-23

## 판정과 범위

R1-A 계정·인증·파일 기반 영속 저장을 승인한다. 이전 필수 수정 5건의 수정 코드와 동작을 확인했다. R1-B 개인 일정 CRUD로 진행할 수 있다. 이번 승인은 로컬 MVP 인증 기반에 한정하며 공개 서비스 배포, 브라우저 인증 UI, 일정 소유권 격리, 일정 추출·알림의 완료를 의미하지 않는다.

검토 자료: docs/gemini_round1a_revision_report.md, docs/campusmate_auth_api_guide.md, 실제 backend/auth·db·라우터·스키마·lifespan 및 tests/test_auth_persistence.py.

## 재실행 결과

아래 테스트를 Python pytest.main으로 실행했다. 실행 전 sys.addaudithook으로 부모 테스트 프로세스의 sqlite3.connect가 저장소 data 하위 DB를 열려고 하면 즉시 실패하도록 보호했다. 독립 자식 프로세스의 코드는 임시 DB 환경변수를 직접 설정함을 확인했다.

```sh
.venv/bin/python -m pytest tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```

- 동등한 테스트 인자 실행 결과: **79 passed, 1 warning, 16.40초**.
- 경고: Starlette TestClient의 AnyIO deprecated alias. 기능 실패는 아니다.
- 실행 전후 data 아래 DB 및 sidecar 파일 집합과 SHA-256 비교: **7개 파일 동일**. 계정 DB나 Chroma를 초기화·삭제하지 않았다.
- 인증 실패 경로를 별도 임시 SQLite/TestClient로 검사: **21개 HTTP 사례 통과**. 비밀번호 길이·자료형·객체/배열·추가 필드 오류, /me·/logout의 잘못된 토큰, 기존 query/retrieve의 기본 422 형식 보존을 확인했다. 첫 검토 스크립트의 짧은 비밀번호 표식 `short`는 오류 코드 `string_too_short`에도 포함되어 검사 자체가 실패했으며, 고유한 합성 표식으로 정정 후 위 21건을 완료했다. 제품 결함으로 집계하지 않는다.
- `.venv/bin/python scripts/verify_rag_eval_evidence.py`: **10/10 통과**, 통합 JSON SHA-256 일치. 로컬 근거 대조이며 실제 LLM 정답률 측정이 아니다.

## 이전 지적사항 종료

| 지적 | 재검수 결과 |
|---|---|
| 422 응답에 비밀번호 입력 반환 | 인증 경로에서 input 제거 확인. 독립 검사에서도 합성 비밀번호·민감 값 미노출. 기존 RAG 검증 오류는 기본 핸들러 유지 |
| 테스트 lifespan이 기본 계정 DB 사용 | 임시 경로가 lifespan과 요청 양쪽에 주입됨. 기본 data DB 접근 차단 상태에서 회귀 통과 및 파일 해시 불변 |
| 비ASCII 토큰에서 500 | 헤더 문자·길이 검증으로 /me와 /logout 모두 401 확인 |
| DB 초기화 실패를 삼켜 정상 기동 | init_db 예외가 startup에 전파됨. 합성 OperationalError 회귀 통과 |
| WAL/SHM Git 제외 누락 | db/sqlite/sqlite3의 WAL·SHM·journal 패턴 확인. check-ignore 대표 10경로 통과. 계정 DB 및 검사한 sidecar 추적 목록은 비어 있음 |

독립 Python 프로세스 2개에서 동일 임시 파일 DB를 열어 이전 세션으로 본인 정보를 조회하는 검사가 통과했다. 네트워크 소켓을 여는 uvicorn 재배포나 비정상 종료 복구를 검증한 것은 아니다.

## 승인 차단이 아닌 보완 사항

1. 테스트 fixture는 기존 dependency_overrides를 저장·복구하지 않고 clear한다. 현재 테스트 조합에는 문제가 없었지만 향후 공통 override fixture와 결합할 때는 사본을 저장하고 복원하는 방식으로 보완한다.
2. test_default_account_db_isolation은 임시 테이블 존재를 확인하며 default_path 변수를 실제 assertion에 사용하지 않는다. 이번 검수는 별도 접근 차단 및 해시 비교로 보완했다. 해당 검사를 저장소 테스트에 포함하면 향후 회귀 방지가 강화된다.
3. 숫자 비밀번호 비노출 assertion의 `or`는 오류 유형만 맞아도 통과한다. 값 미노출과 오류 유형을 각각 assert하는 편이 정확하다. 이번 독립 검사에서 실제 숫자 입력 미노출은 확인했다.
4. 가이드의 “0.1초 기동”은 이번에 측정하지 않았다. PREWARM_RAG_ON_STARTUP=false는 사전 로드만 끄며 /api/query·retrieve 요청 시 지연 초기화는 가능하다. “RAG 비활성화” 표현은 이 의미로 정정하는 것이 좋다.
5. 서브프로세스 검사는 기존 토큰 인증을 확인하지만 두 번째 프로세스의 비밀번호 재로그인과 비정상 종료 복구는 검사하지 않는다. 문서의 보증 범위는 실제 검사 수준에 맞추고 해당 동작은 배포 단계에서 검증한다.

## 다음 단계

R1-B에서 개인 일정 CRUD 및 날짜/시각 모델을 구현하고, 인증된 current_user를 기준으로 계정 A가 B의 일정을 조회·수정·삭제할 수 없는지 별도 검증한다. 공개 인증의 호출 제한, HTTPS, 브라우저 토큰 보관 및 운영 복구는 후속 범위다.

애플리케이션 코드 변경, 실제 모델 호출, 크롤링, 배포, commit/push는 수행하지 않았다. 이번 산출물은 이 최종 검수 보고서다.
