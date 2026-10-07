# CampusMate R0 구현 완료 보고서 (Gemini)

- **작성 일자:** 2026-09-23
- **담당:** 구현 담당 (Gemini)
- **검수 수신:** 설계·검수 총괄 (Codex)
- **대상 단계:** R0 — 기존 결함 수정 및 평가 기준 확정

---

## 1. 변경 요약

1. **작업 A (날짜 파서 결함 수정):**
   - `scripts/build_unified_dataset.py` 내 `import re`, `timedelta` 누락으로 인해 발생하던 `NameError: name 're' is not defined` 결함을 최소 수정으로 해결.
   - `parse_iso_datetime`에 엄격한 완전 일치(`^...$`) 정규식을 적용하여 `2026.09.23garbage`와 같은 부분 일치 입력이 유효 날짜로 오인식되는 취약점을 원천 차단.
   - None, 빈 문자열, 달력상 존재하지 않는 날짜(예: 2월 30일), 점 구분 날짜, 시각 선택 입력, 타임존(+09:00/Z)을 일관되게 처리하고 예외 대신 `None`을 반환하도록 안정화.
   - 기존 정책(시간대 없는 날짜 입력의 UTC 간주 처리)을 보존하고 함수 docstring에 명시.
   - 문서 충돌 해결(`resolve_document_conflict`) 시 비정상 날짜나 점 구분 날짜가 포함되어도 데이터셋 통합 프로세스가 중단되지 않음을 검증.

2. **작업 B (평가 기준선 및 합성 픽스처 구축):**
   - `docs/campusmate_evaluation_baseline.md` 작성:
     - 30~50문항 확장을 위한 10대 분류표(CAT-01 ~ CAT-10) 수립.
     - 로컬 지식 베이스(`data/unified_campus_knowledge.json`, 1,366건) 전수 대조를 통한 초기 대표 사례 10개 정의 (허위 사실/URL 일절 배제, 로컬 미수집 항목은 '평가 준비 미완료'로 명시).
     - 과거 검토에서 발생한 지연 시간 왜곡을 방지하기 위한 4대 상태(`PASS`, `MOCK_SUCCESS`, `API_ERROR`, `NOT_RUN`) 독립 보고 체계 및 지연 시간 집계 원칙 정의.
     - 실서비스 미검증 항목 및 후속 R1(인증/일정 API) 데이터 계약 초안(날짜-only vs 시각 확정 분리, 사용자 소유권 격리) 명세.
   - `tests/fixtures/schedule_extraction_cases.json` 작성:
     - 기준 시각(`2026-09-23T15:00:00+09:00`)과 `Asia/Seoul` 시간대를 고정한 22개 합성 검증 사례 구축.
     - 단일/다단계 마감, 종일/시각확정, 상대일자, 취소/연장, 달력오기, 비일정 텍스트, 모호성 사유(`ambiguity_reason`) 및 사용자 확인 필수(`requires_user_confirmation: true`) 처리.

---

## 2. 파일 목록

| 파일 경로 | 구분 | 설명 |
|---|---|---|
| `scripts/build_unified_dataset.py` | [MODIFY] | `re`, `timedelta` import 추가, `parse_iso_datetime` 완전 일치 정규식 및 docstring 보강 |
| `tests/test_date_parsing.py` | [NEW] | 날짜 파서 결함 재현, 경계값 검증, 부분 일치 차단, 충돌 해결 중단 방지, 픽스처 정합성 검증 (24개 테스트) |
| `tests/fixtures/schedule_extraction_cases.json` | [NEW] | 향후 R2 일정 추출 검증용 합성 픽스처 22건 (Asia/Seoul 고정) |
| `docs/campusmate_evaluation_baseline.md` | [NEW] | 30~50문항 분류표, 초기 대표 10사례, 상태 보고 기준, R1 데이터 계약 초안 |
| `docs/gemini_round0_report.md` | [NEW] | R0 작업 수행 결과 및 Codex 검수 요청 보고서 (본 문서) |

---

## 3. 수정 전 재현 및 수정 후 결과

### 3.1 수정 전 재현 (Before Fix)

- **재현 명령:**
  ```bash
  .venv/bin/python -c "from scripts.build_unified_dataset import parse_iso_datetime; parse_iso_datetime('2026.09.23')"
  .venv/bin/python -c "from scripts.build_unified_dataset import parse_iso_datetime; parse_iso_datetime('invalid')"
  ```
- **결과:**
  두 입력 모두 `NameError: name 're' is not defined. Did you forget to import 're'?` 예외 발생 확인.
- **부분 일치 취약점:**
  `r"^(\d{4})[-.](\d{2})[-.](\d{2})..."`에 종단 앵커(`$`)가 없어 `parse_iso_datetime('2026.09.23garbage')`가 쓰레기 값을 버리고 `datetime(2026, 9, 23)`을 반환하는 오인식 결함 확인.
- **초기 회귀 테스트(`tests/test_date_parsing.py`):**
  18개 항목 실패 (`18 failed, 5 passed in 0.11s`).

### 3.2 수정 후 결과 (After Fix)

- **정상 날짜 및 점 구분 날짜:**
  - `parse_iso_datetime('2026-09-23')` -> `datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)`
  - `parse_iso_datetime('2026.09.23')` -> `datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)`
- **예외 문자열 및 쓰레기 값 방어:**
  - `parse_iso_datetime('invalid')` -> `None` (예외 없음)
  - `parse_iso_datetime('2026.09.23garbage')` -> `None` (부분 일치 오인식 차단)
  - `parse_iso_datetime('2026-02-30')` -> `None` (달력상 유효하지 않은 날짜 방어)
  - `parse_iso_datetime('2026.02.29')` -> `None` (2026년 평년 윤일 방어)
- **시간대 변환:**
  - `parse_iso_datetime('2026-09-23T15:00:00+09:00')` -> `datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)`
  - `parse_iso_datetime('2026.09.23 15:00:00+09:00')` -> `datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)`
- **전용 회귀 테스트 통과:**
  24개 항목 전체 통과 (`24 passed in 0.02s`).

---

## 4. 정확한 실행 명령 및 통과/실패 수

### 4.1 기본 회귀 검증 슈트 (Codex 지정 3개 파일)

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py -q
  ```
- **실행 결과:**
  `30 passed, 1 warning in 5.87s` (통과 30건, 실패 0건, 경고 1건)
  *(경고: Starlette TestClient의 anyio BlockingPortal 관련 deprecation 경고이며 프로젝트 코드와 무관)*

### 4.2 신규 날짜 파서 및 픽스처 정합성 회귀 테스트

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_date_parsing.py -v
  ```
- **실행 결과:**
  `24 passed in 0.02s` (통과 24건, 실패 0건)

### 4.3 전체 통합 회귀 실행 (4개 파일 일괄)

- **실행 명령:**
  ```bash
  .venv/bin/python -m pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
  ```
- **실행 결과:**
  `54 passed, 1 warning in 5.70s` (통과 54건, 실패 0건)

---

## 5. 미실행 항목 (Scope Restrictions Respected)

지침에 따라 R0 작업 범위를 엄격히 준수하였으며 다음 작업은 일절 수행하지 않았습니다:
1. **실제 LLM API 호출:** Gemini API를 직접 호출하는 라이브 생성 평가는 수행하지 않음 (유료 한도 소진 방지).
2. **신규 웹 크롤링 및 DB 재색인:** 기존 통합 데이터(1,366건) 및 공지 아카이브(960건)를 온전히 보존하고 크롤러를 재실행하지 않음.
3. **R1 계정/일정 API 구현:** 데이터 계약 초안만 수립하였으며, `backend/main.py`에 API 엔드포인트나 DB 테이블을 추가하지 않음.
4. **Git Commit/Push:** 변경 사항은 작업 디렉터리에만 반영하였으며 커밋이나 푸시를 진행하지 않음.

---

## 6. 남은 위험 및 후속 라운드 주의사항

1. **시간대 정책 전환 (UTC vs Asia/Seoul):**
   - 현재 `build_unified_dataset.py`의 `parse_iso_datetime`은 기존 충돌 해결 규칙과의 호환성을 위해 시간대 미지정 입력을 `UTC`로 정규화합니다.
   - 반면 후속 R2의 학생 서비스 일정 추출은 한국 표준시(`Asia/Seoul`)를 기준으로 마감 일시를 해석해야 하므로, 일정 추출 모듈 전용 파서에서 시간대 해석 정책이 분리 적용되어야 합니다.
2. **라이브 API Quota 한도 위험:**
   - 향후 30~50문항 실제 LLM 생성 평가 시 429 Resource Exhausted가 발생할 위험이 상존합니다. `scripts/run_eval.py`의 체크포인트 원자적 저장 및 NOT_RUN 분리 집계 체계를 반드시 준수하여 실행해야 합니다.
3. **사용자 소유권 격리 검증 (R1 착수 시):**
   - R1 구현 시 타 계정의 `schedule_id`를 통한 인가 우회(BOLA/IDOR) 취약점이 발생하지 않도록 모든 DB 쿼리에서 `user_id` 조건을 필수로 검증하는 단위 테스트가 선행 작성되어야 합니다.

---

**보고서 경로:** `docs/gemini_round0_report.md`  
Codex 검수를 요청합니다.
