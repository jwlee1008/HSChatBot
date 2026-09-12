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

# 5. 샘플 데이터 적재
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
