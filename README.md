# 🎓 CampusRAG: 한성대학교 학내 공지사항 통합 RAG 챗봇

> 분산된 학내 공지사항을 통합하여, 자연어 질문으로 필요한 정보를 빠르게 찾을 수 있는 AI 챗봇 시스템

## 📌 프로젝트 개요

대학교 본부 공지, 단과대 공지, 학과별 공지사항이 흩어져 있어 학생들이 원하는 학사 정보를 찾기 어려운 문제를 해결합니다.

**핵심 기능**: 자연어 질문 → **2~3줄 핵심 요약 + 공식 공지사항 원문 링크/등록일 카드** 반환

## 🛠 기술 스택

| 계층 | 기술 |
|------|------|
| 데이터 수집 | Python, BeautifulSoup4, Requests |
| 임베딩 | `jhgan/ko-sroberta-multitask` (한국어 특화) |
| 벡터 DB | ChromaDB |
| 생성 LLM | `google/gemma-2-2b-it` (오픈소스 경량 모델) |
| RAG 프레임워크 | LangChain |
| 백엔드 | FastAPI |
| 프론트엔드 | Streamlit |
| 배포 | Docker, Hugging Face Spaces |

## 🚀 빠른 시작

### 사전 요구사항
- Python 3.10+
- pip
- **Tesseract OCR (한국어 언어팩 포함)**:
  - **macOS**: `brew install tesseract tesseract-lang`
  - **Ubuntu/Debian**: `sudo apt-get install -y tesseract-ocr tesseract-ocr-kor`

### 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/your-team/CampusRAG.git
cd CampusRAG

# 2. 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일에서 필요한 값을 수정

# 5. 실제 공지 수집 및 적재
playwright install chromium
python -m crawler.hansung_pw --pages 5 --with-content
python scripts/ingest.py

# 6. 검색 테스트
python -c "
from core.rag import CampusRAG, print_retrieve_results
rag = CampusRAG()
results = rag.retrieve('수강신청 일정')
print_retrieve_results(results)
"
```

### 테스트 실행

```bash
pytest tests/ -v
```

## 📁 프로젝트 구조

```
CampusRAG/
├── config.py              # 전역 설정 (모델 스위칭)
├── requirements.txt       # 의존성
├── core/                  # AI & RAG 코어
│   ├── embedder.py        # 임베딩 + 벡터 DB 적재
│   ├── rag.py             # RAG 파이프라인
│   └── prompts.py         # 프롬프트 템플릿
├── crawler/               # 웹 크롤러
├── backend/               # FastAPI 서버
├── frontend/              # Streamlit UI
├── data/                  # 데이터
├── scripts/               # 유틸리티 스크립트
└── tests/                 # 테스트
```

## 📄 라이선스

MIT License

## 👥 팀

한성대학교 캡스톤디자인 프로젝트

## 공지 링크 / 답변 데이터 복구

`data/sample_notices.json`은 테스트용 가상 공지이며 원문 URL은 실제 공지가 아닙니다.
운영 DB에 샘플을 섞지 마세요. 기본 적재 파일은 `data/crawled_notices.json`입니다.
기존 샘플과 중복 문서를 정리하려면 서버를 종료하고 `data/chroma_db`를 백업한 뒤 실행하세요.

```bash
python -m crawler.hansung_pw --pages 5 --with-content
python scripts/ingest.py --json-path data/crawled_notices.json --replace
# FastAPI 서버 재시작
uvicorn backend.main:app --port 8000
```

`--replace`는 입력 JSON에 없는 기존 문서도 제거하므로, 유지할 공지를 포함한 파일을 사용하세요.
일반 적재는 URL 기준 upsert로 동일 공지의 본문/메타데이터를 갱신합니다.
국가장학금은 최신 전체 목록에 없을 수 있어 제목 검색 목록도 수집합니다.
추출 텍스트가 없거나 실패하여 제목만 있는 공지(`content_status: title_only`)는 세부 내용을 추측하지 않고 원문 확인을 안내합니다.

## 📄 OCR 및 첨부파일 텍스트 수집/추출 (1단계)

학내 공지사항의 본문 이미지 및 첨부파일(PDF, HWP, HWPX)에서 텍스트를 로컬 오픈소스 방식으로 안전하게 추출하여 RAG 파이프라인에 결합합니다.

### 1. 지원 형식 및 방식
- **본문 이미지 (JPG, PNG 등)**: Tesseract 한국어/영어 OCR (`kor+eng`)로 로컬 추출
- **PDF 문서**:
  - 텍스트 PDF: `pypdf`를 통한 초고속 텍스트 레이어 추출
  - 스캔 PDF: `pypdfium2`로 페이지 고해상도 렌더링 후 Tesseract OCR 적용 (최대 10페이지 제한)
- **HWPX (한글 개방형 문서)**: 표준 KS X 6101 XML 파싱으로 무손실 텍스트 추출
- **HWP (한글 5.0)**: `olefile` 기반 zlib 스트림 압축 해제 및 태그 레코드(HWPTAG_PARA_TEXT) 파싱

### 2. 한계 및 예외 상태 코드
- **암호화/배포용 문서**: 비밀번호가 걸려있거나 DRM이 적용된 HWP 문서는 파싱이 불가능하며, `unsupported_encrypted` 상태로 명시 기록합니다.
- **손상/비표준 문서**: 파싱 예외 발생 시 전체 파이프라인이 중단되지 않고 `failed` 또는 `unsupported_format` 상태를 기록합니다.
- **다운로드 보안 (SSRF 방어)**: 사설 IP(`127.0.0.1`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16` 등) 및 루프백 접근을 리다이렉트를 포함하여 엄격히 차단합니다.
- **리소스 보호**: 파일당 20MB 상한, 타임아웃, SHA-256 파일 캐시를 적용하여 중복 다운로드/OCR을 방지합니다.

### 3. 일괄 보강 실행
```bash
# 기존 공지사항 JSON에 이미지/첨부파일 텍스트 보강
python scripts/enrich_notices.py --input data/crawled_notices.json --output data/crawled_notices_enriched.json

# 국가장학금 공지만 우선 보강
python scripts/enrich_notices.py --filter-keyword "국가장학" --limit 10
```

GitHub Actions에서 생성한 DB는 실행 중인 서버에 자동 전달되지 않습니다.
갱신된 JSON을 서비스에 반영한 후 적재하고 서버를 재시작해야 합니다.
