# 챗봇 전용 제품 분리 및 PRD 개정 결과

2026-09-27 사용자 요청에 따라 개인 일정 관리 기능을 활성 제품에서 제외했다. 제품명은 CampusMate를 유지하며 로그인 없는 학내 공지 챗봇으로 정리했다.

## 변경

- React 메인 화면을 배포 기준 챗봇 흐름으로 분리하고 CampusMate 이름으로 통일했다. 일정 후보 추출·확인·편집 모달, 캘린더, 인증 모달, 마감 알림을 기본 번들에서 제거했다.
- FastAPI에서 인증/일정 라우터, 계정 DB import와 startup migration, 인증 전용 오류 처리기를 제거했다. /health, /api/query, /api/retrieve는 유지했다.
- config에서 계정 DB/세션 설정을 분리했다. RAG prewarm 설정과 공지 본문 content 전달, 날짜 정규화 수정은 유지했다.
- Docker에서 개인 DB 볼륨/환경변수/SQLite 백업 스크립트 복사를 제거했다. 인증 bcrypt 의존성을 requirements와 lock에서 제거했다. 수정 후 Docker 이미지는 새로 빌드해야 한다.
- 기존 일정 구현 원본 및 검사·fixtures·설정 34개 파일을 archived_features/personal_schedule_20260927에 SHA-256 manifest와 함께 보존했다. 기본 pytest 탐색과 Docker 컨텍스트에서 제외했다. 보관본은 현재 공유 모듈과 함께 복구해야 하는 소스 묶음이며 독립 앱이 아니다.
- README, 활성 범위, 컨테이너 가이드를 업데이트했다. 이전 일정 계획 및 API 가이드에는 역사 기록 안내를 추가했다.
- 첨부 PRD의 문제 정의·대상·페르소나·MVP·사용 흐름·기술·성공 기준·요약을 챗봇으로 개정했다. 목표와 완료 사실을 구분하고 최신판 외부 배포 미반영 상태를 명시했다. 팀원/역할은 원본이 비어 있어 별도 확정으로 표시했다.

## 검증

- npm run build --prefix frontend-web: TypeScript/Vite 성공.
- 선별 5개 파일(test_chatbot_only, test_codex_round2_fixes, test_codex_fixes, test_retrieval_grounding, test_date_parsing): 65 passed, 1 warning, 8.65초.
- 첫 검사에서 날짜 파싱 파일에 남아 있던 일정 fixture 검사가 실패했다. 해당 원본 파일도 보관하고 일정 전용 테스트만 활성 파일에서 분리한 후 재검사했다. 실패를 무시하거나 skip 처리한 것은 아니다.
- 새 프로세스에서 sqlite3.connect를 금지한 상태로 서버 lifespan과 /health가 정상 동작한다. 공개 API 목록에는 챗봇 3개 경로만 있다.
- 익명 /api/query 호출이 답변·출처를 반환한다(mock RAG).
- 실제 Chromium 모바일 390×844: 로그인/캘린더 UI 없음, 질문 입력→답변→원문 링크 표시, 인증/일정 API 요청 없음. 답변은 mock이므로 실제 LLM 품질 검증이 아니다.
- RAG 로컬 원문 대조 10/10 통과.
- 보관 파일 34개의 SHA-256 검증 통과. git diff --check 통과.
- DOCX 한글 글꼴을 적용해 렌더링 및 페이지 육안 검수. 원본 Downloads 파일은 보존했다.

## 범위

data/와 기존 개인 DB 파일·Docker 볼륨을 삭제하지 않았다. 외부 LLM 호출, 모델 다운로드, 최신판 Docker 이미지 재빌드, Cloudtype/AWS 재배포, commit/push는 실행하지 않았다. 기존 159개 테스트·컨테이너 검증 수치를 현재 챗봇 전용판의 결과로 사용하지 않는다.
