"""
CampusRAG 전역 설정 모듈

환경 변수 또는 기본값으로 동작하며,
오픈소스 로컬 모델과 상용 API를 스위칭할 수 있는 하이브리드 구조.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# 프로젝트 경로
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHROMA_PERSIST_DIR = str(DATA_DIR / "chroma_db")
SAMPLE_NOTICES_PATH = str(DATA_DIR / "sample_notices.json")

# ──────────────────────────────────────────────
# 임베딩 모델 설정
# ──────────────────────────────────────────────
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask"
)

# ──────────────────────────────────────────────
# LLM 설정 (하이브리드 스위칭)
# ──────────────────────────────────────────────
# "local"  : HuggingFace 오픈소스 모델 (gemma-2-2b-it) — 기본값
# "gemini" : Google Gemini API
# "openai" : OpenAI API
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")

# 로컬 LLM 설정
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
LOCAL_LLM_MAX_NEW_TOKENS = int(os.getenv("LOCAL_LLM_MAX_NEW_TOKENS", "512"))

# Gemini API 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# OpenAI API 설정
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ──────────────────────────────────────────────
# RAG 파이프라인 설정
# ──────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "3"))  # 유사도 검색 반환 개수
CHROMA_COLLECTION_NAME = "campus_notices"

# ──────────────────────────────────────────────
# 디바이스 설정 (Apple Silicon MPS 자동 감지)
# ──────────────────────────────────────────────
def get_device() -> str:
    """사용 가능한 최적의 디바이스를 반환한다."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"
