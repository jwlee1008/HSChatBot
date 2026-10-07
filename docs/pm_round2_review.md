# CampusMate R2 PM 검수 보고서 — 승인 (Approved)

- **검수일**: 2026-09-24
- **검수자**: PM (Antigravity Orchestrator)
- **대상 마일스톤**: CampusMate R2 — 자연어/공지 일정 후보 추출 및 Zero-Auto-Save 데이터 계약

---

## 1. 판정: 승인 (Approved)

R2 마일스톤 구현을 공식 **승인**한다.
일꾼 서브에이전트가 작성한 코드(`backend/schemas.py`, `backend/schedules/extraction.py`, `backend/routers/schedules.py`)와 테스트 슈트(`tests/test_schedule_extraction.py`), 그리고 완료 보고서(`docs/gemini_round2_report.md`)를 독립적으로 전수 검토하였다.

핵심 요구사항인 **Zero-Auto-Save 계약(사용자 확인 필수 원칙)**, 23개 실무 픽스처 케이스 전수 일치, 세션 토큰 인증 게이트, 오프라인 결정적 엔진 동작, DB 불변성이 코드 및 자동화 테스트로 증명되었다.

다음 단계는 **R3: 최소 캘린더 통합 UI 및 사용자 확인 상호작용**이다.

---

## 2. 세부 검수 항목 및 결과

### 2.1 [PASS] Zero-Auto-Save 원칙 및 스키마 불변성
- `/api/v1/schedules/extract` 엔드포인트는 `db: sqlite3.Connection` 의존성을 아예 주입받지 않는 순수 인메모리/비영속 분석 엔드포인트로 설계되었다.
- `ScheduleCandidate` Pydantic 모델의 `requires_user_confirmation: StrictBool` 필드는 `field_validator`를 통해 `True` 외의 값이 주입될 경우 `ValidationError`를 발생시킨다 (`tests/test_schedule_extraction.py::test_schedule_candidate_requires_user_confirmation_enforced` 통과).
- 추출 API 호출 전후 DB 레코드 수 비교 테스트(`test_api_extract_db_immutability`)를 통해 호출 전후 DB 레코드 수가 동일(0건 변동)함을 입증하였다.
- 일정이 포함되지 않은 일반 안내문(sched-17)의 경우 응답 루트의 `requires_user_confirmation: false`를 정상 반환한다.

### 2.2 [PASS] 23개 픽스처 케이스 (`schedule_extraction_cases.json`) 전수 일치
- 23개 시나리오 전부에 대해 제목(`title`), 일정 유형(`schedule_kind`), 날짜/일시(`start_date`, `end_date`), 종일 여부(`is_all_day`), 시각 확정 여부(`is_time_confirmed`), 미확정 필드(`unconfirmed_fields`), 모호성 사유(`ambiguity_reason`), 원문 발췌문(`source_quote`, `source_quotes`), 자정 해석 옵션(`interpretation_options`), 취소 공지(`action`, `is_cancellation`)가 픽스처 기대치와 100% 일치함을 확인하였다.
- 외부 LLM(Gemini API)을 호출하지 않고 순수 오프라인/결정적 하이브리드 파서로 동작하여 네트워크 지연, 레이턴시, 토큰 소모를 배제하였다.

### 2.3 [PASS] API 보안 및 입력 유효성 검증
- 세션 토큰 없이 호출 시 `401 Unauthorized` 정상 차단 (`test_api_extract_unauthorized_blocked`).
- 빈 문자열, 공백 전용 문자열, 비정상 프로토콜 URL, 유효하지 않은 기준 일시 형식에 대해 `422 Unprocessable Entity` 거부 (`test_api_extract_validation_failures`).
- 동적 `reference_time` 주입 시 상대 날짜(오늘, 내일 등)가 주입된 기준 시간에 맞게 정확히 계산됨을 확인 (`test_api_extract_dynamic_reference_time`).

---

## 3. 테스트 실행 및 데이터 감사 결과

1. **R2 신규 테스트 슈트 (`tests/test_schedule_extraction.py`)**:
   - 실행 결과: **28 passed in 5.02s**
2. **전체 통합 회귀 테스트 (Full Regression Suite)**:
   ```bash
   PREWARM_RAG_ON_STARTUP=false .venv/bin/python -m pytest tests/test_schedule_extraction.py tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -q
   ```
   - 실행 결과: **142 passed, 1 warning in 35.94s** (기존 114건 + R2 28건)
3. **RAG 대표 10사례 근거 무결성 검증**:
   ```bash
   .venv/bin/python scripts/verify_rag_eval_evidence.py
   ```
   - 실행 결과: `data/unified_campus_knowledge.json` SHA-256 일치 및 **ALL PASS (10/10)**
4. **저장소 데이터 무결성**:
   - `data/` 하위 지식베이스 및 DB 파일의 무단 변경 없음을 확인.

---

## 4. 후속 마일스톤 안내

- **승인 마일스톤**: CampusMate R2 (일정 추출 및 사용자 확인 계약)
- **차기 마일스톤**: **CampusMate R3 — 최소 캘린더 통합 UI 및 사용자 확인 흐름 (React Frontend)**
  - 챗봇 답변 카드 내 [캘린더에 추가] 버튼 연동
  - 추출된 일정 후보 팝업 확인 모달 (날짜/시각/제목 수정 및 중복 클릭 방지)
  - 월간/오늘 개인 캘린더 뷰 및 일정 완료 토글/삭제 UI
