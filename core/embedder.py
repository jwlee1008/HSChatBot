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


from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_notice_into_chunks(
    notice: dict,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[Document]:
    """
    단일 공지사항을 적절한 크기의 청크(Document)들로 분할한다.

    각 청크는 공지 헤더(분류, 제목, 등록일, 출처)를 공통 접두사로 포함하여
    개별 청크의 의미적 맥락(연도, 학기, 대상 등)을 완벽하게 유지한다.
    """
    if isinstance(notice, Document):
        meta = notice.metadata
        url = meta.get("url", "")
        base_id = meta.get("id") or hashlib.sha256(url.encode()).hexdigest()
        title = meta.get("title", "").strip()
        source = meta.get("source", "").strip()
        category = meta.get("category", "").strip()
        date = meta.get("date", "").strip()
        content = notice.page_content.strip()
        content_status = meta.get(
            "content_status",
            "title_only" if content == title or not content else "text",
        )
        has_ocr = bool(meta.get("has_ocr", False))
        has_attachment = bool(meta.get("has_attachment", False))
        extraction_summary = str(meta.get("extraction_summary", ""))
        extractions_json = meta.get("extractions_json", "")
    else:
        url = notice.get("url", "")
        base_id = notice.get("id") or hashlib.sha256(url.encode()).hexdigest()
        title = notice.get("title", "").strip()
        source = notice.get("source", "").strip()
        category = notice.get("category", "").strip()
        date = notice.get("date", "").strip()
        content = notice.get("content", "").strip()
        content_status = notice.get(
            "content_status",
            "title_only" if content == title or not content else "text",
        )
        has_ocr = bool(notice.get("has_ocr", False))
        has_attachment = bool(notice.get("has_attachment", False))
        extraction_summary = str(notice.get("extraction_summary", ""))
        extractions_json = (
            json.dumps(
                {
                    "images": notice.get("images", []),
                    "attachments": notice.get("attachments", []),
                },
                ensure_ascii=False,
            )
            if ("images" in notice or "attachments" in notice)
            else ""
        )

    header = f"[{category}] {title} (등록일: {date}, 출처: {source})"

    content_hash = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()[:16]

    base_metadata = {
        "id": base_id,
        "parent_id": base_id,
        "parent_url": url,
        "title": title,
        "source": source,
        "category": category,
        "date": date,
        "url": url,
        "content_status": content_status,
        "content_hash": content_hash,
        "has_ocr": has_ocr,
        "has_attachment": has_attachment,
        "extraction_summary": extraction_summary,
        "extractions_json": extractions_json,
    }

    # Preserve guidance provenance; never use crawl time as the publication date.
    provenance = notice.metadata if isinstance(notice, Document) else notice
    for key in ("source_type", "source_updated_at", "last_checked_at", "last_changed_at", "contact", "coverage_status"):
        if provenance.get(key):
            base_metadata[key] = str(provenance[key])
    if provenance.get("menu_path"):
        value = provenance["menu_path"]
        base_metadata["menu_path"] = " / ".join(value) if isinstance(value, list) else str(value)

    # 본문이 비어있거나 제목과 같으면 단일 청크 반환
    if not content or content == title:
        doc_id = f"{base_id}_c0"
        meta = dict(base_metadata)
        meta["parent_id"] = base_id
        meta["chunk_id"] = doc_id
        meta["chunk_index"] = 0
        meta["total_chunks"] = 1
        return [Document(page_content=f"{title}\n{content}", metadata=meta)]

    # 본문이 청크 크기 이하이면 단일 청크로 유지
    full_text = f"{title}\n{content}"
    if len(full_text) <= chunk_size:
        doc_id = f"{base_id}_c0"
        meta = dict(base_metadata)
        meta["parent_id"] = base_id
        meta["chunk_id"] = doc_id
        meta["chunk_index"] = 0
        meta["total_chunks"] = 1
        return [Document(page_content=full_text, metadata=meta)]

    # 긴 본문은 단락/줄바꿈 기준으로 분할
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    raw_chunks = splitter.split_text(content)

    documents = []
    total = len(raw_chunks)

    for idx, chunk in enumerate(raw_chunks):
        doc_id = f"{base_id}_c{idx}"
        chunk_meta = dict(base_metadata)
        chunk_meta["parent_id"] = base_id
        chunk_meta["chunk_id"] = doc_id
        chunk_meta["chunk_index"] = idx
        chunk_meta["total_chunks"] = total

        # 청크 헤더 결합으로 맥락 보존
        page_content = f"{header}\n\n{chunk}"
        documents.append(Document(page_content=page_content, metadata=chunk_meta))

    return documents


def load_notices_from_json(
    json_path: str,
    enable_chunking: bool = True,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[Document]:
    """
    JSON 파일에서 공지사항을 읽어 LangChain Document 리스트로 변환한다.

    Args:
        json_path: 공지사항 JSON 파일 경로
        enable_chunking: True이면 긴 공지를 청킹하여 분할 적재 (기본값: True)
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"공지사항 파일을 찾을 수 없습니다: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    documents = []
    for notice in notices:
        if enable_chunking:
            chunks = split_notice_into_chunks(
                notice, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
            documents.extend(chunks)
        else:
            # 기존 단일 문서 모드 (하위 호환)
            page_content = f"{notice['title']}\n{notice['content']}"
            metadata = {
                "id": notice["id"],
                "title": notice["title"],
                "source": notice["source"],
                "category": notice["category"],
                "date": notice["date"],
                "url": notice["url"],
                "content_status": notice.get(
                    "content_status",
                    "title_only"
                    if notice["content"].strip() == notice["title"].strip()
                    else "text",
                ),
                "has_ocr": bool(notice.get("has_ocr", False)),
                "has_attachment": bool(notice.get("has_attachment", False)),
                "extraction_summary": str(notice.get("extraction_summary", "")),
                "extractions_json": json.dumps(
                    {
                        "images": notice.get("images", []),
                        "attachments": notice.get("attachments", []),
                    },
                    ensure_ascii=False,
                )
                if ("images" in notice or "attachments" in notice)
                else "",
            }
            documents.append(Document(page_content=page_content, metadata=metadata))

    logger.info(
        "JSON에서 %d건의 공지사항으로부터 %d건의 Document를 로드했습니다.",
        len(notices),
        len(documents),
    )
    return documents


def ingest_to_chroma(
    documents: list[Document],
    persist_directory: str | None = None,
    collection_name: str | None = None,
    replace: bool = False,
) -> Chroma:
    """
    Document 리스트를 Chroma DB에 임베딩하여 적재한다.

    청킹된 Document와 일반 Document 모두 지원하며,
    청크 ID(`chunk_id`) 또는 URL 해시 기반 고유 ID를 부여하여 중복을 방지한다.
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

    # Document 객체뿐 아니라 raw dict 입력도 자동으로 분할/변환 지원
    processed_docs: list[Document] = []
    for item in documents:
        if isinstance(item, dict):
            processed_docs.extend(split_notice_into_chunks(item))
        elif isinstance(item, Document):
            processed_docs.append(item)
        else:
            raise TypeError(f"지원하지 않는 문서 타입: {type(item)}")
    documents = processed_docs

    vectorstore = Chroma(
        embedding_function=embeddings,
        persist_directory=persist_dir,
        collection_name=col_name,
    )

    # 고유 ID 생성 (청크 ID 우선, 없으면 URL 해시)
    unique = {}
    target_parent_ids = set()
    target_urls = set()

    for doc in documents:
        doc_id = doc.metadata.get("chunk_id")
        if not doc_id:
            key = doc.metadata.get("url") or doc.metadata["id"]
            doc_id = hashlib.sha256(key.encode()).hexdigest()
        unique[doc_id] = doc

        pid = doc.metadata.get("parent_id") or doc.metadata.get("id")
        if pid:
            target_parent_ids.add(str(pid))
        purl = doc.metadata.get("parent_url") or doc.metadata.get("url")
        if purl:
            target_urls.add(str(purl))

    # 갱신 대상 공지에 속한 기존 청크/문서 ID 탐색
    existing_data = vectorstore.get(include=["metadatas"])
    existing_ids = existing_data.get("ids", [])
    existing_metas = existing_data.get("metadatas", []) or []

    if replace:
        candidate_stale_ids = set(existing_ids)
    else:
        candidate_stale_ids = set()
        for eid, emeta in zip(existing_ids, existing_metas):
            emeta = emeta or {}
            emeta_pid = str(emeta.get("parent_id") or emeta.get("id") or "")
            emeta_url = str(emeta.get("parent_url") or emeta.get("url") or "")
            # ID 자체가 parent_id인 레거시 단일 문서이거나, parent_id/url이 갱신 대상과 일치하는 경우
            if (
                eid in target_parent_ids
                or emeta_pid in target_parent_ids
                or (emeta_url and emeta_url in target_urls)
            ):
                candidate_stale_ids.add(eid)

    # 1. 신규 문서 적재 (실패 시 예외 발생하여 하단 삭제 미수행 -> 기존 데이터 안전 보존)
    vectorstore.add_documents(list(unique.values()), ids=list(unique))

    # 2. 신규 적재 성공 후, 갱신 대상 공지의 불필요해진 이전 청크 삭제
    stale_ids = candidate_stale_ids - unique.keys()
    if stale_ids:
        logger.info("갱신 대상 공지의 이전 청크 %d건 정리 (IDs: %s)", len(stale_ids), list(stale_ids))
        vectorstore.delete(ids=list(stale_ids))

    logger.info("Chroma DB 적재 완료: %d건 (고유 청크: %d건)", len(documents), len(unique))
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
