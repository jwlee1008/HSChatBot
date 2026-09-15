# CampusRAG Gemini 연동 및 데이터 통합 정정 보고서

**작성일**: 2026-09-15  
**작성 주체**: CampusRAG 구현·검증 담당  
**문서 목적**: Codex의 재검토 문서(`docs/codex_gemini_integration_review.md`)에서 지적된 6대 수정 사항(P1 4건, P2 2건) 및 주의 사항에 대해 원시 실행 결과 JSON 파일의 불변성을 유지하면서 사실 관계를 엄격히 정정하고, 코드 수정·재현 테스트·검증 결과·잔여 문제를 기록함.

---

## 1. 원시 실행 결과 정합성 정정 (Item 5 관련)

기존 `docs/gemini_integration_review.md`의 일부 기술(특히 제3.3절 6대 사례 표)에서 검색 검증과 답변 생성을 혼동하여 "Gemini 생성 PASS"로 과장 표현된 내용을 다음과 같이 원시 데이터 사실에 입각하여 정정한다.

### 1.1 원시 파일의 실제 상태 분석

| 원시 실행 파일 | 대상 질문 ID / 건수 | 실제 HTTP/생성 상태 | 정정 판정 |
| --- | --- | --- | --- |
| `data/gemini_integration_results.json` | 9개 프로브 (취업멘토링, 편입생, 국가장학금 등) | **9건 전원 429 RESOURCE_EXHAUSTED** (`status: "api_error"`) | **검색 근거 검증 완료 / LLM 답변 미검증** |
| `data/gemini_smoke_results.json` | `dev-md-05` (1건) | **200 OK 정상 텍스트 생성 완료** (`status: "PASS"`) | **Gemini 답변 생성 PASS 실증 (근거 확보)** |
| `data/eval_phase2_expansion_results.json` | `exp-02` (1건) | **200 OK 정상 텍스트 생성 완료** (`answer_eval.status: "PASS"`, 지연 시간: 3.64초) | **Gemini 답변 생성 PASS 실증 (근거 확보)** |
| `data/eval_phase2_expansion_results.json` | `exp-01`, `exp-03` ~ `exp-10` (9건) | **429 RESOURCE_EXHAUSTED** (`answer_eval.status: "API_ERROR"`) | **검색 근거 확인 / 답변 미검증 (API_ERROR)** |

### 1.2 생성 PASS 증명 가능 항목 (Ground Truth)
저장소 내에서 실제 Gemini API(`gemini-3.8-flash`) 200 OK 응답으로 생성 성공이 증명된 항목은 다음 **단 2건**이다:
1. **`dev-md-05`** (`data/gemini_smoke_results.json`):
   - 질문: *"국가전문자격시험 합격생 장학금 대상에 공인회계사랑 세무사도 포함돼?"*
   - 생성 답변: *"네, 국가전문자격시험 합격생 장학금 대상 시험에 공인회계사(CPA)와 세무사 모두 포함됩니다. 본 공지에 따르면 변리사, 공인회계사, 미국공인회계사, 세무사, 감정평가사, 관세사 등이 대상 시험으로 명시되어 장학 혜택을 받을 수 있습니다..."*
   - 실행 시각: `2026-09-15T04:41:02.187147+00:00`, source_db: `data/verify_demo_chroma_db`
2. **`exp-02`** (`data/eval_phase2_expansion_results.json`):
   - 질문: *"편입생 전적대학 학점 재인정 신청 대상자가 누구야?"*
   - 생성 답변: *"전적대학 학점 재(추가)인정 신청 대상자는 일반편입생 중 전적대학 학점 추가인정 또는 재인정 신청 대상자이며, 외국인 유학생은 대상에서 제외됩니다..."*
   - 실행 시각: `2026-09-15T14:05:53.429189+09:00`, latency: **3.64초**, score: 1.0 (PASS)

### 1.3 6대 프로브 항목에 대한 정정
`data/gemini_integration_results.json`의 9개 프로브 항목은 검색 단계에서 Top-3 후보 청크를 정확하게 회수(`candidate_k` 확장 및 가중치 보정 효과)하였으나, 최종 LLM 호출 시 429 한도 초과로 인해 실제 답변 생성이 완료되지 못했다. 따라서 본 보고서는 이들 항목을 **"검색 검증 완료 / 답변 미검증 (API 한도 초과)"** 상태로 공식 정정한다.

### 1.4 지연 시간 및 쿼터 해석 정정
1. **지연 시간 p95 2.25초의 왜곡 해소**:
   - `data/eval_phase2_expansion_results.json`의 p95 2.25초는 10건 중 9건의 429 빠른 실패(0.27~0.55초)가 포함되어 왜곡된 수치이다.
   - 실제 정상적인 단일 LLM 생성 호출(`exp-02`)의 지연 시간은 **3.64초**이다.
2. **Free Tier 할당량(Quota)의 본질**:
   - Gemini Free Tier의 일일 요청 한도는 20 RPD(Requests Per Day)이다.
   - 요청 간격을 15~20초로 늘리는 슬립(Sleep) 조치는 분당 한도(15 RPM) 완화에는 유효하나, 일일 누적 20회 소진 시에는 효과가 없다.
   - 따라서 추가 API 호출을 전면 중단하고, mock/fixture 기반의 회귀 테스트로 검증 방식을 전환하였다.

---

## 2. 6대 수정 사항별 구현 및 검증 상세

### [수정 사항 1] 데이터 갱신 우선순위 및 출처 오염 방지 (P1)
- **변경 파일**: `scripts/build_unified_dataset.py`
- **구현 내용**:
  1. `resolve_document_conflict()` 함수 도입: 단순 길이 비교 대신 타임스탬프(`source_updated_at`, `date`, `collected_at`) 비교 우선 적용.
  2. 실패 보존(Failure Preservation): 신규 수집 문서가 `title_only`인 경우, 기존의 유효한 `text`, `mixed`, `ocr_enhanced` 본문을 절대 덮어쓰지 못하도록 차단 (`preserve_existing_valid_content_over_empty_crawl`).
  3. 정상 변경 반영: 최신 공지의 마감 정정이나 본문 축소가 발생하더라도, 신규 문서의 타임스탬프가 최신이면 단축된 본문을 정상 채택 (`newer_version_adopted`).
  4. OCR 보강본 우선: 동일 일자에서 `ocr_enhanced` 문서가 일반 텍스트보다 우선 채택 (`adopt_ocr_enriched_over_plain_text`).
  5. 227행 결함 수정: 문서 병합 루프에서 신규 문서가 기각(skipped)된 경우, 기존 문서의 `_source_name`이 신규 소스명으로 오염되던 버그를 원천 수정. 오직 신규 문서가 최종 채택되었을 때만 `_source_name` 갱신.
  6. 투명한 매니페스트 기록: `data/unified_manifest.json`에 73건의 충돌 해결 이력(`resolution_log_sample`)을 구조화하여 기록.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py::test_source_name_not_corrupted_on_skipped_document` (통과)
  - `tests/test_codex_fixes.py::test_resolve_document_conflict_timestamp_and_failure_preservation` (통과)

### [수정 사항 2] 격리 DB 경로 방어 (P1)
- **변경 파일**: `scripts/ingest_unified_db.py`
- **구현 내용**:
  1. `validate_persist_dir()` 방어 함수 구현: 운영 DB(`data/chroma_db`), 기존 검증 DB(`data/verify_demo_chroma_db`, `data/eval_chroma_db`) 및 그 상·하위 경로를 목적지로 지정할 경우 즉시 `PermissionError`를 발생시켜 적재를 원천 차단.
  2. 심볼릭 링크 차단: `os.path.islink()` 검사로 심볼릭 링크를 통한 우회 적재 시도 즉시 거부.
  3. 기존 디렉터리 잔존 청크 방어: 목적지 디렉터리에 이미 파일이 존재하는 경우, `--clean` 또는 `--allow-existing`이 명시되지 않으면 `FileExistsError` 발생. `--clean` 지정 시 안전하게 기존 잔존 데이터를 초기화(`shutil.rmtree`) 후 재적재.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py::test_ingest_rejects_protected_paths_and_symlinks` (통과)
  - `tests/test_codex_fixes.py::test_ingest_directory_safety_and_clean_option` (통과)

### [수정 사항 3] 무관 질문 사전 필터 우회 차단 (P1)
- **변경 파일**: `core/rag.py`
- **구현 내용**:
  1. `OFF_TOPIC_PATTERNS` 정규식 필터 도입: 파이썬, 자바, 코딩, 알고리즘, 이진 탐색, 아이폰, 스마트폰, 날씨 등 캠퍼스 학사와 무관한 도메인 패턴 감지.
  2. 무관 질문 감지 시 어휘 가산점(+0.08)을 절대 부여하지 않으며, 관련성 임계값을 0.40으로 대폭 상향하여 학사 공지가 우연히 통과하는 현상을 원천 차단.
  3. 결과적으로 후보 청크가 0건으로 반환되어, LLM 호출 없이 조기에 `no_context` 유보 응답을 반환.
  4. 단축 검색어 구제 제한: 어휘 보너스는 일반 단어나 연도가 아닌 `SPECIALIZED_TERMS`(`topcit`, `toeic`, `toefl`, `cpa`, `aicpa`, `k-mooc` 등) 및 3자 이상의 영문 대문자 고유 약어에만 국한하여 적용.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py::test_lexical_bonus_does_not_bypass_irrelevant_queries` (통과)
  - `tests/test_codex_fixes.py::test_specialized_terms_retrieval_rescue` (통과)
  - `tests/test_retrieval_grounding.py::TestRetrievalGrounding::test_irrelevant_query_not_bypassed_by_generic_words` (통과)
  - `tests/test_retrieval_grounding.py::TestRetrievalGrounding::test_short_query_lexical_preservation_real` (통과)

### [수정 사항 4] 서비스 응답 오류 상태 유실 방지 (P1)
- **변경 파일**: `backend/schemas.py`, `backend/main.py`, `frontend/app.py`
- **구현 내용**:
  1. `QueryResponse` 스키마 확장: `status`(`success`, `no_context`, `title_only_notice`, `api_error`), `api_called`(bool), `provider`(str), `model`(str), `error_type`(`rate_limit`, `service_unavailable`, `auth_error`, None) 필드 추가.
  2. 보안 격리: 백엔드에서 원시 예외 스택트레이스, 내부 시스템 정보, API 키/토큰을 사용자 응답 JSON에 일절 노출하지 않고 정제된 `error_type`으로 매핑.
  3. 프론트엔드 연동: Streamlit UI에서 `status == "api_error"` 수신 시 상단에 사용자 친화적 경고 배너(429 요청 한도 도달, 503 서버 일시 혼잡, 403 인증 오류) 렌더링.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py::test_fastapi_query_response_contracts` (FastAPI TestClient 기반 계약 6종 검증 통과)

### [수정 사항 5] 검증 결과와 완료 주장의 불일치 해소 (P2)
- **구현 내용**:
  1. 본 정정 보고서 작성을 통해 원시 파일의 수정을 금지한 상태에서 성공 응답(2건)과 한도 초과 응답(9건)을 엄격히 분리 서술.
  2. 지연 시간 왜곡(p95 2.25s)에 대한 실제 정상 생성 시간(3.64s) 분리 기록.
  3. 429 반복 시 체크포인트 및 중단 원칙 수립.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py::test_ground_truth_raw_evidence_integrity` (원시 파일 정합성 검증 통과)

### [수정 사항 6] 단위 테스트 전면 정비 및 외부 의존 제거 (P2)
- **변경 파일**: `tests/test_retrieval_grounding.py`, `tests/test_codex_fixes.py`
- **구현 내용**:
  1. 외부 DB 및 임베딩 모델 로드 의존성을 제거한 `_create_mock_rag()` 팩토리 구현.
  2. `test_short_query_lexical_preservation_real`을 실제 `rag.retrieve()` 메서드를 호출하여 반환 결과를 검증하는 형태로 개선.
  3. FAQ ID 고유 식별 회귀 테스트: 동일 URL을 공유하는 여러 FAQ가 ID 기반으로 고유 키를 생성하여 서로 덮어쓰지 않는 동작 검증.
  4. 상시 안내 정책 회귀 테스트: `guidance`, `faq`, `form` 문서가 오래된 등록일자나 연도 불일치로 인해 부당하게 감점되지 않는 동작 검증.
- **재현 및 검증 테스트**:
  - `tests/test_codex_fixes.py` 10개 테스트 전원 통과.
  - `tests/test_retrieval_grounding.py` 7개 테스트 전원 통과.
  - `tests/test_evaluator.py` 11개 테스트 전원 통과.

---

## 3. 전체 테스트 검증 결과 요약

### 실행 명령
```bash
.venv/bin/pytest tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_evaluator.py -v
```

### 실행 결과
- **총 28개 테스트 전원 통과 (28 passed in 7.35s, 0 failed, 0 skipped)**
- **실제 Gemini API 호출 건수: 0건 (Mock / Fixture / In-memory 격리 검증 완수)**
- **운영 DB(`data/chroma_db`) 및 기존 검증 DB 파일 변경: 0건 (불변성 보존)**

---

## 4. 2차 재검토(Round 2) 5대 수정 사항별 구현 및 검증 상세

Codex의 2차 재검토(`docs/codex_gemini_integration_review_round2.md`)에서 지적된 5대 결함(P1 4건, P2 1건)에 대해 신규 재현 테스트 슈트(`tests/test_codex_round2_fixes.py`)를 먼저 작성하여 실패를 확인한 후 완벽히 수정 및 재검증하였다.

### [2차 수정 1] 게시일이 동일한 정정본 채택 및 타임스탬프 분리 (P1)
- **결함 배경**: `scripts/build_unified_dataset.py`에서 `date[:10]`을 슬라이싱하여 날짜만 비교했기 때문에, 게시일(예: `2026-09-01`)이 변경되지 않은 상태에서 마감일 단축 정정('9월 20일 마감' -> '9월 15일 마감') 및 본문 변경이 발생해도 확인 시각 차이가 무시되고 긴 본문/소스 우선순위 규칙에 의해 신규 정정본이 기각됨.
- **구현 내용**:
  1. `parse_iso_datetime()` 도입: ISO-8601 및 날짜 문자열을 timezone-aware (UTC 기준) datetime 객체로 표준화.
  2. 타임스탬프 의미론적 분리:
     - `source_updated_at`: 공지 원문 수정일 (가장 권위 있음).
     - `date`: 공지 목록의 최초 게시일.
     - `last_checked_at`: 크롤러의 수집/확인 시각.
  3. `resolve_document_conflict()` 충돌 해결 정책 고도화:
     - 게시일(`date`)이 동일하고 본문이 다른 경우, `last_checked_at` 시각을 정밀 비교하여 신규 크롤링 시각이 더 최신이면 본문 정정/단축 공지라도 최신본 채택 (`newer_crawl_revision_adopted`).
     - 원문 수정일(`source_updated_at`)이 명시된 경우 단순 재수집 시각보다 우선하여 과거 캐시본의 덮어쓰기를 방지 (`preserve_authoritative_source_updated_at`).
     - UTC와 KST 간 타임존 인식 epoch 비교 구현.
     - `title_only` 빈 크롤링이 기존 유효 본문을 덮어쓰지 못하도록 하는 실패 보존(Failure Preservation) 원칙 엄격 유지.
- **재현 및 검증 테스트**:
  - `tests/test_codex_round2_fixes.py::test_same_date_later_crawl_content_revision_adopted` (통과)
  - `tests/test_codex_round2_fixes.py::test_source_updated_at_stronger_than_last_checked_at` (통과)
  - `tests/test_codex_round2_fixes.py::test_timezone_aware_timestamp_comparison` (통과)

### [2차 수정 2] `--clean`/`--allow-existing` 제거 및 새 경로만 강제 (P1)
- **결함 배경**: `scripts/ingest_unified_db.py`에 `--clean`(shutil.rmtree) 및 `--allow-existing` 옵션이 존재하여, 잔존 청크 혼입이나 사용자 데이터 오삭제 위험이 존재함.
- **구현 내용**:
  1. CLI 인수 파서 및 함수 시그니처(`validate_persist_dir`, `ingest_unified`)에서 `--clean`, `--allow-existing` 매개변수 전면 제거.
  2. `validate_persist_dir` 검증 강화: 대상 디렉터리가 이미 존재하는 경우 (빈 디렉터리, 파일, DB 디렉터리 무관) 즉시 `FileExistsError` 발생. 오직 아직 존재하지 않는 신규 경로만 허용.
  3. 운영 DB(`data/chroma_db`), 기존 검증 DB(`data/verify_demo_chroma_db`, `data/eval_chroma_db`) 및 심볼릭 링크 경로는 `PermissionError`로 원천 차단.
- **재현 및 검증 테스트**:
  - `tests/test_codex_round2_fixes.py::test_ingest_strictly_requires_new_path_and_rejects_existing_dir` (통과)
  - `tests/test_codex_fixes.py::test_ingest_directory_safety_and_clean_option` (통과)
  - `tests/test_codex_fixes.py::test_ingest_rejects_protected_paths_and_symlinks` (통과)

### [2차 수정 3] 학내 기술 교육 질문 허용 vs 무관 코드 생성 차단 (P1)
- **결함 배경**: `core/rag.py`에서 "파이썬", "코딩", "알고리즘" 등의 단어가 감지되면 무조건 임계값을 0.40으로 올려, '교내 파이썬 코딩 교육 신청 방법 알려줘'와 같은 실제 SW중심대학 공지(점수 0.35)가 0건 처리되어 탈락함.
- **구현 내용**:
  1. `CAMPUS_INTENT_PATTERN` 도입: `교내`, `신청`, `모집`, `접수`, `교육`, `특강`, `일정`, `방법`, `프로그램`, `장학`, `학점`, `학사` 등의 학내 맥락이 포함된 질문은 off-topic 판정에서 완전 제외하여 정상 임계값(0.25)으로 통과.
  2. `CODE_GEN_REQUEST_PATTERN` 및 비학사 상식(`스펙`, `날씨` 등)에 대해서만 정밀하게 off-topic으로 판정:
     - 순수 코드 작성 요청(`코드 짜줘`, `구현해줘`, `알고리즘 구현`, `함수 작성`) 또는 외부 기기 스펙(`아이폰 스펙`)만 off-topic으로 차단하여 0건 반환 및 조기 `no_context` 유보.
  3. `TOPCIT`, `CPA`, `TOEIC` 등 학내 특수 약어 구제 로직(`SPECIALIZED_TERMS`) 완벽 유지.
- **재현 및 검증 테스트**:
  - `tests/test_codex_round2_fixes.py::test_campus_tech_education_queries_distinguished_from_generic_code_gen` (통과)
  - `tests/test_codex_fixes.py::test_lexical_bonus_does_not_bypass_irrelevant_queries` (통과)
  - `tests/test_codex_fixes.py::test_specialized_terms_retrieval_rescue` (통과)

### [2차 수정 4] 알 수 없는 API 예외 시 비밀정보 비노출 및 안전한 응답 (P1)
- **결함 배경**: `core/rag.py:261`에서 미분류 예외 발생 시 `err_str[:200]`을 answer 필드에 직접 포함하여, 내부 서버 URL이나 가짜 비밀 토큰(`SUPER_SECRET_TOKEN`)이 사용자 응답 및 API JSON에 노출될 수 있었음.
- **구현 내용**:
  1. `core/rag.py`: 미분류 예외 시 answer에 예외 원문을 일절 노출하지 않고, 사용자 친화적인 안전한 고정 안내문(`"AI 답변 생성 서비스에 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주시거나 학사 공지 원문을 확인해 주세요."`)을 반환하도록 교체.
  2. `backend/main.py`: `status == "api_error"` 응답 시에도 `error_type="internal_api_error"`로 구조화하여 전달하고, raw stacktrace나 secret이 포함되지 않도록 보장.
- **재현 및 검증 테스트**:
  - `tests/test_codex_round2_fixes.py::test_api_exception_sanitized_and_no_leak_in_answer_and_http` (가짜 비밀 토큰 `SUPER_SECRET_TOKEN_XYZ987654` 및 내부 URL `https://internal-mgmt.hansung.ac.kr:9443`이 answer 및 FastAPI HTTP 응답 text에 전혀 노출되지 않음을 확인, 통과)

### [2차 수정 5] 평가 실행 제어: 429 조기 중단, 원자적 체크포인트, 실행 조건 검증 및 명시적 재개 (P2)
- **결함 배경**: 
  1. `scripts/run_eval.py`가 429 한도 초과 이후에도 나머지 질문들에 대해 불필요한 API 호출을 계속 시도하고 실패 지연(0.27초)이 섞여 지연 시간이 왜곡됨.
  2. 실행 A 후 실행 B 실행 시 체크포인트가 검증 없이 재사용되어 다른 실행 문항이 섞이는 데이터 오염 발생.
  3. 체크포인트 저장이 원자적이지 않아 저장 중단 시 파일 손상 위험.
- **구현 내용**:
  1. `extract_execution_context()` 및 `validate_checkpoint_context()` 도입:
     - 데이터셋 SHA-256 해시, `split`, `provider`/`model`, Chroma DB 경로, `top_k`, `relevance_threshold` 등 실행 조건을 추출 및 체크포인트에 기록.
     - `resume=True` 시 실행 조건 불일치 감지 즉시 `ValueError` 발생시켜 이종 실행 간 결과 혼입 원천 차단.
  2. 명시적 재개(`resume=True`) 및 상태별 재시도 정책(`retry_policy="failed_and_unrun"`):
     - 성공 완료(PASS/정상 응답): 보존 및 재호출 스킵.
     - 실패 문항(`API_ERROR`): 재시도하되 이전 실패 시도 정보를 `previous_attempts` 리스트에 누적 보존하고 `attempt_count` 갱신.
     - 미실행 문항(`NOT_RUN`): 정상 순차 실행.
     - `resume=False` 시 기존 체크포인트를 재사용하지 않고 처음부터 새로 실행.
  3. `save_atomic_checkpoint()` 원자적 저장:
     - 동일 디렉터리 임시 파일(`.tmp.{pid}.{time}`) 작성 -> `flush` + `os.fsync` -> `os.replace`로 교체.
     - 쓰기 실패 시 임시 파일 정리 및 기존 유효 체크포인트 100% 보존.
     - 429 조기 중단 시 잔여 문항을 `NOT_RUN`으로 채운 최종 상태까지 원자적 저장 완결.
  4. `compute_metrics()` 수정:
     - 성공 생성 표본만을 대상으로 `gen_latency_p50_sec`, `gen_latency_p95_sec`, `gen_latency_mean_sec` 분리 산출.
     - `not_run_count` 지표 명시.
- **재현 및 검증 테스트**:
  - `tests/test_codex_round2_fixes.py::test_run_eval_stops_on_rate_limit_and_records_not_run` (통과)
  - `tests/test_codex_round2_fixes.py::test_checkpoint_rejects_different_dataset_model_db_and_split` (통과)
  - `tests/test_codex_round2_fixes.py::test_checkpoint_explicit_resume_retries_failed_items_and_preserves_history` (통과)
  - `tests/test_codex_round2_fixes.py::test_atomic_checkpoint_preserves_previous_file_on_write_failure` (통과)
  - `tests/test_codex_round2_fixes.py::test_checkpoint_without_resume_flag_starts_fresh` (통과)

---

## 5. 전체 2차 통합 검증 결과 요약

### 실행 명령
```bash
.venv/bin/pytest tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_api.py tests/test_retrieval_grounding.py tests/test_evaluator.py tests/test_data_status.py tests/test_rag.py -v
```

### 실행 결과
- **총 62개 테스트 전원 통과 (62 passed in 9.89s, 0 failed, 0 skipped)**
- **실제 Gemini API 호출 건수: 0건 (Mock / Fixture / In-memory 격리 검증 완수)**
- **운영 DB(`data/chroma_db`) 및 기존 검증 DB 파일 변경: 0건 (불변성 보존)**
- **추가 단위 테스트 슈트(`test_extractor.py`, `test_knowledge_collection.py`, `test_official_site.py`, `test_pipeline_isolation.py`, `test_regressions.py`, `test_scholarship_rag.py`, `test_embedder_cleanup.py`) 포함 시 총 130개 테스트 100% 통과**

---

## 6. 추가 주의 사항 준수 여부 점검

1. **202건 `title_only` 원인 확정 지양**:
   - `title_only` 202건의 원인을 "모두 HWP 문제"로 단정하지 않고, 첨부파일 형식 부재, 본문 스크립트 렌더링 누락, 비표준 첨부 등 다양한 크롤링 한계 가능성을 인정함.
2. **`text`/`mixed` 상태 표현 정정**:
   - "본문/OCR 완벽 확보"라는 표현을 지양하고, OCR 인식 오탈자 및 본문 부분 추출 가능성이 상존함을 명시함.
3. **기존 20/25문항 전체 회귀의 성격**:
   - 이번 단위 테스트의 통과는 검색 및 분기 처리의 안전성을 입증한 것이며, 전체 문항에 대한 엔드투엔드 실전 생성 품질 평가는 유료 플랜 또는 일일 쿼터 리셋 이후 정식 수행되어야 함을 확인.
4. **비기능적 제약 사항 100% 준수**:
   - Gemini API 라이브 호출 0건.
   - git commit / push 미수행.
   - 운영 DB 교체 미수행.
   - 유료 전환 미수행.

---

## 7. 잔여 문제 및 후속 인계 사항

1. **Gemini API 일일 할당량(20 RPD) 및 운영 모델 결정**:
   - 무료 티어의 20 RPD 한도로 인해 전체 20/25문항에 대한 실시간 일괄 평가는 불가능함.
   - 운영 배포 전 Gemini Pay-as-you-go(유료 종량제) 플랜 적용 여부를 최종 결정하거나, 로컬 모델(Ollama) 폴백 파이프라인과의 하이브리드 운영 전략을 수립해야 함.
2. **잔여 202건 `title_only` 공지의 심층 추출**:
   - 필요 시 향후 HWP/HWPX 전용 파서 및 고해상도 첨부 이미지 대상 추가 OCR 배치를 후속 마일스톤으로 검토 가능.
3. **병합 및 브랜치 상태**:
   - 현재 작업 트리는 Codex 작업 및 이번 수정 사항이 안전하게 반영된 상태(`codex/official-information` 브랜치)로 보존되어 있음.

