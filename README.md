# CampusMate 한성대학교 공식 정보 질의응답 챗봇

**저학년의 반란 · 문서 기준일 2026년 10월 18일**

CampusMate는 한성대학교의 공개 공지, 학사 안내, FAQ와 서식을 검색해 질문에 필요한 답변과 공식 원문 출처를 제공하는 웹 챗봇입니다. 학교의 공식 서비스가 아닌 학생 프로젝트이며, 신청 기간과 자격 등 중요한 조건은 연결된 공식 원문에서 확인합니다.

- 기준 저장소: [jwlee1008/HSChatBot](https://github.com/jwlee1008/HSChatBot), 브랜치 `main`
- [문서 목록](docs/README.md) · [저장소 구성과 형상관리](docs/repository_structure.md)
- [최신 설계 산출물 4종](outputs/campusmate_design_20261018/README.md) · [제품 요구사항과 수행 계획](docs/chatbot_release_20261007/README.md)

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

Python 3.12, Node.js 22와 npm을 기준으로 안내합니다. Python 의존성은 플랫폼별 조건을 포함하므로 설치 환경의 OS와 CPU를 확인합니다.

```bash
git clone https://github.com/jwlee1008/HSChatBot.git
cd HSChatBot

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
npm ci --prefix frontend-web
npm run build --prefix frontend-web
```

`.env`에서 생성 제공자와 필요한 키·모델을 설정한 다음 실행합니다. 기본 `LLM_PROVIDER=local`은 로컬 생성 모델까지 다운로드하고 로드할 수 있습니다. Gemini 또는 OpenAI를 쓰려면 해당 제공자의 키와 계정에서 사용할 수 있는 모델명을 지정합니다. 키는 서버 환경변수에만 보관합니다.

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

`/health`의 `status=ok`는 모델·검색·생성 준비 완료를 보장하지 않습니다. 지연 초기화 전 `doc_count=0`이 가능하며, 검색 준비와 실제 답변은 해당 API로 따로 확인합니다.

## 데이터 버전과 갱신

| 구분 | 확인된 기준 | 해석 |
|---|---|---|
| Git 기본 지식 seed | 1,366문서 / 3,447청크. 2026-09-15 통합본 | [적재 보고서](data/integrated_eval_chroma_db/ingest_report.json)와 [manifest](data/unified_manifest.json)의 기록 |
| 10월 9일 로컬 확장본 | 1,485문서 / 6,886청크, 제목만 있는 문서 3개 | 10월 18일 TRD가 참조한 로컬 작업 결과. 이번 문서 반영에 확장 DB와 관련 런타임 변경을 포함하지 않음 |
| Git 원본 수집 자료 | 안내·FAQ 등의 원본이 별도로 갱신됨 | 원본 파일이 갱신돼도 통합 JSON·Chroma 및 운영 서버 반영은 별도 단계 |

`data/sample_notices.json`은 테스트용 가상 자료입니다. 운영 색인에 섞지 않습니다. 등록일과 마지막 수집 확인일을 구분하고, 본문이 없는 자료는 원문 확인을 안내합니다.

현재 `main`에서 사용할 수 있는 통합·색인 명령은 다음과 같습니다. 후보 색인은 **아직 존재하지 않는 새 경로**에 생성합니다. 아래 예시 경로가 이미 있으면 다른 후보 이름을 사용합니다.

```bash
python scripts/build_unified_dataset.py
python scripts/ingest_unified_db.py \
  --dataset data/unified_campus_knowledge.json \
  --persist-dir data/readme_candidate_chroma_db \
  --collection campus_knowledge
python scripts/check_data_status.py \
  --json-path data/unified_campus_knowledge.json \
  --db-path data/readme_candidate_chroma_db \
  --collection-name campus_knowledge --strict
```

통합 명령은 기본 JSON·manifest를 다시 만들기 때문에 운영 중인 경로를 직접 갱신하지 않고 검증용 checkout에서 실행합니다. 검증된 JSON·색인·manifest를 같은 버전으로 적용하고 서버 재시작 후 대표 질문과 원문 링크를 확인합니다. 실행 중인 Chroma 파일을 덮어쓰지 않습니다.

GitHub 수집 workflow는 원본 자료를 기록하며 운영 DB를 자동 교체하지 않습니다. 로컬 확장 작업에 있는 `refresh_knowledge.py`, `activate_knowledge_snapshot.py` 등의 추가 CLI는 이번 문서 커밋과 별도이며, 현재 `main`에 있다고 가정하지 않습니다.

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

실행·배포 세부 사항은 [컨테이너 가이드](docs/campusmate_local_container_guide.md)를 참고합니다. [Cloudtype 문서](docs/cloudtype_chatbot_deployment.md)는 당시 배포 설정과 장애 수정 기록입니다. 이전 홈서버 운영 기록의 주소는 <https://hschatbot.jwlee.dev>이며, 이번 문서 갱신에서 운영 배포 상태와 사용 모델을 새로 확인한 것은 아닙니다.

## 검증

개발 환경에는 테스트 도구를 별도로 설치합니다. 다음은 저장소에 포함된 챗봇 범위의 선별 오프라인 회귀 명령입니다.

```bash
python -m pip install pytest httpx
PREWARM_RAG_ON_STARTUP=false python -m pytest \
  tests/test_chatbot_only.py \
  tests/test_codex_round2_fixes.py \
  tests/test_codex_fixes.py \
  tests/test_retrieval_grounding.py \
  tests/test_date_parsing.py -q
```

단위·mock 회귀 결과는 실제 생성 답변의 정확도, 사용자 만족도 또는 운영 성능 결과와 구분합니다. 대표 질문의 원문 대조 평가, 최신 데이터 적용과 실제 단말 테스트는 각각 증거를 남겨 확인합니다.

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
├── outputs/campusmate_design_20261018/  # 최신 설계 산출물 4종
├── archived_features/           # 개인 일정·인증 기능 보관
├── archived_artifacts/          # 이전 기획·발표 자료 보관
├── .github/workflows/           # CI와 수집 스케줄
├── .env.example                 # 비밀값 없는 환경변수 예시
├── requirements*.txt            # Python 의존성
├── config.py                    # 경로·모델·검색 설정
├── Dockerfile                   # 웹·API 다단계 빌드
└── docker-compose.yml           # 포트·볼륨·헬스체크
```

폴더 역할, 브랜치와 자료 버전 관리 원칙은 [저장소 구성 문서](docs/repository_structure.md)에 정리했습니다. 루트의 이전 계획서와 발표자료는 역사 기록이며 최신 제출본은 문서 목록의 기준일을 확인합니다.

## 팀과 라이선스

팀명은 **저학년의 반란**입니다. 실명별 역할과 제출 기한은 팀에서 확정하며 문서에 임의로 추가하지 않습니다.

소스 코드는 [MIT License](LICENSE)에 따라 배포합니다. 모델·폰트·라이브러리와 학내 자료의 고지는 [OPEN_SOURCE_LICENSES.md](OPEN_SOURCE_LICENSES.md)를 참고합니다.
