# CampusRAG Gemini 연동 및 데이터 통합 검증 인계 보고서 (2026-09-15)

## 1. 개요 및 검증 환경

본 보고서는 보강된 학내 공지, 상시 안내, FAQ, 서식 데이터를 통합한 격리 DB 환경에서 학생 질의에 필요한 핵심 검색 근거를 정확히 회수하여 Gemini API(`gemini-3.8-flash`)에 전달하고, 답변 생성 및 서비스 장애(503/429) 처리까지 완료한 구현·검증 인계 문서이다.

### 검증 환경 메타데이터
- **로컬 경로**: `/Users/jwlee/study1/aisw`
- **저장소 / 브랜치**: `https://github.com/pregeon/HSChatBot.git` (`codex/official-information`)
- **HEAD 커밋**: `30df506400056735ab3c7bde7bc51dea9b4d264b` (dirty: true, Codex 및 신규 작업 보존)
- **주 LLM 프로바이더/모델**: `gemini` / `gemini-3.8-flash`
- **임베딩 모델**: `jhgan/ko-sroberta-multitask` (기기: `mps`)
- **검증 격리 DB**: `data/integrated_eval_chroma_db` (컬렉션: `campus_knowledge`, SQLite SHA256: `10a8397b12ad215376f6aa2608ade713d1dd5718b6244cd7e57a766489192257`)
- **통합 Manifest**: `data/unified_manifest.json` (총 1,366개 고유 문서, 3,447개 청크 적재)
- **신규 검증 데이터셋**: `data/eval_official_expansion_dataset.json` (SHA256: `a53ab0df6a75cf939809332b8e45f49f732161cc646c13e60a794305ee732e8a`)

---

## 2. 작업 1: 데이터 통합 및 격리 DB 적재

### 2.1 통합 대상 원본 소스
1. `data/official_pages_enriched.json` (144건, SHA256: `c872ed2e...`, 상시 안내 HTML + PDF/HWP 첨부 보강, 우선순위 1)
2. `data/official_faq.json` (179건, SHA256: `e556025a...`, 공식 학사 FAQ 개별 질의응답 보존, 우선순위 2)
3. `data/official_forms_enriched.json` (57건, SHA256: `00f40042...`, 공식 학사서식 및 첨부 추출, 우선순위 3)
4. `data/missing_notices_refreshed.json` (99건, SHA256: `32bd0cef...`, OCR/포스터 전수 보강 공지, 우선순위 4)
5. `data/notice_archive.json` (960건, SHA256: `8ce49a9e...`, 공지사항 아카이브, 우선순위 5)

### 2.2 통합 결과 및 중복 처리 규칙
- **통합 스크립트**: `scripts/build_unified_dataset.py`
- **통합 문서 출력**: `data/unified_campus_knowledge.json` (SHA256: `c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e`)
- **고유 문서 수**: 1,366건 (신규 추가: 144 + 179 + 57 + 99 + 887, 아카이브 내 저품질/중복 제외 73건)
- **문서 유형별 분포**: `guidance` 144건, `faq` 179건, `form` 57건, `notice` 986건
- **본문 품질 상태**: 본문 확보(`text`/`mixed`/`ocr`) 1,164건 (85.2%), 잔여 `title_only` 202건 (14.8%)
- **적재 스크립트**: `scripts/ingest_unified_db.py`
- **적재 청크 수**: 총 3,447개 청크가 `data/integrated_eval_chroma_db`의 `campus_knowledge` 컬렉션에 적재 완료 (`data/integrated_eval_chroma_db/ingest_report.json`)
- **운영 DB 격리 원칙 준수**: 기존 운영 DB(`data/chroma_db`) 및 이전 검증 DB(`data/verify_demo_chroma_db`)는 일절 수정하거나 삭제하지 않음.

---

## 3. 작업 2: 검색 근거 누락 수정 및 6대 필수 사례

### 3.1 청크 누락 근본 원인 분석
1. **1차 벡터 검색 잠식 (Candidate K 부족)**: 3,447개 대형 DB에서 `candidate_k = max(k * 4, 15) = 15`로 고정되어 있어 길이가 긴 단일 문서 청크들이 상위 15개를 독점하여 정작 필요한 핵심 공지 청크가 재순위화 단계 이전에 탈락함.
2. **연도 정규식 버그**: 한글 "2024년"에서 `\b(20\d{2})\b`의 ASCII 워드 바운더리 문제로 2년 전 구 공지가 감점 없이 상위에 잔존함.
3. **상시 안내 불이익**: 상시 안내(`guidance`, `faq`, `form`)에 공지 전용 최신성 감점(-0.18)이 잘못 적용되어 FAQ나 규정이 검색에서 누락됨.
4. **주 공지 청크 제한**: `max_chunks_per_notice = 2` 제한으로 주 공지의 1~2위 청크에 밀려 정작 일정/대상 조건이 들어 있는 `_c0` 청크가 누락됨.

### 3.2 검색 엔진 및 프롬프트 개선 (`core/rag.py`, `core/prompts.py`)
- `candidate_k`를 `max(k * 15, 60)`으로 확대하여 대형 통합 DB의 1차 회수율 확보.
- 연도 정규식을 `(?:^|[^\d])(20\d{2})(?:[^\d]|$)`로 전면 교체하고 `date_str` 연도까지 반영하여 타 연도 공지에 -0.40 강력 감점 부여.
- 상시 안내 문서(`guidance`, `faq`, `form`)는 공지용 연도/최신성 감점 대상에서 제외.
- "TOPCIT 평가" 등 단축 검색어의 경우 질의 토큰이 공지 제목에 온전히 포함될 때 어휘 매칭 가산점(+0.08) 부여.
- 질의에 "신청", "마감", "일정", "대상", "자격", "서식" 등이 포함될 때 해당 문맥 청크에 가산점(+0.12) 부여 및 주 공지 청크 최대 3개 수용 (`max_chunks_per_notice = 3`).
- `core/prompts.py`:
  - 제목 오타/상충 시 본문 상세 일정 최우선 명시 및 상충 사실 안내.
  - 대상자 제외 조건('외국인 유학생 제외' 등) 누락 없이 명시.
  - 다단계 마감(온라인 접수, 보증금 납부 등) 및 업무별 마감 각각 구분 설명.

### 3.3 6대 필수 사례 검증 결과 (`data/gemini_integration_results.json`)
> **정정 공지**: `data/gemini_integration_results.json`의 9개 프로브 항목은 검색 단계에서 핵심 근거 청크를 모두 정확히 회수했으나, 실제 LLM 생성 호출 시 Free Tier 일일 할당량(20 RPD) 소진으로 429 `RESOURCE_EXHAUSTED`를 수신했습니다. 따라서 아래 판정은 **"검색 근거 검증 완료 / LLM 답변 미검증"**으로 정정되었으며, 실제 라이브 생성 PASS 증명은 `dev-md-05`(`data/gemini_smoke_results.json`) 및 `exp-02`(`data/eval_phase2_expansion_results.json`)로 확인되었습니다. 세부 정정 내역은 [`docs/gemini_integration_correction_report.md`](docs/gemini_integration_correction_report.md)를 참조하십시오.

| 검증 사례 | 검색된 핵심 근거 청크 | 검색 및 답변 상태 판정 |
| --- | --- | --- |
| **1. 취업멘토링 신청 기간** | `1a676b..._c0` (본문 상세 일정), `_c1` (대상자), `_c2` (문의처) | **검색 검증 완료** (핵심 청크 Top-3 회수 / 429로 답변 미검증) |
| **2. 편입생 학점 재인정 대상** | `e8ef6b..._c0` ("일반편입생(외국인 유학생 제외)"), `_c2`, `_c3` | **검색 검증 완료** (핵심 청크 Top-3 회수 / 429로 답변 미검증; 단 `exp-02`에서 실제 생성 PASS 실증) |
| **3. 국가장학금 2차 마감 구분** | `bdda8c..._c0`, `_c1` (서류/가구원동의 9.16), `_c2` (신청 9.9) | **검색 검증 완료** (핵심 청크 Top-3 회수 / 429로 답변 미검증) |
| **4. TOPCIT 단체접수 연장** | `731505..._c2` (구글설문 연장 ~9.9), `e05332..._c2` | **검색 검증 완료** (핵심 청크 Top-3 회수 / 429로 답변 미검증) |
| **5. 단축 질문 "TOPCIT 평가"** | `e05332..._c2`, `731505..._c2` (TOPCIT 정기평가 공지 2건) | **검색 검증 완료** (어휘 매칭으로 상위 2건 TOPCIT 공지 회수 / 429로 답변 미검증) |
| **6. 상시 안내 (FAQ/서식)** | `e792fb...` (평점계산 소수점 3째자리 절사), `222485` (자퇴원 서식) | **검색 검증 완료** (FAQ 및 서식 상위 회수 / 429로 답변 미검증) |

---

## 4. 작업 3: Gemini 오류 처리 및 회귀 테스트

### 4.1 오류 처리 구조 (`core/rag.py` - `_invoke_llm_with_error_handling`)
- **503 Service Unavailable**: 지수 백오프 1회(1.5초) 재시도 후 서버 혼잡 안내 반환 (`status: "api_error"`).
- **429 Resource Exhausted**: 무한 반복 없이 즉시 1회 실패 처리 및 한도 초과 안내 반환 (`status: "api_error"`).
- **401/403 Authentication/Permission**: 재시도 없이 즉시 인증/설정 오류 안내 반환 (`status: "api_error"`).
- **은폐 금지**: API 오류를 "관련 공지 없음"이나 정상 유보(Abstain)로 은폐하지 않고, 메타데이터(`status`, `error`, `latency_seconds`, `model`, `provider`, `api_called`)를 투명하게 기록.

### 4.2 단위 및 회귀 테스트 결과
- `tests/test_retrieval_grounding.py`:
  - `test_query_entities_extraction`: 연도/학기 엔티티 추출 검증
  - `test_short_query_lexical_preservation`: 단축어 어휘 보존 검증
  - `test_gemini_503_backoff_and_user_message`: 503 재시도 및 오류 안내 검증
  - `test_gemini_429_quota_exhausted_immediate_stop`: 429 즉시 중단 검증
  - `test_gemini_auth_error_immediate_stop`: 401/403 즉시 중단 검증
- `tests/test_evaluator.py`:
  - 날짜 전도(swapped), 날짜 동일 판정, 미기재 정보 유보, 무관 질문 유보, provider 보존, `test_api_error_handling` 등 11개 항목
- **테스트 실행 명령**:
  ```bash
  .venv/bin/pytest tests/test_evaluator.py tests/test_retrieval_grounding.py -v
  ```
- **결과**: **16 passed in 6.78s (100% 통과, 0 failed, 0 skipped)**

---

## 5. 실전 평가 및 검증 결과

### 5.1 신규 Phase 2 검증셋 (`data/eval_official_expansion_dataset.json`)
- **파일 SHA256**: `a53ab0df6a75cf939809332b8e45f49f732161cc646c13e60a794305ee732e8a`
- **표본 수**: 10건 (상시안내, 단축질문, 제외조건, 다단계마감, 무관유보 포함)
- **평가 실행 결과 (`data/eval_phase2_expansion_results.json`)**:
  - **검색 회수율 (Hit@1 / Hit@3)**: **88.9% (8/9)** (사실 질의 9건 중 8건 Top-1/Top-3 일치)
  - **Gemini 답변 성공**: `exp-02` (편입생 학점 재인정 대상자) -> **PASS (score 1.0)**
    - 실제 생성 답변: *"전적대학 학점 재(추가)인정 신청 대상자는 일반편입생 중 전적대학 학점 추가인정 또는 재인정 신청 대상자이며, 외국인 유학생은 대상에서 제외됩니다."*
  - **API 상태**: Free Tier 20회/일 요청 한도 도달에 따른 429 RESOURCE_EXHAUSTED 발생 -> 9건 모두 정상적으로 **API_ERROR**로 투명하게 분류됨 (FAIL이나 임의 PASS 처리하지 않음).
  - **지연 시간**: Median(p50) = 0.37초, p95 = 2.25초, Mean = 0.71초

---

## 6. HTTP 백엔드 및 UI 연동 검증

FastAPI 백엔드를 격리 DB 경로로 기동하여 RESTful 엔드포인트 연동을 검증함 (`scripts/verify_http_server.py`, `data/http_backend_verification.json`).

1. **GET `/health`**:
   - `status: "ok"`, `llm_provider: "gemini"`, `doc_count: 3447` (격리 DB 적재 청크 수와 100% 일치)
2. **POST `/api/retrieve`**:
   - 질의: *"2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간"*
   - 결과: Top-3 청크 정상 회수 (취업멘토링 공지 3건)
3. **POST `/api/query` (무관 질문)**:
   - 질의: *"파이썬으로 이진 탐색 트리 구현하는 코드 짜줘"*
   - 결과: HTTP 200 정상 반환, 유보/오류 안내문 전달
4. **POST `/api/query` (실제 질문 및 한도 초과 상황)**:
   - 질의: *"2026학년도 2학기 전공연계 협업형 진로·취업멘토링 참가자 신청 기간이 언제야?"*
   - 결과: HTTP 200 정상 반환, 500 서버 크래시 없이 AI 서비스 한도 초과 안내문 및 출처 카드 제공
5. **프로세스 정리**: 검증 완료 즉시 테스트 uvicorn 프로세스 정상 종료 완료 (좀비 프로세스 잔존 없음).

---

## 7. 미해결 과제 및 Codex 판단 필요 사항

1. **Gemini API 할당량(Quota) 및 유료 플랜 전환 여부**:
   - 현재 설정된 API 키는 Free Tier(분당 15 RPM, 일당 20 RPD 제한) 상태로, 일일 한도(20회) 소진 시 요청 간격(슬립) 증가로는 해결할 수 없습니다.
   - 전체 평가셋(20~25문항) 일괄 실전 평가는 유료 플랜(Pay-as-you-go) 전환 또는 일일 쿼터 리셋 후 수행되어야 하며, Codex/관리자의 결정이 필요합니다.
2. **잔여 `title_only` 공지(202건)의 처리 방안**:
   - 1,366건 중 1,164건은 본문 및 OCR 텍스트를 확보하였으나(부분 추출 및 OCR 오류 가능성 상존), 202건은 첨부파일 미추출, 동적 스크립트 본문 등 다양한 원인으로 `title_only` 상태입니다.
   - 현재 파이프라인은 `title_only` 공지 질문 시 원문 링크 확인 유도 가드레일이 정상 작동하므로 안전하나, 추가적인 HWP/HWPX 파서 도입 등은 후속 마일스톤으로 검토 가능합니다.
