"""
CampusRAG 임베딩 및 벡터 DB 적재 모듈

JSON 형태의 공지사항 데이터를 읽어 벡터 임베딩을 생성하고
Chroma DB에 적재하는 기능을 담당한다.
"""

import hashlib
import json
import logging
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

import config

logger = logging.getLogger(__name__)


def get_embedding_model() -> HuggingFaceEmbeddings:
    """한국어 임베딩 모델(ko-sroberta-multitask)을 로드하여 반환한다."""
    logger.info("임베딩 모델 로딩: %s", config.EMBEDDING_MODEL_NAME)
    return HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cpu"},  # 임베딩은 CPU로 충분
        encode_kwargs={"normalize_embeddings": True},
    )


def load_notices_from_json(json_path: str) -> list[Document]:
    """
    JSON 파일에서 공지사항을 읽어 LangChain Document 리스트로 변환한다.

    각 Document의 page_content에는 '제목 + 내용'을 결합하고,
    metadata에는 검색 결과 카드에 필요한 정보를 포함한다.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"공지사항 파일을 찾을 수 없습니다: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    documents = []
    for notice in notices:
        # 제목과 내용을 결합하여 검색 품질 향상
        page_content = f"{notice['title']}\n{notice['content']}"
        metadata = {
            "id": notice["id"],
            "title": notice["title"],
            "source": notice["source"],
            "category": notice["category"],
            "date": notice["date"],
            "url": notice["url"],
            "content_status": notice.get("content_status", "title_only" if notice["content"].strip() == notice["title"].strip() else "text"),
        }
        documents.append(Document(page_content=page_content, metadata=metadata))

    logger.info("JSON에서 %d건의 공지사항을 로드했습니다.", len(documents))
    return documents


def ingest_to_chroma(
    documents: list[Document],
    persist_directory: str | None = None,
    collection_name: str | None = None,
    replace: bool = False,
) -> Chroma:
    """
    Document 리스트를 Chroma DB에 임베딩하여 적재한다.

    Args:
        documents: 적재할 LangChain Document 리스트
        persist_directory: Chroma DB 영속화 경로 (기본값: config에서 로드)
        collection_name: Chroma 컬렉션 이름 (기본값: config에서 로드)

    Returns:
        적재가 완료된 Chroma 벡터 스토어 인스턴스
    """
    persist_dir = persist_directory or config.CHROMA_PERSIST_DIR
    col_name = collection_name or config.CHROMA_COLLECTION_NAME
    embeddings = get_embedding_model()

    logger.info(
        "Chroma DB에 %d건 적재 시작 (경로: %s, 컬렉션: %s)",
        len(documents),
        persist_dir,
        col_name,
    )

    if not documents:
        raise ValueError("빈 데이터로 기존 DB를 교체할 수 없습니다.")
    vectorstore = Chroma(
        embedding_function=embeddings,
        persist_directory=persist_dir,
        collection_name=col_name,
    )
    # URL이 동일한 고정 공지/재수집 공지는 하나의 문서로 upsert한다.
    unique = {}
    for doc in documents:
        key = doc.metadata.get("url") or doc.metadata["id"]
        doc_id = hashlib.sha256(key.encode()).hexdigest()
        unique[doc_id] = doc
    old_ids = set(vectorstore.get()["ids"]) if replace else set()
    vectorstore.add_documents(list(unique.values()), ids=list(unique))
    # 신규 적재 성공 후에만 이전 샘플/중복/수집 범위 밖 문서를 제거한다.
    stale_ids = old_ids - unique.keys()
    if stale_ids:
        vectorstore.delete(ids=list(stale_ids))

    logger.info("Chroma DB 적재 완료: %d건", len(documents))
    return vectorstore


def get_chroma_vectorstore(
    persist_directory: str | None = None,
    collection_name: str | None = None,
) -> Chroma:
    """이미 적재된 Chroma DB를 로드하여 반환한다."""
    persist_dir = persist_directory or config.CHROMA_PERSIST_DIR
    col_name = collection_name or config.CHROMA_COLLECTION_NAME
    embeddings = get_embedding_model()

    return Chroma(
        persist_directory=persist_dir,
        collection_name=col_name,
        embedding_function=embeddings,
    )
