# CampusMate 마일스톤 추가 결함(R1 ~ R4) 복구 및 2차 검증 보고서

- **작성일자**: 2026-09-24
- **작성자**: Gemini Worker Subagent (Full-Stack Engineering)
- **수신자**: PM Subagent 및 검수팀
- **대상 검수 보고서**: `docs/codex_milestone_repair_review_20260924.md` (R1 ~ R4)
- **수정 지침 문서**: `docs/gemini_milestone_repair2_prompt.md`

---

## 1. 수정 개요 및 해결 내용 (R1 ~ R4)

Codex의 마일스톤 재검수에서 지적된 4대 핵심 결함(R1~R4)을 백엔드 비즈니스 로직, 프론트엔드 React 상태 및 날짜 파싱 계층, 데이터 스키마, 그리고 실제 Playwright 브라우저 E2E 테스트에 걸쳐 전면 수복하였습니다.

### R1 (ScheduleEditModal 시각 왜곡 및 정밀도 유실 복구)
1. **Asia/Seoul 기준 날짜·시각 파싱 함수 도입**:
   - `frontend-web/src/App.tsx`에 `parseUtcToSeoulParts(isoStr)` 및 `formatSeoulTime(isoStr)` 구현.
   - `Intl.DateTimeFormat` (`timeZone: "Asia/Seoul"`, `hourCycle: "h23"`)을 사용하여 서버가 반환한 UTC 일시 문자열을 로컬 타임존 환경과 무관하게 항상 일관된 서울 시간(KST)으로 변환.
   - 기존의 `slice(0, 5)`로 인한 9시간 역방향 시각 밀림 현상 완전 차단.
2. **미수정 필드 PATCH 제외 및 원본 정밀도 보존**:
   - `ScheduleEditModal`에 `initialKind`, `initialStartDate`, `initialEndDate`, `initialStartTime`, `initialEndTime`을 추적하는 상태 도입.
   - 사용자가 제목이나 중요도만 수정한 경우(`isDateOrKindModified === false`), 날짜 및 시각 필드(`start_date`, `end_date`, `start_datetime`, `end_datetime`)를 PATCH 요청 페이로드에서 제외.
   - 백엔드 `ScheduleService.patch_schedule`은 전송되지 않은 필드를 기존 DB 레코드 값 그대로 보존하므로, 마이크로초(`.123456`) 정밀도와 원본 타임스탬프가 100% 손실 없이 보존됨.
3. **서울 자정 경계(00:00 KST) 안정적 처리**:
   - 서울 자정 일시를 수정한 경우 UTC `15:00:00Z`로 정상 정규화 저장.
   - 재조회 시에도 날짜가 전날로 밀리지 않고 `2026-11-20 00:00`으로 일관되게 렌더링됨을 검증.
4. **모달 마운트 레이스 컨디션 제거**:
   - `ScheduleEditModal`의 `useState`를 `useState(() => ...)` 초기화 함수 형태로 변경하여 컴포넌트 마운트 즉시 `schedule`의 초기값을 동기화. React의 비동기 `useEffect` 지연으로 인한 폼 덮어쓰기 레이스 컨디션을 원천 차단.

### R2 (추출기 모든 분기 공통 달력·시각 검증 및 반례 해결)
1. **공통 달력 유효성 검증 함수 전면 적용**:
   - `backend/schedules/extraction.py`의 모든 반환 경로 및 특수 분기에 `_check_calendar_validity(year, month, day, hour, minute)` 일괄 적용.
2. **보고서 R2의 5대 반례 및 특수 규칙 완벽 수복**:
   - **반례 1 (동적 제목 추출)**: "오늘 18시까지 장학금 신청서를 제출하세요" 등의 입력에서 하드코딩 "지도교수 면담 신청서 제출"을 제거하고 문맥 정규식 기반으로 "장학금 신청서 제출" 동적 추출.
   - **반례 2 (날짜 없는 자정)**: "자정까지 접수"와 같이 일자 정보가 누락된 경우, 임의 날짜(`2026-10-09` 등)를 위조하지 않고 `extracted_date=None, is_ambiguous=True, unconfirmed_fields=["date", "time", "exact_boundary"]`로 유보.
   - **반례 3 (명시 연도 보존)**: "1차: 2027.01.10 10:00, 2차: 2027.01.12 14:00"에서 명시된 연도 `2027`을 온전히 보존하여 후보 생성.
   - **반례 4 (1시간 기본 계산의 분 보존 및 자정 넘김)**: 2차 시작 시각에서 `timedelta(hours=1)`을 적용하여 분 단위 누락(`13:30 -> 14:30`) 및 자정 넘김(`23:30 -> 익일 00:30`, `24:00` 방지) 완벽 해결.
   - **반례 5 (다단계 순차 마감 유효성 검증)**: "1차 접수는 2월 30일 25:90까지이며 2차 접수는 3월 5일 18:00까지입니다"와 같은 입력에서 유효하지 않은 1차 후보는 배제하고 유효한 2차 후보만 정상 반환.
3. **독립 반례 테스트 슈트 확충**:
   - `tests/test_schedule_extraction.py`에 `test_codex_round2_r2_five_counterexamples`를 신설하여 5대 반례 전수 검증 통과 (총 30개 테스트 100% 통과).

### R3 (출처 카드 내부 문서 실제 본문 전달 및 사용자 입력 요청)
1. **백엔드 스키마 및 RAG 파이프라인 계약 확장**:
   - `backend/schemas.py`: `SourceCard` 모델에 `content: str | None = Field(default=None)` 필드 추가.
   - `backend/main.py`: `/api/retrieve` 엔드포인트에서 검색된 문서 청크 본문(`doc.page_content[:2000]`)을 `SourceCard.content`로 전달.
   - `core/rag.py`: `query()` 응답 내 `deduped_sources`에 `content: doc.page_content[:2000]` 포함.
2. **프론트엔드 출처 카드 추출 로직 개선**:
   - `frontend-web/src/App.tsx`: `SourceCard`의 [📅 일정 추출] 클릭 시 문서 본문(`src.content`)이 존재하면 해당 본문을 기반으로 추출 실행.
   - 본문이 미확보된 경우(제목/게시일만 있는 경우), 제목/게시일만으로 임의 일정을 생성하지 않고 `window.prompt`를 통해 사용자에게 실제 공지 본문 텍스트 입력을 직접 요청.

### R4 (실제 브라우저 E2E 테스트 강화 및 실행 구분 명확화)
1. **`tests/test_browser_e2e.py` 검증 시나리오 대폭 강화**:
   - **취소/미선택 시 DB 불변성**: 모달이 열린 상태 및 취소 버튼 클릭 시 SQLite DB가 0건으로 유지됨을 검증.
   - **후보 2 정확 값 대조**: 2개 후보 중 2번째 후보(보증금 납부) 선택 시, DB에 `TOPCIT 보증금 납부 마감`, `TIME_CONFIRMED_DEADLINE`, `end_date: 2026-11-22`, `end_datetime: 2026-11-22T03:00:00Z`로 정확히 1건 저장되고 후보 1은 미저장됨을 엄격 검증.
   - **다일 기간 일정 중간 날짜 필터링**: 2026년 10월로 이동하여 중간 날짜인 22일(목) 클릭 시 `2026 2학기 중간고사 집중기간`(10-20 ~ 10-24)이 노출되고, 범위 밖 날짜인 25일(일) 클릭 시 목록에서 사라짐(count == 0), '전체 보기'로 복귀함을 검증.
   - **제목만 수정 시 시각 불변 및 마이크로초 보존**: `.123456` 마이크로초를 가진 레코드를 주입하고 UI에서 제목만 수정 시 DB의 `start_datetime`과 `end_datetime`이 원본과 100% 동일함을 확인.
   - **서울 자정 경계(00:00) 수정**: 00:00 KST / 01:00 KST 수정 시 DB에 UTC `15:00:00Z`로 저장되고, 재조회 모달에서 `2026-11-20 00:00`으로 정확히 복원됨을 검증.
   - **51건 이상 대량 페이징**: 50건을 일괄 주입(총 53건) 후 `offset/limit` 페이징 루프를 통해 50번째 항목까지 화면에 완벽 렌더링됨을 검증.
   - **로그아웃 후 토큰 무효화**: 로그아웃 후 브라우저 localStorage에서 토큰이 삭제되고, 이전 토큰으로 `/api/v1/auth/me` 호출 시 HTTP `401 Unauthorized`가 반환됨을 검증.
2. **테스트 내 Mock RAG 사용 경계 명시**:
   - `test_browser_e2e.py` 내의 `/api/query` 라우트 모킹 주석을 보강하여, 해당 테스트가 백엔드 LLM 생성 자체가 아닌 프론트엔드 UI ↔ API 간의 브라우저 E2E 상호작용을 검증함을 명확히 표기.

---

## 2. 실제 검증 실행 결과

### 2.1 실제 브라우저 E2E 테스트 (Playwright Chromium)
- **명령어**: `.venv/bin/pytest -v tests/test_browser_e2e.py`
- **결과**: **`1 passed in 10.43s` (100% 통과)**
```
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0 -- /Users/jwlee/study1/aisw/.venv/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/jwlee/study1/aisw
plugins: langsmith-0.12.4, anyio-4.15.1
collecting ... collecting 1 item

tests/test_browser_e2e.py::test_browser_e2e_full_lifecycle PASSED        [100%]

============================== 1 passed in 10.43s ==============================
```

### 2.2 핵심 9개 파일 회귀 테스트 슈트
저장소 전체 25개 테스트 파일 중 본 마일스톤 및 인증/일정/수복 핵심 영역에 해당하는 9개 파일(148개 테스트)을 선별 실행하였습니다.
- **명령어**:
  ```bash
  .venv/bin/pytest tests/test_browser_e2e.py tests/test_ui_and_e2e_flow.py tests/test_schedule_extraction.py tests/test_schedules.py tests/test_auth_persistence.py tests/test_codex_round2_fixes.py tests/test_codex_fixes.py tests/test_retrieval_grounding.py tests/test_date_parsing.py -v
  ```
- **결과**: **`148 passed, 1 warning in 43.50s` (100% 통과)**
  - `tests/test_browser_e2e.py`: 1 passed
  - `tests/test_ui_and_e2e_flow.py`: 3 passed
  - `tests/test_schedule_extraction.py`: 30 passed (R2 반례 검증 1건 포함)
  - `tests/test_schedules.py`: 35 passed
  - `tests/test_auth_persistence.py`: 15 passed
  - `tests/test_codex_round2_fixes.py`: 13 passed
  - `tests/test_codex_fixes.py`: 10 passed
  - `tests/test_retrieval_grounding.py`: 7 passed
  - `tests/test_date_parsing.py`: 34 passed

### 2.3 프론트엔드 프로덕션 빌드 검증
- **명령어**: `npm run build` (in `frontend-web/`)
- **결과**: **성공 (254ms, 0 errors)**
```
> campusrag-mobile-web@1.0.0 build
> tsc && vite build

vite v6.4.3 building for production...
✓ 27 modules transformed.
dist/index.html                   1.00 kB │ gzip:  0.58 kB
dist/assets/index-BamWOvKk.css   25.69 kB │ gzip:  5.74 kB
dist/assets/index-CmTaZjs8.js   193.95 kB │ gzip: 58.20 kB
✓ built in 254ms
```

### 2.4 RAG 대표 10사례 원문 근거 전수 대조
- **명령어**: `.venv/bin/python scripts/verify_rag_eval_evidence.py`
- **결과**: **`[최종 결과] 대표 10사례 로컬 데이터 전수 대조: ALL PASS (10/10)`**
  - Expected SHA-256: `c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e`
  - Actual SHA-256: `c6969ec41faa332b660186cf5407f07dc9621fcbccd2158e124e9b62c225359e` 일치.

---

## 3. `data/` 디렉터리 데이터 무결성 검증 (0-byte Mutation)

수정 및 검증 전후 `data/` 디렉터리의 940개 파일에 대해 파일 내용 SHA-256 해시를 대조하였습니다.
- **검증 스크립트**:
  ```python
  import hashlib, os
  def hash_dir(d):
      h = hashlib.sha256()
      count = 0
      for root, _, files in sorted(os.walk(d)):
          for f in sorted(files):
              p = os.path.join(root, f)
              with open(p, "rb") as fp:
                  h.update(fp.read())
              count += 1
      return count, h.hexdigest()
  c, d_hash = hash_dir("data")
  assert c == 940
  assert d_hash == "7ce71284b38e1fb7c61539d1d96d4fb7ffb186d6f1c90d03cdcfca5d0bf4eba8"
  ```
- **실행 결과**:
  ```
  data files: 940, sha256: 7ce71284b38e1fb7c61539d1d96d4fb7ffb186d6f1c90d03cdcfca5d0bf4eba8
  [PASS] EXACT SHA-256 HASH MATCH!
  ```
- **Git 상태**: `git status` 결과 `data/` 디렉터리 내에 변경된 파일이나 untracked 파일이 일절 없음(0바이트 변동).

---

## 4. 해결 항목 및 미해결 / 제약 사항

### 4.1 완전히 해결된 항목 (Resolved)
1. **R1**: `ScheduleEditModal`의 UTC 9시간 밀림 방지, 제목/우선순위만 수정 시 시간 필드 PATCH 제외를 통한 마이크로초 정밀도 보존, 서울 자정(00:00) 경계 정상 수정 및 렌더링.
2. **R2**: `extraction.py` 전 분기 `_check_calendar_validity` 적용, 5대 반례(동적 제목, 자정 유보, 명시 연도 보존, timedelta(hours=1) 분 보존 및 자정 넘김, 다단계 무효 필터링) 100% 통과.
3. **R3**: `SourceCard.content` 필드 추가 및 `/api/retrieve`, `query()` 파이프라인 본문 연동, 미확보 시 사용자 본문 입력 요청(제목/게시일 기반 위조 방지).
4. **R4**: Playwright 브라우저 E2E에서 취소 시 미저장, 후보 2 단독 저장 및 값 대조, 다일 기간 중간 날짜 필터링, 제목 수정 시 시각 불변, 서울 자정 경계, 51건 이상 페이징, 로그아웃 후 토큰 401 차단 검증.

### 4.2 미해결 및 제약 사항 (Scope Boundaries & Proposed State)
1. **테스트 슈트 실행 범위의 한정 (명시적 고지)**:
   - 본 보고서의 회귀 검증(148 passed)은 저장소 전체 25개 테스트 파일 중 본 마일스톤 및 인증/일정/수복 핵심 영역에 해당하는 **9개 파일의 선별 회귀 묶음**입니다. 저장소 내 25개 전체 테스트 파일(`pytest tests/test_*.py`)을 실행한 결과가 아닙니다.
2. **브라우저 E2E 내 Mock RAG 범위**:
   - `test_browser_e2e.py`는 브라우저 UI ↔ API 간의 데이터 연동과 상태 변경(Playwright)을 안정적으로 검증하기 위해 `/api/query` 엔드포인트의 응답을 모킹하여 사용합니다. 백엔드 RAG 엔진 자체의 임베딩 검색 및 문서 일치 무결성은 `scripts/verify_rag_eval_evidence.py` 및 전용 RAG 단위 테스트로 분리 검증됩니다.
3. **운영 알림(F7) 범위 변경 및 연기 제안 (Proposed State)**:
   - 웹 브라우저를 종료한 상태에서의 OS 백그라운드 푸시 알림(APNs/FCM) 및 상시 백그라운드 배치 데몬은 인앱 웹 브라우저 단계의 스코프를 넘어서는 아키텍처이므로, **Phase 3 (모바일 앱 패키징 및 운영 환경 배포)** 단계로 이관하여 구현할 것을 제안(Proposed) 상태로 유지합니다. 현재 구현은 브라우저 탭 내 D-Day 배너 및 Notification API 권한 요청 흐름으로 한정됩니다.
