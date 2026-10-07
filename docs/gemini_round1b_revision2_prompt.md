# Gemini R1-B 최종 보완 — URL 검증과 증거 정정

`docs/codex_round1b_revision_review.md`를 읽고 아래 두 항목만 수정한다. 동시 PATCH, 마이크로초 보존, 기존 일정/인증 계약은 유지한다. R2·UI·알림 기능을 추가하지 않는다.

## 1. source_url의 잘못된 포트와 제어문자 차단

현재 `_validate_source_url`은 아래 입력을 CREATE 201 / PATCH 200으로 허용한다:

- `https://example.com:abc`
- `https://example.com:99999`
- `http://localhost:abc`
- 실제 탭 문자가 포함된 `https://exa\tmple.com`

검증된 URL 타입 또는 파서의 포트 검증을 사용한다. 파서가 입력을 정규화/제거하기 전에 원본 문자열의 탭·CR·LF 등 제어문자를 거부한다. localhost/IP 분기의 조기 return 전에 공통 검증을 마쳐야 한다. 기존 길이·nullable·http/https 규칙을 유지한다. URL을 네트워크로 조회하지 않는다.

CREATE/PATCH 모두 위 입력 및 줄바꿈 문자를 422로 거부하는 parametrize 회귀를 작성한다. 잘못된 PATCH는 기존 source_url과 updated_at 등 레코드를 바꾸지 않아야 한다. 정상 https URL, localhost:8000, IPv4와 유효 포트, null/빈 값 정책의 회귀도 포함한다. 실패를 500으로 처리하지 않는다.

## 2. migration 실패 보고의 세션 보존 근거 보완

현재 실패 테스트는 사용자만 삽입하지만 수정 보고서는 사용자와 세션 보존을 검증했다고 기술한다. 임시 v1 DB에 유효 세션을 추가하여 합성 v2 실패 전후 사용자·세션 레코드 불변, v2 테이블/인덱스/버전 기록 부재, 정상 재적용 후 기존 세션 인증을 검사한다. 실제 검사 결과에 맞춰 새 보고서에서 이전 표현을 정정한다.

신규/보강 검사를 먼저 실행한 뒤 기존 일정·인증·관련 RAG 회귀를 결합한다. 기존 기준은 92개 통과이며 테스트 개수를 맞추기 위해 사례를 생략하지 않는다. lifespan/요청 DB는 모두 임시 경로를 사용하고 기본 계정 DB·Chroma 접근을 차단한다. 실제 LLM·크롤링·배포·commit/push·의존성 전체 업그레이드는 하지 않는다.

원본 보고서와 사용자 파일을 보존한다. 산출물은 수정 코드/회귀 테스트, 필요 시 API 가이드 정정, `docs/gemini_round1b_revision2_report.md`다. 새 보고서에 실행 명령/결과와 지적별 증거·미검증 범위를 기록하고 Codex 재검수를 기다린다.
