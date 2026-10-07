# Gemini R1-B — 개인 일정 CRUD와 사용자별 접근 격리

R1-A 계정·인증·영속 저장 기반은 Codex 최종 재검수를 통과했다. 이번에는 기존 인증을 사용하여 사용자가 확인한 개인 일정을 저장·조회·수정·삭제하는 백엔드만 구현한다. 구현 담당은 Gemini, 설계·검수 담당은 Codex다.

## 1. 시작과 범위

- 저장소: `/Users/jwlee/study1/aisw`. 적용 AGENTS.md가 있으면 읽고 시작 git status를 기록한다. 기존 수정·미추적 파일을 보존한다.
- 먼저 읽을 문서: `docs/codex_round1a_final_review.md`, `docs/campusmate_auth_api_guide.md`, `docs/campusmate_evaluation_baseline.md`의 4.2절, `docs/campusmate_improvement_plan_20260923.md`.
- 실제 코드: backend/auth/, backend/db/, backend/routers/auth.py, backend/schemas.py, backend/main.py, tests/test_auth_persistence.py.
- 기존 opaque bearer 인증 및 `get_current_user`를 재사용한다. JWT나 새 인증 체계를 도입하지 않는다.
- 이번 범위: 일정 모델, SQLite v2 migration, 인증된 CRUD API, 시간/입력 검증, 사용자 격리, 영속성 테스트, 사용 문서.
- 제외: 자연어·LLM 일정 추출, 추출 초안 API, 캘린더/로그인 UI, 알림 예약·발송, 외부 캘린더, 반복 일정, PostgreSQL 전환, 실제 배포. R0 초안의 alarm_offsets_min은 이번 저장 계약에서 제외하고 알림 라운드에서 도입한다.
- R0의 후보 픽스처는 추출 평가용이다. 일부 start_date/end_date에 datetime이 들어 있으므로 그대로 저장 스키마로 복사하지 않는다. 아래 계약이 이번 확정 저장 API 기준이다.

## 2. 일정 데이터 모델

기존 AUTH_DB_PATH의 SQLite에 `personal_schedules` 테이블을 추가한다. Chroma와 분리된 기존 계정 DB를 그대로 사용한다.

### 서버 관리 필드

- `id`: 서버 생성 UUID.
- `user_id`: 인증된 current_user의 id, users.id 외래키. 클라이언트가 지정·변경할 수 없다.
- `created_at`, `updated_at`, `user_confirmed_at`: 서버 생성 UTC 시각.
- 클라이언트가 위 필드를 보내면 422. 입력 스키마는 extra="forbid"로 제한한다.

### 사용자가 입력하는 필드

- `title`: 앞뒤 공백 제거 후 1~200자. 공백만 있는 값 거부.
- `description`: 선택, null 허용, 최대 5,000자.
- `course_name`: 선택, null 허용, 최대 100자.
- `schedule_kind`: 아래 5종 enum.
- `start_date`, `end_date`: 날짜 전용 `YYYY-MM-DD` 문자열 또는 null. datetime 문자열이나 숫자를 날짜로 묵시 변환하지 않는다.
- `start_datetime`, `end_datetime`: 명시적인 UTC/offset이 있는 ISO 8601 문자열 또는 null. naive datetime, 날짜만 있는 문자열, 숫자 epoch를 거부한다. 저장·응답은 UTC로 정규화한다.
- `timezone`: 기본 `Asia/Seoul`. 이번에는 이 값만 지원하고 다른 값은 422. 국제 시간대 지원은 후속이다.
- `source_url`: 선택, null 허용. http/https URL만 허용, 최대 2,048자. 저장만 하고 서버가 URL을 가져오지 않는다.
- `source_title`: 선택, null 허용, 최대 500자.
- `extracted_quote`: 선택, null 허용, 최대 5,000자. 사용자가 제공한 근거 문장으로 보존하며 서버가 원문 검증 완료를 주장하지 않는다.
- `is_completed`: strict boolean, 기본 false.
- `priority`: HIGH / MEDIUM / LOW, 기본 MEDIUM.
- `confirmed`: 요청 전용 strict boolean. 생성과 PATCH 모두 명시적인 true가 필수이며 누락/false/문자열은 422. 해당 요청이 사용자의 저장·수정 확인을 표현한다. 원문이나 AI 결과만으로 자동 저장하지 않는다.

`is_all_day`, `is_time_confirmed`는 schedule_kind에서 계산한 응답 필드다. 요청에서 중복 입력받지 않아 모순을 막는다. user_confirmed_at은 성공적인 생성/수정 시 서버에서 기록한다. 이 플래그는 API 계약상의 확인이며 실제 UI 클릭을 검증했다는 의미는 아니다.

## 3. 날짜·시각 조합의 확정 계약

아래 표에서 필수로 명시하지 않은 날짜/일시 필드는 반드시 null이어야 한다. 생략은 생성 시 null로 취급한다.

| schedule_kind | 필수 날짜·일시 필드 | is_all_day / is_time_confirmed |
|---|---|---|
| ALL_DAY_EVENT | start_date, end_date | true / false |
| DATE_ONLY_DEADLINE | end_date | false / false |
| TIME_CONFIRMED_DEADLINE | end_date, end_datetime | false / true |
| TIME_CONFIRMED_EVENT | start_date, end_date, start_datetime, end_datetime | false / true |
| SINGLE_POINT_APPOINTMENT | start_date, start_datetime | false / true |

- 날짜 전용 일정에 00:00나 23:59:59를 만들어 넣지 않는다. 마감 시각을 모르면 DATE_ONLY_DEADLINE으로 저장한다.
- ALL_DAY_EVENT의 end_date는 포함되는 마지막 날짜다. 하루 일정은 시작일=종료일. 시작일≤종료일이어야 한다.
- TIME_CONFIRMED_EVENT는 시작 일시<종료 일시여야 한다. 날짜는 각 일시를 Asia/Seoul로 변환한 달력 날짜와 일치해야 한다.
- 시각 확정 마감/약속도 해당 date와 datetime의 서울 날짜가 일치해야 한다. 불일치하면 조용히 고치지 말고 422를 반환한다.
- 예: `2026-10-01T00:30:00+09:00`은 `2026-09-30T15:30:00Z`로 저장하되 대응 date는 `2026-10-01`이다.
- 잘못된 날짜, 윤년 오류, 역전 구간, 필수값 null, 금지 필드 값, 알 수 없는 enum을 422로 거부한다. 과거 일정은 유효한 입력으로 허용한다.
- 신청 기간과 최종 마감일을 함께 보관하려면 기간 행사나 별도 마감 일정으로 표현한다. 이번에는 모호한 혼합 유형을 추가하지 않는다.

## 4. API 계약

모든 엔드포인트는 유효한 기존 bearer 세션이 필요하다.

| Method | 경로 | 동작 |
|---|---|---|
| POST | /api/v1/schedules | 확인된 일정 생성, 201 및 일정 객체 |
| GET | /api/v1/schedules | 본인 일정 목록, 200 |
| GET | /api/v1/schedules/{schedule_id} | 본인 일정 상세, 200 |
| PATCH | /api/v1/schedules/{schedule_id} | 일부 필드 수정, 200 및 수정된 일정 객체 |
| DELETE | /api/v1/schedules/{schedule_id} | 본인 일정 삭제, 204 본문 없음 |

### 접근 제어

- 다른 사용자의 정상 UUID와 존재하지 않는 UUID는 GET/PATCH/DELETE에서 동일한 안전한 404 응답을 반환한다. UUID 형식 자체가 잘못된 경우는 422로 처리할 수 있다.
- 목록, 상세, 수정, 삭제의 DB 쿼리는 항상 인증된 user_id로 범위를 제한한다. PK만으로 UPDATE/DELETE하지 않는다.
- 누락·만료·폐기·변조 토큰은 기존 401 계약을 유지한다. 오류 응답에 SQL/스택/다른 사용자 정보/원시 예외를 노출하지 않는다.

### PATCH 의미

- 미전송 필드는 기존 값 보존, 명시적 null은 nullable 필드 비우기다. 필수 기본 필드(title/kind/timezone/priority/is_completed)의 null은 거부한다.
- 입력값과 기존 레코드를 합친 최종 상태 전체에 시간 모델 검증을 적용한다. 별도 create 모델로 변환하면서 생략값을 덮어쓰지 않는다.
- 유형을 변경할 때는 새 필수 필드를 제공하고 기존 금지 필드를 명시적 null로 지워야 한다. 모순되는 잔여 필드를 자동 삭제하지 않는다.
- confirmed=true 외에 변경 필드가 하나도 없는 PATCH는 422. 검증 실패 시 DB에 부분 변경이 없어야 한다.

### 목록과 캘린더 조회

- 선택 필터: `date_from`, `date_to`(YYYY-MM-DD, 양끝 포함), `is_completed`, `priority`.
- 날짜 필터는 둘 다 제공하거나 둘 다 생략한다. 하나만 제공하거나 date_from>date_to면 422.
- 기간 일정은 [start_date, end_date]가 조회 기간과 겹치면 반환한다. 마감은 end_date, 단일 약속은 start_date로 판단한다. 월 경계를 걸친 일정도 누락하면 안 된다.
- `limit`: 기본 50, 1~100. `offset`: 기본 0, 0 이상.
- 응답: `{ "items": [...], "total": N, "limit": 50, "offset": 0 }`. total은 본인 소유+필터 적용 후, 페이지 제한 전 건수다.
- 정렬: 일정 기준 날짜(start_date가 있으면 start_date, 아니면 end_date) 오름차순, 동률은 id 오름차순. 완료·중요도는 필터이며 암묵적인 정렬 기준으로 섞지 않는다.

## 5. 저장·마이그레이션·모듈 경계

- v1 users/sessions 마이그레이션을 수정하거나 재실행해서 초기화하지 말고 v2를 추가한다. 기존 계정·유효 세션 보존을 실제 검사한다.
- 외래키 및 적절한 user_id 인덱스, 가능한 CHECK/NOT NULL 제약을 적용한다. SQL 파라미터 바인딩과 필요한 트랜잭션을 사용한다.
- 일정 라우터·서비스/저장 접근·입출력 스키마를 분리한다. 검증 규칙은 create/PATCH가 공통으로 사용하도록 구성한다.
- 기존 /health, /api/query, /api/retrieve 및 인증 API 계약을 보존한다. 정적 프론트엔드 mount 전에 새 라우터를 등록한다.
- 테스트 시작부터 lifespan과 요청 양쪽을 임시 DB로 격리하고 RAG prewarm을 끈다. 실제 모델 다운로드·Chroma 접근·외부 API를 유발하지 않는다.
- R1-A 검수의 fixture 보완을 함께 반영한다: 기존 dependency_overrides 사본 복구, 기본 DB 접근 시 실패하는 보호 검사, 숫자 비밀번호 비노출 assertion의 느슨한 or 제거. 변경 범위를 보고서에 명시한다.

## 6. 완료 기준과 테스트

임시 파일 SQLite + TestClient를 사용하여 실제 동작을 검증한다. mock 저장소만으로 통과시키지 않는다.

1. 5개 일정 유형 각각 생성→목록/상세→수정→삭제. 완료 여부·중요도 및 근거 메타데이터 보존.
2. 계정 A/B: A의 목록과 total에 B 일정 미포함. B의 UUID를 아는 A가 GET/PATCH/DELETE해도 404이고 B의 데이터·updated_at에 변화 없음.
3. user_id/id/서버 시각/계산 필드 주입 거부, confirmed 누락·false·문자열 거부, 유효한 토큰 없는 모든 엔드포인트 차단.
4. 날짜-only에 시각을 발명하지 않음, 서울 자정 전후 UTC 변환, 윤년, 날짜/시각 불일치, naive/숫자 datetime, 역전 기간, 금지·누락 필드 거부.
5. PATCH 생략과 명시적 null 구분, 날짜/유형 전환의 최종 상태 검증, 실패 후 데이터 불변.
6. 월 경계·다일 기간·한 날짜 마감·시작 시각만 있는 약속의 목록 필터, total·페이지네이션·정렬, 다른 계정 건수 미노출.
7. v1 DB에 실제 사용자·유효 세션을 만든 뒤 v2 업그레이드. 재실행 시 데이터 보존, 이전 토큰 유효, 신규 일정 생성 가능. 실패한 migration의 부분 반영 방지.
8. 별도 프로세스 종료/재기동 후 계정·세션·일정 보존. 임시 DB를 사용하며 uvicorn 실배포 완료라고 주장하지 않는다.
9. 기존 인증 및 관련 RAG 회귀 검사. 모든 runtime DB/sidecar는 Git 제외 유지.

테스트 수를 미리 맞추지 말고 필요한 사례를 parametrize하라. `.venv/bin/python`을 사용한다. 먼저 신규 테스트를 실행하고 통과하면 기존 승인 회귀를 결합해 실행한다:

```sh
.venv/bin/python -m pytest tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
```

파일 분리가 필요하면 실제 명령과 이유를 보고한다. 전체 테스트를 무작정 실행하지 않는다.

## 7. 산출물과 금지 사항

- 구현 및 `tests/test_schedules.py`(필요한 테스트 분리 허용).
- `docs/campusmate_schedule_api_guide.md`: 5개 유형의 요청 예시, PATCH null 의미, 사용자 확인·접근 제어, 날짜 필터·페이지네이션, 마이그레이션 안내. 수동 생성 예시에는 confirmed=true를 포함한다.
- `docs/gemini_round1b_report.md`: 변경 파일, 설계 결정, 실제 실행 명령/결과, v1→v2 계정·세션 보존 증거, 계정 격리 증거, 미검증 사항.
- R0 문서/픽스처 및 원본 완료 보고서는 덮어쓰지 않는다. 이번 확정 계약과 R0 초안의 차이는 새 가이드에 기록한다.
- 운영 계정 DB·Chroma·원시 JSON·사용자 문서를 보존한다. migration 검증을 위해 사용자 DB를 열거나 변경하지 않는다.
- 실제 LLM 호출, 크롤링, 모델 변경, 배포, commit/push는 하지 않는다. 의존성 전체 업그레이드도 하지 않는다.
- R1-B만 구현하고 보고한다. R2 추출 및 R3 UI는 Codex 검수 이후 별도 프롬프트로 진행한다.
