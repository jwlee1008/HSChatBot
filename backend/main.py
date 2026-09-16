"""
CampusRAG FastAPI 백엔드 서버

RESTful API 엔드포인트:
  - GET  /health          : 서버 상태 확인
  - POST /api/retrieve    : 유사도 검색만 수행 (LLM 불필요, 빠름)
  - POST /api/query       : RAG 전체 파이프라인 (검색 + LLM 생성)

실행:
  uvicorn backend.main:app --reload --port 8000
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from backend.schemas import (
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RetrieveResponse,
    SourceCard,
)
from core.rag import CampusRAG

logger = logging.getLogger(__name__)

# ── 전역 RAG 인스턴스 ──────────────────────────
rag_instance: CampusRAG | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 RAG 인스턴스를 관리한다."""
    global rag_instance
    logger.info("CampusRAG 서버 시작 — RAG 인스턴스 초기화")
    # 검색 전용으로 빠르게 시작, LLM은 첫 query 요청 시 지연 로드
    rag_instance = CampusRAG(load_llm=False)
    logger.info("RAG 인스턴스 초기화 완료 (검색 전용 모드)")
    yield
    logger.info("CampusRAG 서버 종료")


app = FastAPI(
    title="CampusRAG API",
    description="한성대학교 학내 공지사항 통합 RAG 챗봇 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정 (Streamlit 프론트엔드 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["시스템"])
async def health_check():
    """서버 상태 및 적재된 문서 수를 반환한다."""
    doc_count = 0
    if rag_instance:
        try:
            doc_count = rag_instance.vectorstore._collection.count()
        except Exception:
            pass

    return HealthResponse(
        status="ok",
        llm_provider=config.LLM_PROVIDER,
        doc_count=doc_count,
    )


@app.post("/api/retrieve", response_model=RetrieveResponse, tags=["RAG"])
async def retrieve(request: QueryRequest):
    """
    유사도 검색만 수행한다 (LLM 불필요, 빠름).

    공지사항 벡터 DB에서 질문과 가장 유사한 문서를 반환한다.
    """
    if not rag_instance:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다.")

    start = time.time()
    docs = rag_instance.retrieve(request.question, top_k=request.top_k)
    elapsed = time.time() - start
    logger.info("검색 완료: %.2f초, %d건", elapsed, len(docs))

    return RetrieveResponse(
        results=[
            SourceCard(
                title=doc.metadata.get("title", ""),
                source=doc.metadata.get("source", ""),
                category=doc.metadata.get("category", ""),
                date=doc.metadata.get("date", ""),
                url=doc.metadata.get("url", ""),
            )
            for doc in docs
        ],
        contents=[doc.page_content for doc in docs],
    )


@app.post("/api/query", response_model=QueryResponse, tags=["RAG"])
async def query(request: QueryRequest):
    """
    RAG 전체 파이프라인을 수행한다 (검색 + LLM 생성).

    유사도 검색 후 LLM이 검색 결과를 바탕으로 2~3줄 요약 답변을 생성한다.
    """
    global rag_instance

    if not rag_instance:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다.")

    # LLM이 로드되지 않았으면 지연 로드
    if rag_instance.llm is None:
        logger.info("LLM 지연 로드 시작 (provider: %s)", config.LLM_PROVIDER)
        try:
            rag_instance = CampusRAG(load_llm=True)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="LLM 서비스를 초기화할 수 없습니다.",
            )

    start = time.time()
    try:
        result = rag_instance.query(request.question, top_k=request.top_k)
    except Exception as e:
        logger.error("RAG 질의 실패: %s", str(e))
        raise HTTPException(status_code=500, detail="질의 처리 중 서버 내부 오류가 발생했습니다.")

    elapsed = time.time() - start
    logger.info("RAG 질의 완료: %.2f초", elapsed)

    raw_status = result.get("status", "success")
    raw_error = str(result.get("error") or "")
    safe_error_type = None
    if raw_status == "api_error":
        if "429" in raw_error or "RESOURCE_EXHAUSTED" in raw_error:
            safe_error_type = "rate_limit"
        elif "503" in raw_error or "UNAVAILABLE" in raw_error:
            safe_error_type = "service_unavailable"
        elif any(code in raw_error for code in ("401", "403", "PERMISSION_DENIED")):
            safe_error_type = "auth_error"
        else:
            safe_error_type = "internal_api_error"

    return QueryResponse(
        answer=result["answer"],
        sources=[SourceCard(**src) for src in result.get("sources", [])],
        status=raw_status,
        api_called=result.get("api_called", False),
        provider=result.get("provider", ""),
        model=result.get("model", ""),
        error_type=safe_error_type,
    )


# ── 프론트엔드 정적 파일 서빙 ───────────────────
# frontend-web/dist 빌드 결과물이 존재할 경우 루트(/) 및 에셋 서빙
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend-web" / "dist"
if _frontend_dist.is_dir() and (_frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
