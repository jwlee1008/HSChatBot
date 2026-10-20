# CampusRAG 저장소 구성과 형상관리

기준일은 2026년 10월 18일입니다. 이 문서는 현재 `main`의 파일 역할과 변경 관리 원칙을 설명합니다. 코드 재배치나 운영 데이터 교체를 수행한 기록은 아닙니다.

## 기준 저장소와 브랜치

| 항목 | 기준 |
|---|---|
| 문서·산출물 반영 저장소 | [jwlee1008/HSChatBot](https://github.com/jwlee1008/HSChatBot) |
| 기준 브랜치 | `main` |
| 원본 협업 저장소 | [pregeon/HSChatBot](https://github.com/pregeon/HSChatBot) |
| 이번 정리의 코드 기준 | `8349320` |
| 프로젝트와 팀 | CampusRAG / 저학년의 반란 |

현재 로컬 checkout은 `myrepo`가 `jwlee1008/HSChatBot`, `origin`이 `pregeon/HSChatBot`을 가리키며 `codex/official-information` 브랜치가 `origin/codex/official-information`을 추적합니다. 새 clone의 remote 이름은 이와 다를 수 있습니다. 따라서 원격 이름만으로 대상 저장소를 판단하지 않고 URL과 브랜치를 함께 확인합니다.

```bash
git remote -v
git branch -vv
git fetch myrepo main
```

이번 문서·보고서 반영은 `jwlee1008/HSChatBot`의 `main`을 대상으로 합니다. 원본 저장소의 작업 브랜치에만 push한 변경이 자동으로 이 저장소의 `main`에 반영되는 것은 아닙니다.

## 폴더별 역할

| 경로 | 관리하는 내용 | 현재 사용 범위 |
|---|---|---|
| `backend/` | FastAPI 라우트와 Pydantic 스키마 | `/health`, `/api/query`, `/api/retrieve` |
| `core/` | 검색·재정렬·답변·프롬프트·청킹·임베딩 | 익명 챗봇의 RAG 처리 |
| `core/extractor/` | 안전한 다운로드, OCR, PDF·HWP·HWPX 파서 | 공지 본문·첨부 보강 |
| `crawler/` | 공식 안내·FAQ·게시판 수집과 정책 | 공개 자료 수집 |
| `frontend-web/` | React·TypeScript·Vite 웹 | 현재 사용자 화면 |
| `frontend-web/dist/` | 정적 웹 빌드 | FastAPI가 화면 서빙 시 사용 |
| `frontend/` | Streamlit 참고 UI | 기본 사용자 화면과 별도인 이전 경로 |
| `scripts/` | 자료 통합, 새 색인 구축, 평가와 진단 | 운영·개발 CLI |
| `tests/` | API·검색·청킹·첨부 처리 등의 검사 | 테스트별 unit/mock/live 범위를 확인 |
| `data/` | 공개 원본·보강 JSON, manifest, 기본 seed와 보고서 | 파일마다 수집·생성 시점 구분 |
| `docs/` | 문서 목록, PRD·실행 가이드와 과거 검토 기록 | 기준일과 제품 범위에 따라 선택 |
| `outputs/` | 제출·검토용 최종 문서 파일 | 날짜별 묶음과 버전으로 관리 |
| `.github/workflows/` | `ci.yml`, `crawl.yml`, `official-site.yml` | 회귀 실행·공지 수집·상시 안내 갱신 설정 |
| `archived_features/` | 인증·개인 일정 관련 소스 | 기본 앱 import·Docker·pytest 기본 범위에서 제외 |
| `archived_artifacts/` | 제품 범위 변경 전 기획·발표 기록 | 과거 자료 보존 |

## 파일과 산출물의 구분

소스와 실행 설정은 코드 리뷰와 회귀 검증의 대상입니다. 공개 자료 JSON과 manifest는 수집 범위·시각·입력 해시를 확인하고, 생성한 색인은 원본과 일치하는지 따로 검증합니다. 제출 문서는 해당 자료·코드 기준을 적어 코드 완료나 운영 적용과 혼동하지 않게 합니다.

현재 설계 묶음은 [outputs/campusrag_design_20261018](../outputs/campusrag_design_20261018/README.md)에 둡니다. TRD·프로그램 목록·StoryBoard의 요구사항과 화면 ID를 유지하고, 형상관리표에는 기준 저장소와 README·구성 문서의 상태를 기록합니다. 최신 파일은 묶음 README에서 안내합니다.

구형 루트 문서와 과거 기능은 이번 작업에서 이동하거나 삭제하지 않습니다. [문서 목록](README.md)에서 현재 제출 자료와 역사 기록을 구분합니다.

## 변경 반영 절차

1. 대상 URL·브랜치와 작업 디렉터리의 수정사항을 확인합니다.
2. 필요하면 `codex/` 접두사의 작업 브랜치와 별도 checkout에서 변경을 만듭니다.
3. 코드 변경은 관련 회귀를, 문서 변경은 링크·명령·경로를, Office 파일은 내용과 표시를 확인합니다.
4. 의도한 파일만 stage하고 `git diff --cached --stat`과 실제 변경을 검토합니다.
5. 검토한 커밋을 명시한 원격·브랜치에 반영하고 원격 SHA를 확인합니다. 원격이 앞서갔으면 최신 변경을 통합하며 강제 push로 덮어쓰지 않습니다.

실명별 담당자와 승인 체계, 제출 기한은 팀에서 별도로 확정합니다. 존재하지 않는 승인자나 완료 실적을 문서에 추가하지 않습니다.

## 비밀정보와 실행 데이터

`.env`, API 키, 가상환경, `node_modules`, 다운로드·모델 캐시와 개인 DB는 소스·제출 문서에 포함하지 않습니다. `.gitignore`는 새 비추적 파일에 대한 규칙이므로 이미 추적되는 파일이 자동으로 제외되지는 않습니다.

이 저장소에는 기존 `data/integrated_eval_chroma_db/` seed가 추적되어 있습니다. 10월 9일 확장된 약 258MiB의 로컬 SQLite와 HNSW 파일은 이번 문서·보고서 커밋에 포함하지 않습니다. 해당 DB와 런타임 추가 코드는 별도 검증·전달·적용 작업으로 관리합니다.

`myrepo/main`에서 갱신된 공식 원본 JSON, 로컬 통합 JSON, 현재 Chroma 색인과 운영 서버의 데이터는 서로 다른 버전일 수 있습니다. 원본 갱신, 색인 생성, 운영 반영을 각각 기록합니다. 실행 중인 DB는 파일 단위로 덮어쓰지 않고 같은 후보의 JSON·manifest·DB를 적용합니다.

## 이번 최신화 범위

- README의 실제 저장소 주소, 설치·실행·API·환경변수와 현재 제품 범위를 정리했습니다.
- 현재 웹 `frontend-web/`과 이전 Streamlit 경로, 보관된 개인 일정 기능을 구분했습니다.
- 문서 목록과 설계 산출물 묶음의 진입점을 추가했습니다.
- TRD·프로그램 목록·StoryBoard와 갱신한 형상관리표 4종을 함께 관리합니다.
- 로컬 런타임 수정과 확장 DB는 유지하며 이번 문서 반영과 분리합니다. 운영 재배포를 완료했다는 뜻은 아닙니다.
