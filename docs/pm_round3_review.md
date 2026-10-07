# CampusMate R3 & R5 PM 검수 보고서 — 전체 개선 마일스톤 완수 승인 (Approved)

- **검수일**: 2026-09-24
- **검수자**: PM (Antigravity Orchestrator)
- **대상 마일스톤**: CampusMate R3 (최소 캘린더 통합 UI & Zero-Auto-Save 확인 흐름) 및 R5 (마감 알림 배너, 정적 서빙 및 E2E 테스트)

---

## 1. 종합 판정: 전원 승인 (Full Milestone Approved)

CampusMate 프로젝트의 핵심 과제인 **인증(R1-A) → 개인 일정 CRUD(R1-B) → 일정 후보 추출(R2) → 최소 캘린더 통합 UI 및 Zero-Auto-Save 확인 모달(R3) → 마감 알림 배너 및 웹 정적 서빙 E2E(R5)**에 이르는 전체 개선 마일스톤이 성공적으로 구현 및 검수 완료되었다.

독립적인 PM 검수 결과:
1. **프론트엔드 빌드**: `frontend-web` TypeScript + Vite 프로덕션 빌드 **정상 통과 (255ms)** 및 `frontend-web/dist` 정적 에셋 생성 완료.
2. **백엔드 정적 서빙**: FastAPI 루트(`GET /`)에서 `frontend-web/dist/index.html`이 200 OK로 원활하게 서빙됨을 확인.
3. **E2E 전체 라이프사이클**: 회원가입/로그인 → 공지 일정 추출 → Zero-Auto-Save 확인 검증 → 사용자 확인 모달을 통한 등록(`confirmed: true`) → 캘린더 조회 → 완료 토글(`PATCH`) → 삭제(`DELETE`) 전수 통과.
4. **전체 회귀 테스트**: **145개 전원 통과 (`145 passed, 1 warning in 36.09s`)**.
5. **RAG 대표 10사례 근거 무결성**: **`10/10 ALL PASS`** 및 지식베이스 0바이트 변동 무결성 확인.

---

## 2. 세부 검수 항목 및 증거

### 2.1 [PASS] R3: 캘린더 통합 UI & Zero-Auto-Save 확인 흐름
- **챗봇-캘린더 연동**:
  - 챗봇 응답 말풍선 및 공지 출처 카드(SourceCard)에 `[📅 일정 추출]` 버튼이 배치되어, 클릭 시 `POST /api/v1/schedules/extract`를 호출한다.
  - 추출된 후보는 즉시 DB에 들어가지 않고, **`ScheduleConfirmationModal`**에 표시되어 사용자가 제목, 날짜/시간, 우선순위를 직접 검토하고 수정할 수 있다.
  - 사용자가 **[확인 및 캘린더 저장]** 버튼을 클릭해야만 `POST /api/v1/schedules` (`confirmed: true`)로 확정 저장된다.
  - 중복 저장 방지를 위해 요청 중 `isSubmitting` 로딩 락이 걸린다.
- **캘린더 뷰 (CalendarView)**:
  - 상단 탭으로 `[💬 챗봇 대화]`와 `[📅 내 캘린더]`를 실시간 전환할 수 있다.
  - 월간 달력 그리드에 일정이 있는 날짜는 마커 점이 표시되며, 날짜 클릭 시 해당 일자의 일정이 필터링된다.
  - 일정 완료 체크박스 토글(`PATCH /api/v1/schedules/{id}`, `is_completed: !current`), 삭제(`DELETE /api/v1/schedules/{id}`), 수동 `[➕ 새 일정]` 모달을 완벽히 지원한다.

### 2.2 [PASS] R5: 마감 알림 배너 및 브라우저 Notification 연동
- 오늘 마감(D-Day) 또는 3일 이내 마감인 미완료 일정이 감지될 경우, 상단에 **`🚨 마감 임박 일정 (N건)`** 경고 배너가 자동으로 활성화된다.
- Web Notification API 권한 요청(`Notification.requestPermission()`) 버튼이 탑재되어, 사용자가 브라우저 알림을 활성화할 수 있다.

### 2.3 [PASS] 백엔드 정적 서빙 및 보안 E2E 검증 (`tests/test_ui_and_e2e_flow.py`)
- `test_frontend_static_serving_root`: `GET /` 호출 시 `frontend-web/dist/index.html`이 200 OK로 반환되며, React 번들이 정상 로드됨을 확인.
- `test_e2e_extract_confirm_crud_flow`: 공지 텍스트 추출 시점에는 DB 레코드 수가 0건(Zero-Auto-Save 검증)이며, 확인 모달 제출 시점에만 DB에 레코드가 1건 생성되고, 이후 수정 및 삭제가 완벽히 동작함을 확인.
- `test_selective_confirmation_zero_auto_save`: 다단계 일정(TOPCIT 설문 마감 vs 보증금 납부 마감 등) 추출 시 사용자가 선택한 1개 후보만 저장되고 미선택 후보는 저장되지 않는 엄격한 선택적 확인 계약 증명.

---

## 3. 테스트 실행 결과 요약

```text
============================= test session starts ==============================
collected 145 items

tests/test_ui_and_e2e_flow.py::test_frontend_static_serving_root PASSED
tests/test_ui_and_e2e_flow.py::test_e2e_extract_confirm_crud_flow PASSED
tests/test_ui_and_e2e_flow.py::test_selective_confirmation_zero_auto_save PASSED
tests/test_schedule_extraction.py (28 tests) PASSED
tests/test_schedules.py (35 tests) PASSED
tests/test_auth_persistence.py (10 tests) PASSED
tests/test_codex_round2_fixes.py (14 tests) PASSED
tests/test_codex_fixes.py (16 tests) PASSED
tests/test_retrieval_grounding.py (5 tests) PASSED
tests/test_date_parsing.py (34 tests) PASSED

======================== 145 passed, 1 warning in 36.09s =========================
```

- **RAG 원문 대조 (`scripts/verify_rag_eval_evidence.py`)**: `10/10 ALL PASS`
- **저장소 파일 무결성**: `data/` 하위 데이터베이스 및 원본 지식베이스 파일 0바이트 변경 없음.

---

## 4. 최종 결론

CampusMate 서비스는 공지 검색/답변(CampusRAG)과 더불어, 사용자 계정 영속성, 개인 캘린더 CRUD, 지능형 일정 후보 추출, 사용자 확인 강제(Zero-Auto-Save) UI, 마감 임박 알림 배너, 그리고 모바일/웹 반응형 React 프론트엔드가 하나로 통합된 완전한 서비스 상태를 갖추었다.
