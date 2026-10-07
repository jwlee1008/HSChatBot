# Gemini 전달용 — R0 기존 결함 수정 및 평가 기준 확정

너는 CampusMate 구현 담당이고 Codex가 설계·검수 총괄이다. 이번에는 아래 R0만 수행하고 다음 기능으로 넘어가지 마라.

## 저장소와 현재 상태

- 저장소: `/Users/jwlee/study1/aisw` (다른 환경이면 실제 체크아웃 경로 사용).
- 먼저 적용되는 AGENTS.md, `docs/campusmate_improvement_plan_20260923.md`, 관련 소스/테스트를 읽어라.
- 시작 시 git status를 확인하고 사용자의 기존 미추적 문서 및 변경을 보존하라.
- Python은 프로젝트 `.venv/bin/python`을 사용한다. 시스템 python3는 이 환경에서 `str | None` 문법을 실행하지 못했다.
- 현재 통합 JSON은 1,366건, 아카이브 960건이다. 새로 수집하거나 재색인할 필요 없다.
- Codex가 아래 3개 테스트 파일을 실행하여 30 passed, 1 warning을 확인했다. 이것은 전체 서비스 검증이 아니다.

## 작업 A: 날짜 파싱 결함의 작은 수정

`scripts/build_unified_dataset.py`의 `parse_iso_datetime`에 대해 다음을 재현하라.

- `2026-09-23`: 정상 UTC datetime 반환.
- `2026.09.23`: 현재 `NameError: name 're' is not defined`.
- `invalid`: 현재 같은 NameError. 기대 결과는 예외 대신 None.

먼저 실패하는 회귀 테스트를 추가하고 최소 수정으로 해결하라. None/빈 문자열/존재하지 않는 날짜, ISO 시간대(+09:00/Z), 점 구분 날짜와 선택 시각을 검사하라. 정규식의 부분 일치로 `2026.09.23garbage` 같은 잘못된 입력을 정상 날짜로 받아들이지 않게 하라. 지원 형식은 함수 문서에 명시하고, 기존 날짜-only/시간대 없는 입력의 UTC 처리 정책은 이번에 바꾸지 마라. 서비스 일정 추출의 Asia/Seoul 정책은 후속 라운드다.

날짜 파싱 때문에 문서 전체 통합이 중단되지 않는 대표 사례를 검증하되 기존 충돌 해결 정책을 재설계하지 마라.

## 작업 B: 작은 평가 기준 파일

`docs/campusmate_evaluation_baseline.md`를 작성하라. 아래를 포함하되 실제 측정하지 않은 수치를 결과처럼 쓰지 마라.

1. 핵심 RAG 평가 30~50문항으로 확대할 분류표와 초기 대표 사례 10개: 질문, 기대 근거/판정 기준, 로컬 근거 확인 여부. 근거가 없으면 평가 준비 미완료로 표시하라. 가짜 학교 사실이나 URL을 만들지 마라.
2. 향후 일정 추출용 synthetic fixture 최소 20개를 `tests/fixtures/schedule_extraction_cases.json`에 작성하라. 기준 시각과 Asia/Seoul 시간대를 고정하고 입력, 기대 후보 일정 수, 확정 가능한 날짜/시각, 미확정 필드, 사용자 확인 필요를 포함하라. 정답을 하나로 고를 수 없는 상대 날짜 표현은 모호함으로 남겨라. API/구현은 추가하지 않는다.
3. API_ERROR, NOT_RUN, mock 성공과 실제 생성 성공을 구분하는 보고 방식.
4. 실제 서비스에서 미검증인 사항과 다음 R1(인증/일정 API)에 필요한 데이터 계약 초안. 날짜-only와 시각 확정 일정을 구분하고 사용자 소유권을 명시하라.

## 수정 범위 및 보존

- 허용: 날짜 파서의 작은 수정, 관련 회귀 테스트, 위 평가 문서/fixture, R0 완료 보고.
- 신규 기능, 대규모 리팩터링, 패키지 업그레이드, 운영 DB 변경, 기존 JSON/평가 결과 덮어쓰기, 재크롤링, 실제 LLM API 호출, 배포, commit/push는 이번 범위가 아니다.
- 비밀키/.env 값을 출력하거나 보고서에 넣지 마라.
- 과거 검토 보고서를 완료 상태에 맞춰 고쳐 쓰지 말고 새 보고서에 현재 검증 결과를 남겨라.

## 검증 및 보고

기본 회귀 명령:

```bash
.venv/bin/python -m pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py -q
```

추가 날짜 회귀 테스트도 실행하라. fixture의 JSON 문법과 기대 결과 일관성을 확인하라. 실패가 발생하면 원인과 이번 수정과의 관련성을 보고하라.

`docs/gemini_round0_report.md`에 변경 요약, 파일 목록, 수정 전 재현/수정 후 결과, 정확한 실행 명령과 pass/fail 수, 미실행 항목, 남은 위험을 적어라. 마지막 응답에 보고서 경로를 제시하고 Codex 검수를 기다려라.
