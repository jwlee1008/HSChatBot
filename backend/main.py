"""
CampusRAG FastAPI 백엔드 서버

RESTful API 엔드포인트:
  - GET  /health          : 서버 상태 확인
  - POST /api/retrieve    : 유사도 검색만 수행 (LLM 불필요, 빠름)
  - POST /api/query       : RAG 전체 파이프라인 (검색 + LLM 생성)

실행:
  uvicorn backend.main:app --reload --port 8000
"""

import asyncio
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

# ── 전역 RAG 인스턴스 및 비동기 락 ──────────────
rag_instance: CampusRAG | None = None
_rag_lock = asyncio.Lock()


async def get_or_init_rag(load_llm: bool = False) -> CampusRAG:
    """RAG 인스턴스를 안전하게 비차단/지연 초기화한다."""
    global rag_instance
    if rag_instance is not None:
        if load_llm and rag_instance.llm is None:
            async with _rag_lock:
                if rag_instance.llm is None:
                    loop = asyncio.get_running_loop()
                    rag_instance = await loop.run_in_executor(
                        None, lambda: CampusRAG(load_llm=True)
                    )
        return rag_instance

    async with _rag_lock:
        if rag_instance is None:
            logger.info("CampusRAG 인스턴스 초기화 시작 (load_llm=%s)...", load_llm)
            loop = asyncio.get_running_loop()
            rag_instance = await loop.run_in_executor(
                None, lambda: CampusRAG(load_llm=load_llm)
            )
            logger.info("CampusRAG 인스턴스 초기화 완료")
        elif load_llm and rag_instance.llm is None:
            loop = asyncio.get_running_loop()
            rag_instance = await loop.run_in_executor(
                None, lambda: CampusRAG(load_llm=True)
            )
        return rag_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작 시 8000번 포트를 즉시 개방하여 쿠버네티스 Startup Probe(헬스체크)를
    0.1초 만에 통과시키고, 무거운 모델 다운로드 및 로딩은 백그라운드 태스크로 비차단 수행한다.
    """
    logger.info("CampusRAG 서버 기동 — 8000번 포트 즉시 개방")
    asyncio.create_task(get_or_init_rag(load_llm=False))
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
    rag = await get_or_init_rag(load_llm=False)

    start = time.time()
    docs = rag.retrieve(request.question, top_k=request.top_k)
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
    try:
        rag = await get_or_init_rag(load_llm=True)
    except Exception as e:
        logger.error("LLM 서비스 초기화 실패: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail="LLM 서비스를 초기화할 수 없습니다.",
        )

    start = time.time()
    try:
        result = rag.query(request.question, top_k=request.top_k)
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
