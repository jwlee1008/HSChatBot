# CampusRAG 한성대학교 공식 정보 질의응답 챗봇

**저학년의 반란 · 문서 기준일 2026년 11월 4일**

CampusRAG는 한성대학교의 공개 공지, 학사 안내, FAQ와 서식을 검색해 질문에 필요한 답변과 공식 원문 출처를 제공하는 웹 챗봇입니다. 학교의 공식 서비스가 아닌 학생 프로젝트이며, 신청 기간과 자격 등 중요한 조건은 연결된 공식 원문에서 확인합니다.

- 기준 저장소: [jwlee1008/HSChatBot](https://github.com/jwlee1008/HSChatBot), 브랜치 `main`
- [문서 목록](docs/README.md) · [저장소 구성과 형상관리](docs/repository_structure.md)
- [최신 프로그램 목록·WBS·Project Charter](outputs/campusrag_docs_20261104/README.md): 현재 코드·운영 기록 반영, 2026-11-04 개정
- [중간발표 최종 PPT와 Word 대본](outputs/campusrag_midterm_final_20261021/README.md): 8장, 설명 7분·시연 3분
- [홈서버 최신 코드·명칭 적용 및 발표 인계 프롬프트](docs/campusrag_home_server_presentation_handoff_20261021.md)
- [10월 설계 산출물 4종](outputs/campusrag_design_20261018/README.md) · [제품 요구사항과 수행 계획](docs/chatbot_release_20261007/README.md)

## 홈서버 상태 2026년 11월 4일

- 배포 주소: [hschatbot.jwlee.dev](https://hschatbot.jwlee.dev). Windows 11 + Docker Desktop + Cloudflare Tunnel. 확인 시점 서버는 **수동 정지 상태**이며 로컬 `/health` 연결도 거부됨.
- 서버 설정: `local` / `Qwen/Qwen2.5-1.5B-Instruct`, NVIDIA GPU 예약, `jhgan/ko-sroberta-multitask` 임베딩. 활성 데이터는 `data/knowledge_runtime/active/` bind mount 사용.
- 저장 활성본: **1,576문서 / 7,534청크**, 제목만 확보한 문서 3개. manifest 생성 2026-10-31 12:37 KST, 최신 공지 등록일 10월 30일.
- 최근 갱신 성공: 10월 31일 12:53 KST, strict 동기화 일치·대표 검색 4/4 기록. 최근 11월 3일 작업은 `skipped_stopped`. Windows `CampusMate-KnowledgeRefresh`는 매일 06:00 KST 등록, 수동 정지 시 건너뜀.
- 서버 RAG·수집·검증·적용 코드는 `main`에 포함. 로컬 자동 적용 설정은 [서버 Compose 예제](docker-compose.server.example.yml)로 제공. `.env`·모델 캐시·활성 DB·서버 외부 예약 스크립트는 별도 관리.
- 10월 21일 실제 질의·GPU·배포 기록: [홈서버 적용 및 발표 조사](docs/campusrag_home_server_presentation_audit_20261021.md). 당시 실측과 현재 정지 상태 구분.

## 현재 제품 범위

로그인 없이 학내 정보 질문을 입력하고, 관련 근거를 바탕으로 작성한 답변과 출처 카드를 확인합니다. 화면의 예시 질문, 대화 초기화, 안내 및 오픈소스 모달도 제공합니다.

각 질문은 독립적으로 처리합니다. 이전 대화가 화면에 남아 있어도 API에는 현재 질문만 전달합니다. 관련 근거가 없거나 제목만 수집된 자료는 상세 답변을 유보하고, 생성 API나 통신에 문제가 있으면 오류를 안내합니다.

회원가입, 로그인, 개인 일정 등록·추출, 캘린더와 마감 알림은 현재 제품 범위에서 제외합니다. 관련 코드는 [archived_features/personal_schedule_20260927](archived_features/personal_schedule_20260927/README.md)에 보관하며 기본 실행·배포 경로에 포함하지 않습니다. 공지에 있는 학사 일정의 질의응답은 현재 범위에 포함합니다.

## 실행 흐름과 기술 구성

```text
React 웹 질문 입력
  → FastAPI 요청 검증
  → 한국어 임베딩과 Chroma 근거 검색
  → 선택한 근거로 LLM 답변 생성
  → 답변과 공식 원문 출처 표시

공개 자료 수집 → 이미지·첨부 텍스트 추출 → 통합 JSON → 새 검색 색인 → 검증과 운영 반영
```

| 영역 | 기술과 역할 |
|---|---|
| 사용자 화면 | React, TypeScript, Vite, Tailwind CSS. `frontend-web/`의 모바일 중심 웹 UI |
| API | FastAPI, Pydantic. 질문 검증, 검색·답변 API, 웹 빌드 결과 정적 서빙 |
| 검색 | LangChain, `jhgan/ko-sroberta-multitask` 임베딩, ChromaDB |
| 답변 생성 | 환경변수로 `local`, `gemini`, `openai` 중 선택 |
| 자료 수집 | Python, Requests, BeautifulSoup 및 선택적인 Playwright 수집 경로 |
| 이미지·첨부 | Tesseract OCR, PDF·HWP·HWPX 텍스트 추출기 |
| 실행 환경 | Python 3.12와 Node.js 22를 사용하는 Docker 빌드, Docker Compose |

생성 모델과 검색 임베딩은 별개입니다. API 제공자를 사용해도 검색 임베딩은 서버에서 실행합니다. 실제 제공자·모델과 사용 가능한 API 한도는 배포 환경에 따라 확인합니다.

## 로컬에서 시작하기

Linux/WSL2의 Python 3.12, Node.js 22와 npm 기준입니다. Windows 호스트는 Docker Desktop 사용을 권장합니다. 현재 잠금 의존성은 x86_64에서 CUDA 12.4 PyTorch를 설치하며, CPU 전용 경량 설치나 Windows 네이티브 pip 설치를 검증한 구성은 아닙니다.

```bash
git clone https://github.com/jwlee1008/HSChatBot.git
cd HSChatBot

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
npm ci --prefix frontend-web
npm run build --prefix frontend-web

# Git 통합 JSON과 같은 버전의 새 검색 색인 생성
python scripts/ingest_unified_db.py \
  --dataset data/unified_campus_knowledge.json \
  --persist-dir data/local_chroma_db \
  --collection campus_knowledge
python scripts/check_data_status.py \
  --json-path data/unified_campus_knowledge.json \
  --db-path data/local_chroma_db \
  --collection-name campus_knowledge --strict
```

색인은 아직 존재하지 않는 경로에 생성합니다. `.env`의 `CHROMA_PERSIST_DIR=data/local_chroma_db`, `NOTICES_PATH=data/unified_campus_knowledge.json`, `CHROMA_COLLECTION_NAME=campus_knowledge`를 맞춘 뒤 실행합니다. 저장소 기본 Chroma와 통합 JSON은 서로 다른 버전이므로 새 색인 검증이 필요합니다.

`.env.example`의 `LLM_PROVIDER=local`은 로컬 생성 모델까지 다운로드하고 로드할 수 있습니다. Gemini·OpenAI는 제공자와 사용할 모델·키를 서버 환경변수로 지정합니다. 검색 임베딩도 최초 다운로드가 필요합니다. 현재 지원 모델명·API 한도는 제공자 계정에서 확인합니다.

```bash
PREWARM_RAG_ON_STARTUP=false python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 <http://127.0.0.1:8000>을 엽니다. 화면은 `frontend-web/dist/`에 `index.html`이 있을 때 FastAPI가 제공합니다. 개발용 웹 서버는 `npm run dev --prefix frontend-web`으로 실행하며, API 프록시는 [Vite 설정](frontend-web/vite.config.ts)을 따릅니다.

`PREWARM_RAG_ON_STARTUP=false`는 기동 시 사전 로드만 생략합니다. 첫 검색이나 질문에는 임베딩과 필요한 모델의 초기화가 발생할 수 있습니다.

## 설정

값의 정의는 [.env.example](.env.example)과 [config.py](config.py)를 기준으로 합니다. 현재 `.env`의 비밀값은 문서나 저장소에 포함하지 않습니다.

| 환경변수 | 용도 |
|---|---|
| `LLM_PROVIDER` | `local`, `gemini`, `openai`. 코드 기본값은 `local` |
| `LOCAL_LLM_MODEL` | 로컬 생성 모델. 코드 기본값은 `Qwen/Qwen2.5-1.5B-Instruct` |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS` | Gemini 생성 설정과 대기 제한 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI 생성 설정 |
| `EMBEDDING_MODEL` | 검색 임베딩 모델 |
| `CHROMA_PERSIST_DIR` | 사용할 Chroma 디렉터리 |
| `CHROMA_COLLECTION_NAME` | 검색 컬렉션. 통합 자료는 `campus_knowledge` |
| `NOTICES_PATH` | 검색 원본 JSON 경로 |
| `TOP_K`, `RELEVANCE_THRESHOLD` | 검색 개수와 관련성 기준 |
| `PREWARM_RAG_ON_STARTUP` | 시작 시 검색 모델 사전 로드 여부 |

## API

| Method | 경로 | 동작 |
|---|---|---|
| `GET` | `/health` | 서버 생존 상태, 제공자와 초기화된 컬렉션의 문서 수 반환 |
| `POST` | `/api/retrieve` | 생성 LLM 없이 관련 근거 검색 |
| `POST` | `/api/query` | 근거 검색과 답변 생성, 공식 출처 반환 |

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"국가장학금 신청 기간은 언제인가요?","top_k":3}'
```

`question`은 1~500자, `top_k`는 1~10이며 기본값은 3입니다. 답변의 `status`는 `success`, `no_context`, `title_only_notice`, `api_error`를 구분합니다. 실제 호출의 제공자와 모델은 `provider`, `model`로 확인합니다.

`/health.doc_count`는 원문 문서 수가 아닌 **Chroma 청크 수**입니다. `status=ok`는 생존 응답이며 모델·검색·생성 준비 완료를 보장하지 않습니다. 지연 초기화 전 `doc_count=0`이 가능하며, 검색과 실제 생성은 해당 API로 확인합니다. `api_called=true`는 생성 호출 표시이며, 로컬 제공자에서도 true일 수 있습니다.

## 데이터 버전과 갱신

| 구분 | 확인된 기준 | 해석 |
|---|---|---|
| Git 기본 Chroma | 1,366문서 / 3,447청크 | [기본 적재 보고서](data/integrated_eval_chroma_db/ingest_report.json). 9월 seed 유지 |
| Git 통합 JSON | 1,485문서, 2026-10-09 생성 | [통합 JSON](data/unified_campus_knowledge.json)·[manifest](data/unified_manifest.json). 기본 Chroma와 버전 불일치. 새 색인 필요 |
| 서버 저장 활성본 | 1,576문서 / 7,534청크, 2026-10-31 | 안내145·FAQ179·서식57·공지1,195. Git 미포함. 현재 서비스 정지 |
| Git 원본 수집 자료 | 원본별 재확인 시각 유지 | 11월 3일 원격 수집 이력과 10월 31일 서버 수집본을 문서 ID·확인 시각으로 병합. 원본 갱신과 통합·색인·운영 적용 구분 |

`data/sample_notices.json`은 테스트용 가상 자료입니다. 운영 색인에 섞지 않습니다. 등록일과 마지막 수집 확인일을 구분하고, 본문이 없는 자료는 원문 확인을 안내합니다.

`main`의 후보 생성 CLI는 운영 DB와 다른 경로에 JSON·manifest·Chroma를 만들고 strict 동기화를 검사합니다. 새 수집 없이 저장 원본만 사용할 때:

```bash
python scripts/refresh_knowledge.py --skip-collect

# 수집·이미지/첨부 보강도 수행할 때
python scripts/refresh_knowledge.py --enrich

# 출력된 후보 경로와 검증할 질문 세트 지정
python scripts/verify_knowledge_snapshot.py \
  data/knowledge_snapshots/<RUN> \
  --cases data/knowledge_refresh_daily_cases.json
```

후보 상태 `validated_candidate`와 검색 검사 통과를 확인한 뒤 서비스 정지·백업·묶음 교체·재시작·실질의를 수행합니다. `scripts/activate_knowledge_snapshot.py`는 `--server-stopped`와 적용 경로를 받아 교체·실패 복구를 처리합니다. 서버 외부 Windows 스크립트가 이 전체 흐름과 수동 정지 정책을 관리합니다. 절차는 [홈서버 데이터 운영](docs/home_server_knowledge_operations_20261008.md) 참고.

GitHub 수집 workflow는 원본 자료를 기록하며 홈서버 활성 DB를 자동 교체하지 않습니다. 후보 생성 성공도 운영 적용 완료를 뜻하지 않습니다. `scripts/build_unified_dataset.py`는 기본 JSON·manifest를 다시 쓰므로 활성 경로에서 직접 실행하지 않습니다. 실행 중인 Chroma 파일을 덮어쓰지 않습니다.

## 이미지와 첨부 수집

채팅 화면에서 파일을 업로드하는 기능과 구분되는 운영자용 수집 기능입니다. 공개 공지의 본문 이미지, PDF, HWP와 HWPX에서 텍스트를 추출합니다. 암호화·손상·미지원 파일은 상태를 남기며, 파일 크기·다운로드 시간·페이지 수 제한을 적용합니다.

OCR 수집을 실행할 환경에는 Tesseract와 한국어 언어 데이터가 필요합니다. 브라우저 기반 수집 경로를 사용할 때만 Playwright를 추가 준비합니다.

```bash
# macOS OCR 도구 예시
brew install tesseract tesseract-lang

# 브라우저 수집 경로를 사용하는 경우
python -m pip install playwright
python -m playwright install chromium

# 기존 공지 JSON의 이미지·첨부 본문 보강
python scripts/enrich_notices.py \
  --input data/crawled_notices.json \
  --output data/crawled_notices_enriched.json
```

## Docker 실행과 운영 확인

```bash
docker compose up -d --build backend
docker compose ps
```

Docker 빌드는 웹과 API를 한 이미지에 포함하며 기본 서비스 포트는 `127.0.0.1:8000`입니다. Compose의 `chroma_data`와 `model_cache`는 데이터를 영속 보관합니다. **기존 `chroma_data` 볼륨은 이미지 재빌드만으로 새 DB로 교체되지 않습니다.**

새 clone은 먼저 `.env.example`을 `.env`로 복사합니다. Compose 단독 기본값은 `gemini`, `.env.example`은 `local`이므로 실제 제공자를 `.env`에 명시합니다. Docker 이미지의 기본 Chroma도 위의 9월 seed이며, 최신 통합 JSON으로 검증한 색인과 경로를 맞춰 적용해야 합니다.

[Dockerfile.worker](Dockerfile.worker)는 Tesseract 한국어·영어 데이터를 포함한 수집·색인 이미지입니다. [서버 Compose 예제](docker-compose.server.example.yml)는 GPU와 `knowledge_runtime/active` 경로를 사용하므로 해당 GPU·검증된 활성 묶음을 준비한 서버에서만 적용합니다. 예제는 자동 로드되지 않습니다. `docker-compose.override.yml`은 서버 로컬 설정으로 유지합니다.

[Dockerfile.runtime-update](Dockerfile.runtime-update)는 검증된 로컬 이미지 위에 앱·웹을 갱신하는 경로입니다. `RUNTIME_IMAGE`에 실제 검증 이미지 태그 또는 digest를 지정해야 합니다. 일반 새 설치는 기본 Dockerfile을 사용합니다. 자세한 실행은 [컨테이너 가이드](docs/campusrag_local_container_guide.md), 과거 배포 이력은 [Cloudtype 기록](docs/cloudtype_chatbot_deployment.md) 참고.

## 검증

개발 환경에는 테스트 도구를 별도로 설치합니다. 다음은 저장소에 포함된 챗봇 범위의 선별 오프라인 회귀 명령입니다.

```bash
python -m pip install pytest httpx
PREWARM_RAG_ON_STARTUP=false python -m pytest \
  tests/test_chatbot_only.py \
  tests/test_codex_round2_fixes.py \
  tests/test_codex_fixes.py \
  tests/test_retrieval_grounding.py \
  tests/test_date_parsing.py \
  tests/test_activate_knowledge_snapshot.py \
  tests/test_enrich_notice_archive.py \
  tests/test_official_knowledge_retrieval.py \
  tests/test_refresh_knowledge.py \
  tests/test_unified_refresh.py -q
```

2026-11-04 검증: 위 선별 회귀 **145 passed**. 기존 백엔드 이미지 기반 격리 컨테이너, 네트워크 차단·읽기 전용 소스에서 실행. `npm ci`와 `npm run build --prefix frontend-web`의 TypeScript·Vite 빌드 통과. 새로운 전체 의존성 이미지 재빌드 결과는 아님.

단위·mock 회귀 결과는 실제 생성 답변의 정확도, 사용자 만족도 또는 운영 성능 결과와 구분합니다. 대표 질문의 원문 대조 평가, 최신 데이터 적용과 실제 단말 테스트는 각각 증거를 남겨 확인합니다.

남은 작업: 웹 500자 사전 제한·초기화 중 요청 취소, 표현에 따른 검색 누락, 기간·대상·제외 조건 오답 개선. 현재 날짜 자동 주입·멀티턴·PWA는 미구현입니다. 30~50문항 근거 지지율 90%, 학생 10명 이상·만족도 4.0/5는 평가 전 목표이며 3초 응답 보장은 하지 않습니다. 후속 작업은 최신 WBS 참고.

## 저장소 구성

```text
HSChatBot/
├── README.md                    # 프로젝트 소개와 실행 안내
├── backend/                     # FastAPI와 요청·응답 스키마
├── core/                        # 검색·생성·임베딩과 첨부 추출
├── crawler/                     # 공식 안내·FAQ·공지 수집
├── frontend-web/                # 현재 React 웹과 정적 빌드
├── frontend/                    # 이전 Streamlit UI 참고 코드
├── scripts/                     # 통합·색인·평가·진단 명령
├── tests/                       # 단위·API·검색·추출 회귀
├── data/                        # 수집 JSON·통합 manifest·기본 지식 seed
├── docs/                        # 문서 목록, PRD, 운영 기록과 검토 이력
├── outputs/campusrag_docs_20261104/    # 최신 프로그램 목록·WBS·헌장
├── outputs/campusrag_design_20261018/  # 10월 설계 산출물 4종
├── archived_features/           # 개인 일정·인증 기능 보관
├── archived_artifacts/          # 이전 기획·발표 자료 보관
├── .github/workflows/           # CI와 수집 스케줄
├── .env.example                 # 비밀값 없는 환경변수 예시
├── requirements*.txt            # Python 의존성
├── config.py                    # 경로·모델·검색 설정
├── Dockerfile                   # 웹·API 다단계 빌드
├── Dockerfile.worker            # OCR 수집·색인 worker
├── Dockerfile.runtime-update    # 검증 이미지 위 앱·웹 갱신
├── docker-compose.server.example.yml # GPU·활성 지식 경로 예제
└── docker-compose.yml           # 포트·볼륨·헬스체크
```

폴더 역할, 브랜치와 자료 버전 관리 원칙은 [저장소 구성 문서](docs/repository_structure.md)에 정리했습니다. 루트의 이전 계획서와 발표자료는 역사 기록이며 최신 제출본은 문서 목록의 기준일을 확인합니다.

## 팀과 라이선스

팀명은 **저학년의 반란**입니다. 실명별 역할과 제출 기한은 팀에서 확정하며 문서에 임의로 추가하지 않습니다.

소스 코드는 [MIT License](LICENSE)에 따라 배포합니다. 모델·폰트·라이브러리와 학내 자료의 고지는 [OPEN_SOURCE_LICENSES.md](OPEN_SOURCE_LICENSES.md)를 참고합니다.
