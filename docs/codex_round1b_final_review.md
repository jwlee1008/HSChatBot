# R1-B 최종 재검수 — 승인

검수일: 2026-09-24

## 판정

R1-B 개인 일정 CRUD와 사용자별 접근 격리 백엔드를 승인한다. 이전 검수의 동시 PATCH 데이터 유실, 마이크로초 정밀도 손실, 잘못된 source_url 허용 및 migration 실패 후 세션 보존 증거 부족이 해결됐다. 이번 범위에서 추가 승인 차단 사항은 확인하지 못했다.

다음 단계는 R2 자연어/공지의 일정 후보 추출과 사용자 확인을 위한 데이터 계약이다. 캘린더 UI는 R3이며, R1-B 승인에 UI·알림·운영 배포 완료가 포함되지 않는다.

## 검토 자료

- docs/gemini_round1b_revision2_report.md
- docs/campusmate_schedule_api_guide.md
- backend/schemas.py의 URL 검증과 backend/schedules/service.py의 시간/CRUD 처리
- tests/test_schedules.py의 URL parametrize 및 migration 실패/복구 검사
- 기존 인증·RAG·날짜 파싱 관련 회귀

## Codex 재실행 결과

`.venv/bin/python`에서 pytest.main으로 다음 인자를 실행했다:

```text
tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```

- **114 passed, 1 warning, 48.84초**. 전체 결과에 일정 모듈 35개가 포함된다. 별도로 동일 모듈을 중복 실행해 결과를 합산하지 않았다.
- 경고는 기존 Starlette TestClient의 AnyIO deprecated alias이며 기능 실패는 아니다.
- 부모 테스트 프로세스에 sqlite3.connect audit hook을 설치하여 저장소 data 하위 DB 접근 시 실패하도록 보호했다. 테스트의 자식 프로세스는 임시 DB 환경변수 사용을 코드로 확인했다.
- **데이터 해시 감사: 597개 파일 동일.** data 하위를 재귀 순회하여 JSON, .db/.sqlite/.sqlite3 및 -wal/-shm/-journal 파일의 경로 집합과 SHA-256을 실행 전후 비교했다. Gemini의 43개 집계와 검사 범위가 다르며 이 수치를 동일한 집계라고 주장하지 않는다. 다른 확장자 파일의 전체 무변경을 의미하지 않는다.
- `.venv/bin/python scripts/verify_rag_eval_evidence.py`: 종료 코드 0, 데이터셋 SHA-256 일치 및 **10/10 PASS**. 이는 로컬 JSON 근거 대조이며 실제 생성 품질이나 OCR 원본 정확도 검증이 아니다.

## 잔여 지적사항 종료 근거

### URL 검증

원본 문자열의 공백/제어문자를 urlsplit 전에 거부하고, localhost/IPv4 조기 반환 전 parsed.port와 허용 범위를 검사한다. 15종 비정상 URL의 POST/PATCH 422 및 실패 후 전체 레코드 불변, 정상 URL/nullable 7종의 회귀가 통과했다.

추가로 별도 임시 DB에서 아래 7종을 독립 HTTP 검사했다:

- 비숫자 포트, 65535 초과 포트, localhost 비숫자 포트
- 호스트 내부 탭, 경로의 NUL/CR/LF

7종 모두 POST/PATCH가 422이며 이후 GET의 전체 일정 JSON이 초기 스냅샷과 같았다. 실제 외부 URL 조회는 수행하지 않았다.

### migration 실패 후 계정·세션 보존

실패 테스트가 실제 비밀번호 해시와 유효 세션을 가진 v1 DB를 구성한다. v2 중간 SQL 오류 후 사용자/세션 전체 컬럼 불변, v2 테이블·인덱스·버전 기록 부재를 확인한다. 정상 v2 재적용 후에도 원본 레코드를 비교하며 기존 토큰 인증, 기존 비밀번호 재로그인, 새 일정 생성까지 검사한다. 이번 재실행에서 해당 검사가 통과했다. 이전 보고서의 증거 과장도 Revision 2에서 명시적으로 정정됐다.

## 승인 범위와 후속 검증

승인 범위는 로컬 파일 SQLite 기반의 인증된 개인 일정 생성·목록/상세·수정·삭제, 사용자별 접근 제한, 날짜/시각 모델, migration 및 프로세스 재개방 영속성이다.

공개 서비스의 브라우저 인증·캘린더 흐름, 실제 uvicorn 배포 및 장애 복구, 부하·장시간 잠금 대기, 알림 발송, 실제 LLM 일정 추출은 후속 라운드에서 검증한다. 이번 테스트 통과를 전체 서비스 완성이나 모든 경합 조건에 대한 보증으로 확대하지 않는다.

애플리케이션 코드·기존 보고서는 변경하지 않았다. 실제 LLM 호출·크롤링·배포·commit/push는 수행하지 않았다. 이번 산출물은 이 최종 검수 보고서다.
