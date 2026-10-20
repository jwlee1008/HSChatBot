# CampusRAG 홈서버 적용·발표 조사

작업일: 2026-10-21 KST. 운영 확인: 01:20~01:30. 팀: 저학년의 반란.

후속 완료: [8장 중간발표 PPT와 Word 대본](../outputs/campusrag_midterm_final_20261021/README.md). 아래 내용은 최종 제작에 사용한 1단계 조사 기록이다.

CampusRAG 명칭 배포 완료. 홈서버에서 검색·답변 생성까지 수행. 운영 자료 **1,529문서 / 7,202청크**. FAQ·행사 답변 확인. 도서관 검색 실패·장학 공지 날짜 오답도 재현.

## 1. 두 프롬프트 비교·적용 결과

| 자료 | 요구·주장 | 이번 처리 |
|---|---|---|
| [Codex 인계](campusrag_home_server_presentation_handoff_20261021.md), 원격 `b8aed9e` | 최신 코드 수신, CampusRAG 명칭, 운영 실측, 기존 발표 확인, 8장 구성안 | 실행·기록 |
| 사용자 첨부 `HSChatBot_중간발표_개선분석_및_홈서버_통합브리핑.md` | 드리프트 진단, 검색·시점·표·청킹·대화 개선 | 현 코드·운영과 대조, 후속 과제 도출 |
| 사용자 범위 선택 | **명칭 적용·운영 검증·개선 분석 우선** | 구현 범위 기준 |

문서 안 명령문은 분석 자료로 취급. 모델 교체·전체 재수집·재색인·멀티턴·PWA 신규 개발·PPT/대본 개편은 실행하지 않음.

### Git·백업

- 실제 저장소: `C:\server01\services\hs-chatbot`. 기준 원격: `https://github.com/jwlee1008/HSChatBot.git`.
- 시작: `server01/knowledge-20261009`, `828ce2d`, 추적 파일 수정 11개·기존 미추적 보고서 1개.
- 백업 브랜치: `server01/pre-campusrag-20261021`, `df6593e`. 서버 RAG·프롬프트·CUDA 의존성·수집 JSON 수정 보존.
- 작업 브랜치: `server01/campusrag-audit-20261021`.
- 원격 기준: `b8aed9e9b7b06f265690d88dc6bb9f66b251a0a7`. 서버 전용 커밋 존재로 fast-forward 불가. `5b3408a`에서 병합.
- 충돌 4개: 최신 원격 README 채택 후 서버 운영 안내 추가. `official_faq.json`, `official_pages.json`, `official_site_inventory.json`은 서버 수집본 유지. 원격 자료는 Git 이력에 보존.
- Compose: GPU·모델·활성 DB override, 컨테이너명, 60초 health 주기·로그 제한 유지. 새 `CAMPUSRAG_PORT`와 기존 `CAMPUSMATE_PORT` 모두 지원. 실제 포트 `127.0.0.1:8000` 유지.
- 외부 백업: `C:\server01\archive\handoffs\campusrag-audit-20261021-0122`. 변경 파일·서버 전용 override/worker·기존 보고서·운영 웹 파일·검증 기록 보관. `.env` 출력·커밋 없음.
- 이 작업은 로컬 커밋까지 수행. GitHub push·PR·원격 main 변경 없음.

### 배포

- 실행 소스 커밋: **`db095aec4d021bdaf3072dc06d88abe3e3cfe1fe`**. 이후 조사 문서 커밋은 실행 소스와 구분.
- 이전 이미지: `hs-chatbot-backend:rollback-20261021`, ID `sha256:7aa067e3e6471d0f02c4affa7e9fb8558a236980194d01ce885bbc5db5365557`.
- 배포 이미지: `hs-chatbot-backend:campusrag-20261021`, ID `sha256:789b3d7ab647279e001edd946e1d6f277ba6c6b9d71e159ff5f953189faf4deb`.
- [Dockerfile.runtime-update](../Dockerfile.runtime-update) 추가. 검증된 기존 이미지 위에 앱 소스·웹 빌드만 반영. 전체 Dockerfile 빌드에서 의존성 재설치 감지 후 중단. 운영 컨테이너에는 영향 없음.
- `npm ci`, TypeScript 검사, Vite 빌드 통과. 배포 전후 `pip freeze` 전체 일치. 모델·임베딩·활성 JSON/manifest·핵심 코드·override SHA256 일치.
- `Global\Server01ServerControl` 잠금 안에서 backend만 재생성. 01:24:37~01:24:54 KST, health 준비 확인. 다른 서비스 유지.
- 실제 도메인 제목·상단명·첫 안내·정보 모달: **CampusRAG**. 공개 JS `/assets/index-C3XmnSgZ.js`에서 CampusRAG 6개, CampusMate 0개 확인.
- 공개 JS와 빌드 JS SHA256 일치: `3f28b7744d2ce467cbc7f6564d79a28223144935a4b8da1563dedc3f0eb4b852`.
- `/` 응답 `Cache-Control: no-cache`. 새 해시 JS 사용. 이전 해시 자산은 기존 이미지 안에 남아 있음. 이미 열린 이전 탭은 새로고침 필요.
- 장애 시 저장된 이전 이미지로 `latest` 태그 복원 후 같은 서버 제어 잠금 안에서 backend 재생성. 데이터 전환·볼륨 삭제 없이 복귀 가능.

### 기존 발표 수신

| 파일 | 확인 |
|---|---|
| `outputs/campusrag_midterm_20261019/CampusRAG_중간발표_10분_v1.2_20261019.pptx` | 155,368바이트, 슬라이드 XML 12장 |
| 같은 폴더 `CampusRAG_중간발표_대본_20261019.docx` | 43,725바이트, 수신 |
| 같은 폴더 `CampusRAG_중간발표_대본_20261019.md` | 13,613바이트, 내용 확인 |
| 같은 폴더 `README.md`, Codex 인계, `docs/README.md`, 설계·제출 자료 폴더 | 수신 |

기존본은 설명 10분·실시간 시연 별도. 이번 8장·설명 7분+시연 3분 안과 구분. 새 PPT·대본 제작 없음.

## 2. 실제 운영 환경

| 항목 | 실측·근거 |
|---|---|
| OS | Windows 11 Pro, `10.0.26200` |
| CPU·RAM | Intel i7-11800H, 8코어/16스레드, 호스트 RAM 15.71GiB |
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU, VRAM 6,144MiB. 생성 후 약 4,316MiB 사용. 프로세스 전체 사용량이며 모델 단독 사용량 아님 |
| 컨테이너 | Docker Desktop Linux x86_64, Engine 29.7.2, Compose 5.3.1. Docker 메모리 약 7.76GiB |
| 서비스 | Compose 프로젝트 `hs-chatbot`, 컨테이너 `server01-hs-chatbot`, `uvicorn backend.main:app --host 0.0.0.0 --port 8000` |
| 공개 경로 | HTTPS `hschatbot.jwlee.dev` → Cloudflare Tunnel → `127.0.0.1:8000` |
| 생성 | `LLM_PROVIDER=local`, `Qwen/Qwen2.5-1.5B-Instruct`, Transformers/HuggingFacePipeline. 실제 응답 provider/model 확인 |
| 연산 | PyTorch `2.6.0+cu124`, `torch.cuda.is_available()=True`, 설정 선택 `cuda`. 생성 후 GPU 메모리 증가 관찰 |
| 임베딩 | `jhgan/ko-sroberta-multitask`. 생성 모델과 별도 |
| 코드 | backend/config/핵심 core 파일의 실행 컨테이너·작업본 SHA256 일치. core와 config는 기존 bind mount 유지 |
| 활성 Chroma | `/app/knowledge_runtime/active/chroma_db`, collection `campus_knowledge` |
| 활성 JSON | `/app/knowledge_runtime/active/unified_campus_knowledge.json` |
| 호스트 활성 경로 | `C:\server01\services\hs-chatbot\data\knowledge_runtime\active` |
| 원문·청크 | 활성 JSON 1,529문서. health 7,202는 Chroma collection 항목 수, 즉 **청크 수** (`backend/main.py:106`) |
| 문서 구성 | 안내145 / FAQ179 / 서식57 / 공지1,148 |
| 본문 상태 | text1,074 / mixed199 / attachment241 / ocr12 / title_only3 |
| 최신 공지 등록일 | 2026-10-19. 전체 학교 공지의 최신성·완전성 보장 의미 아님 |
| 활성 버전 | manifest `2026-10-19T21:04:53.487665+00:00` = 10/20 06:04:53 KST |
| 일일 갱신 | Windows `CampusMate-KnowledgeRefresh`, 매일06:00 KST. 기존 작업명 유지 |
| 최근 실행 | 10/20 06:00:03~06:20:49, 결과0/success, 검색4/4, 7,202청크 적용. 다음 실행10/21 06:00 예정 |
| 현재 상태 | 로컬·공개 `/health`: ok/local/7,202. 현재 전체 컨테이너7개 healthy 관찰 |
| PWA | 활성 소스·원격 main·기존 서버 브랜치·실행 dist에서 web manifest/service worker 미발견. 모바일 메타 태그만 확인 |

생성까지 홈서버에서 실행. 이번 성공 응답의 `api_called=true`는 생성 호출 표시이며 외부 API 사용을 뜻하지 않음. 관찰 당시 provider는 local.

### 데이터 버전 차이

| 위치 | 원문 수 | 해석 |
|---|---:|---|
| 원격 `origin/main` 통합 seed | 1,366 | 현재 Git 기본 자료 |
| 서버 저장소 루트 `data/unified_campus_knowledge.json` | 1,485 | 10/09 보강 seed |
| 실제 `knowledge_runtime/active` | 1,529 | 10/20 자동 적용 운영본 |

수 차이는 현재도 존재. 서버 일일 수집·검증·스냅샷 활성화 경로는 이미 설치됨. 첨부의 “통합 스크립트 없음”, “named volume만 사용” 주장은 현 서버에는 해당하지 않음. 원격 기본 seed와 운영 스냅샷 배포를 같은 과정으로 표현하지 않음.

기존 named volume `chroma_data`는 `/app/data/integrated_eval_chroma_db`에 남아 있으나, 실제 설정은 bind mount의 `knowledge_runtime/active` 사용. 이미지 재빌드로 운영 DB 교체하지 않음.

활성 JSON SHA256 `a7133e106754043402ff4e1b2381b74a06fd84f995c1ae50e9f97894aa25764b`, manifest `548554123e9bb611967d1a83654ceaa1cf23c961126e66200a18ca0d9cc70035`. 배포 전후 일치.

PWA 구현 위치·설치 단말은 미확인. 원격 head는 main 한 개. 보관 폴더의 `manifest.json`은 파일 해시 목록이며 PWA manifest 아님. 설치·독립 창·오프라인 동작·기존 설치명 갱신을 완료로 보고하지 않음.

## 3. 모델·배포 변화와 근거

| 시점 | 확인 사실 | 근거·한계 |
|---|---|---|
| 9/14 | 로컬 Qwen2.5-1.5B, MPS 환경에서 20문항 평가 | `data/eval_final_results.json`. 자동16/20·수동15/20은 당시 표본 기록 |
| 9/15 | Gemini 실제 생성·오류 기록 | `docs/gemini_smoke.md`: 복제 데모DB217청크, 생성4건·유보2건·503오류2건. 당시 완료 요청3.6~8.9초 |
| 9/15 확장 평가 | Gemini 429·한도 오류 기록 | `data/eval_phase2_expansion_results.json`: PASS1·API_ERROR9. 당시 응답의 limit20을 현재 한도로 쓰지 않음 |
| 9/16 | Cloudtype 배포용 CPU Torch·초기 로딩 처리 수정 | 커밋 `1688f72`, `cc5ad0c`, `4a75e91` |
| 9/26 | Cloudtype 실제 대시보드 조사 | `docs/codex_cloudtype_assessment_20260926.md`: Python3.12·프리티어1GB·중지 상태. 중지 원인/OOM 미확정 |
| 10/07~08 | Cloudtype 의존성·화면 누락·Gemini timeout 수정 | `docs/cloudtype_chatbot_deployment.md`, `c7b985c`, `51efe28`, `5aba801`, `48ec3a5` |
| 10/09 | 홈서버 Gemini 실제 실행 이력 | `logs/campusmate/refresh-history.jsonl`: 15:23 시작 실행 success, 모델 `gemini-3.5-flash-lite` |
| 10/10 이후 | 홈서버 로컬 Qwen 실행 이력 | 같은 로그 10/10 06:00부터 Qwen success. 정확한 모델 전환 시각·당시 GPU 사용은 미확정 |
| 10/21 현재 | 홈서버 CUDA 로컬 생성·웹 운영 | 이번 실제 답변·패키지·GPU·마운트 조사 |

발표 흐름: **로컬 모델 평가 / Gemini 생성 도입 / Cloudtype 배포 제약·장애 수정 / 홈서버 운영**.

Gemini 실호출이 Cloudtype 배포 조사보다 앞섬. “무료 호스팅 후 Gemini 도입”을 확정 연표로 쓰지 않음. Gemma 실사용·HuggingFace 호스팅 근거 미발견. Cloudtype OOM·API 비용 때문에 이전했다는 인과관계도 미확정. 현재 Gemini 모델 지원·가격·한도는 이번 조사 대상 아님.

## 4. 완료 항목·개선 과제

### 발표에 넣을 완료 항목

- CampusRAG 명칭·React 웹·FastAPI·한국어 임베딩·Chroma·로컬 생성 연동.
- 공식 자료 수집, 이미지·첨부 추출, 출처 링크·근거 없을 때 답변 유보.
- 홈서버 GPU 생성, HTTPS 접근, 검증 후 일일 지식 스냅샷 적용·복구 경로.
- 실제 FAQ·행사 답변 확인. 일부 실패도 재현. 전체 정확도·전반 성능 향상 수치로 환산하지 않음.

### 후속 개선 3개

| 우선 | 과제 | 현 근거·다음 검증 |
|---|---|---|
| 1 | 원문 표·이미지/OCR 보존, 핵심 날짜·조건 검증 | 거창군 공지 실제 기간10/16~11/16인데 답변 마감10/16. `notice_archive.py:89`, `pipeline.py:48`, `hwp.py:58`의 평문 추출·표 손실. 공통 table 추출·OCR 품질 점검·정답 fixture 우선 |
| 2 | 현재 날짜·학기·종료 기간 인지 | `rag.py:546` 후보 최대 등록일 기준, `:613` 최신성 가산, `prompts.py` 현재 날짜 입력 없음. KST 기준일·기간 만료 판정·과거 자료 안내. 명시적 과거 질문은 보존 |
| 3 | 질의 정규화·동의어·검색 평가 | 도서관 인사형 질문 no_context 재현. `rag.py:453` 원문 임베딩. 인사 제거·도서관/학술정보관 확장 후 회귀 평가. BM25·멀티턴은 별도 설계 |

### Antigravity 주장 보정

| 주장 | 현 코드 판정 |
|---|---|
| 도서관 인사형 실패 | 현재 운영 재현. 첨부 raw_score0.2482·차이0.0018은 이번 미계측 |
| 후보 날짜 기반 최신성·특정 시각 하드코딩 | 현재도 존재. `rag.py:651`의 15/17/18시 규칙 포함 |
| HTML 표 보존 부재 | 공지·일부 추출기에서 확인. `official_site.py:68`에는 병합 셀 처리·기존 테스트 존재 |
| 출처 카드 무필터 | `rag.py:712` 점수격차 필터 이미 존재. 답변에 실제 사용한 출처 검증은 없음 |
| 짧은 청크 헤더 누락 | 본문 헤더 차이 확인. metadata·프롬프트에서 출처/날짜 보충. 단독 심각도 낮음 |
| history·전체 Markdown 부재 | 확인. 현재 API는 단발 질문, 화면은 줄바꿈·글머리표 중심 |
| 고정 공지 카테고리 오염·33건 고정 출력 | 코드 위험·고정 문자열 확인. 이번 운영 재수집은 수행하지 않음 |
| Git 대용량 DB 제한 때문에 코드까지 미반영 | 미반영 코드·서버 전용 경로는 확인. 당시 누락의 직접 원인은 문서 주장. DB 파일은 이번 커밋·교체 없음 |
| Gemini 기본 모델명 오류 | 코드 문자열 확인. 현재 local 사용. 모델 유효성·교체는 이번 미검증·미변경 |

## 5. 실제 질의·시연안

측정: 공개 HTTPS 클라이언트 왕복 총시간. 첫 웹 FAQ 질의 후 측정했으므로 아래 값은 **모델 로드 후 측정**. 냉간 첫 응답시간 미측정. 요청 반복값을 성능 분포로 확대 해석하지 않음.

| 질문 | 시간 | 상태·원문 대조 |
|---|---:|---|
| 평점평균 계산시 소수점 셋째 자리부터 반올림하나요, 버림 처리하나요? | 2.711초, 반복2.691초 | HTTP200/success. 절사·예시3.4975→3.49, [공식 FAQ](https://www.hansung.ac.kr/bbs/hansung/2148/artclList.do?page=8) 일치. 웹 답변·출처 카드도 확인 |
| 행복米밥차 행사는 언제 어디서 열리고, 누가 참여할 수 있어? | 3.555초 | HTTP200/success. 10/22 11~13시·미래관 앞·재학생/모바일 학생증, [원문](https://www.hansung.ac.kr/bbs/hansung/2127/225059/artclView.do) 일치. 재료 소진 조기 종료 단서는 답변에 없음 |
| 2026년 2학기 거창군 지역출신 대학생 등록금 지원사업 신청 방법 | 13.806초 | HTTP200/success이나 **내용 오답**. [원문 포스터](https://www.hansung.ac.kr/bbs/hansung/2127/225520/artclView.do)는 접수10/16~11/16. 답변은 마감10/16으로 생성. 일부 대상 조건 누락·비한국어 조각도 관찰 |
| 안녕, 도서관 운영시간 알려줄래? | 0.691초 | HTTP200/no_context, 생성 호출 없음. 첨부 검색 실패 재현 |

FAQ·행사·실패 사례의 원시 응답: [validation.json](../outputs/campusrag_home_server_audit_20261021/validation.json). 이번 표본으로 정확도 비율 산출하지 않음. `status=success`는 내용 정답 판정과 다름.

도서관·거창군 질문은 성공 시연에서 제외. 실패·향후 과제 설명에는 실제 관찰 사례로 사용 가능.

### 3분 시연

| 구간 | 동작 |
|---|---|
| 0~15초 | 도메인·CampusRAG 명칭 확인 |
| 15~60초 | FAQ 입력·대기·답변 확인. 평점 처리 설명 |
| 60~95초 | 공식 FAQ 링크·답변 대조 |
| 95~145초 | 행복米밥차 질문·대기·날짜/장소/대상 확인. 날짜는 발표 당일 원문 재확인 |
| 145~180초 | 공지 원문에서 모바일 학생증·조기 종료 단서 확인. 설명 마무리 |

행사는 2026-10-22 예정. 행사 이후 발표에서는 과거 일정 질문임을 명시하거나 새 검증 질문 선정. 리허설 때 같은 질문 재확인. 지연·장애 시 저장된 실제 FAQ 화면으로 전환하고 캡처 사용임을 밝힘. 행사 녹화는 아직 없음. PWA 설치 검증 전 시연 시간에 포함하지 않음.

추가 관찰: 기본 Python urllib User-Agent는 Cloudflare HTTP403/1010. 명시한 `CampusRAG-Operational-Audit/1.0` User-Agent와 실제 웹 브라우저는 정상. 해당 HTTP 오류를 LLM 장애로 집계하지 않음.

## 6. 8장·10분 구성안

| 장 | 내용 | 시간 | 누적 |
|---|---|---:|---|
| 1 | 표지: CampusRAG·저학년의 반란 | 20초 | 0:00~0:20 |
| 2 | 프로젝트 소개: 공식 정보 질문·근거 링크 | 45초 | 0:20~1:05 |
| 3 | 구현 기능: 익명 질문·답변·출처·답변 유보 | 55초 | 1:05~2:00 |
| 4 | 개발 변화: 로컬 평가·Gemini·Cloudtype·홈서버 | 70초 | 2:00~3:10 |
| 5 | 현재 구조: 웹→FastAPI→임베딩/Chroma→로컬 GPU 생성 | 80초 | 3:10~4:30 |
| 6 | 실제 웹 시연 | 180초 | 4:30~7:30 |
| 7 | 완료·개선: 운영 경로, 원문 보존·시점·검색 과제 | 100초 | 7:30~9:10 |
| 8 | 역할분담 | 50초 | 9:10~10:00 |

설명420초+시연180초. 질의응답 별도. 기존 데이터 규모·예외 처리·평가 수치는 대본 끝 예상 질문으로 이동. 90%·학생10명·4/5점 등 기존 목표를 실측으로 쓰지 않음. 과거 테스트 통과율을 현재 답변 정확도로 쓰지 않음.

| 이름 | 역할 | 표기 기준 |
|---|---|---|
|  | 개발 총괄: 설계·핵심 개발·통합·배포 | 사용자 역할안 |
|  | PWA 구현 | 구현 위치·수행 범위 확인 필요 |
|  | 데이터 수집·정리 | 개인별 수행 내역은 별도 확인 |
|  | 기능 테스트·사용성 점검 | 실제 이력 미확정, 향후 담당안 |

예상 질문: RAG 사용 이유, 데이터 범위·최신성, 모델·서버 변경 근거, 비용·속도, 오답, 검증 표본, PWA 설치·오프라인 범위. 비용·현재 API 한도·동시 접속 성능은 미측정으로 답변.

## 7. 다음 결정·근거 파일

- 발표 개편 진행 여부. 이번 결과는 구성안까지 작성.
- PWA 팀원 작업 저장소·브랜치·폴더 위치. 현 서버 구현·설치 완료로 발표할 근거 부족.
- 네 번째 역할의 실제 수행 기록 또는 향후 담당 표기.
- 발표 날짜에 맞는 행사 질문 재선정 여부. 지금 검증한 행사 예정일10/22.

자료: [검증 JSON](../outputs/campusrag_home_server_audit_20261021/validation.json), [실제 웹 FAQ 화면](../outputs/campusrag_home_server_audit_20261021/campusrag-web-faq.png), [장학 공지 기간 화면](../outputs/campusrag_home_server_audit_20261021/notice-source-period.png). 원본 로그·패키지 비교·배포 결과는 위 외부 백업 경로에 보관.
