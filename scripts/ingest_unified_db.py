#!/usr/bin/env python3
"""
CampusRAG 통합 격리 DB 적재 스크립트

통합 데이터셋(data/unified_campus_knowledge.json)을 읽어
새로운 격리 Chroma DB(data/integrated_eval_chroma_db)에 적재한다.
운영 DB(data/chroma_db)와 기존 검증 DB(data/verify_demo_chroma_db)는 일절 변경하지 않는다.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


PROTECTED_DB_DIRS = [
    ROOT / "data/chroma_db",
    ROOT / "data/verify_demo_chroma_db",
    ROOT / "data/eval_chroma_db",
]


def validate_persist_dir(persist_dir: Path | str) -> Path:
    """
    격리 DB 경로 방어:
    1) 운영 DB, 기존 검증 DB, 심볼릭 링크 경로로의 적재 시도를 엄격히 차단한다.
    2) 기존 DB의 덮어쓰기·초기화·잔존 청크 오염을 원천 차단하기 위해,
       빈 디렉터리를 포함하여 이미 존재하는 모든 경로는 거부하고 오직 '존재하지 않는 새 경로만' 허용한다.
    """
    p = Path(persist_dir)

    # 1. 심볼릭 링크 자체 검사
    if p.is_symlink():
        raise PermissionError(f"심볼릭 링크 경로는 보안상 허용되지 않습니다: {p}")

    resolved = p.resolve()

    # 2. 보호된 운영 및 검증 DB 경로 대조
    for protected in PROTECTED_DB_DIRS:
        prot_resolved = protected.resolve()
        if resolved == prot_resolved:
            raise PermissionError(f"보호된 DB 경로({protected})로는 절대 적재할 수 없습니다.")
        try:
            resolved.relative_to(prot_resolved)
            raise PermissionError(f"보호된 DB({protected})의 하위 경로로의 적재는 금지됩니다: {p}")
        except ValueError:
            pass
        try:
            prot_resolved.relative_to(resolved)
            raise PermissionError(f"보호된 DB({protected})를 포함하는 상위 경로 지정은 금지됩니다: {p}")
        except ValueError:
            pass

    # 3. 기존 디렉터리 존재 시 즉시 거부 (빈 디렉터리 포함, 새 경로만 허용)
    if resolved.exists():
        raise FileExistsError(
            f"대상 경로({p})가 이미 존재합니다. "
            "기존 데이터 보호 및 잔존 청크 오염 방지를 위해 아직 존재하지 않는 새로운 경로만 허용됩니다."
        )

    return resolved


def ingest_unified(
    dataset_path: Path = ROOT / "data/unified_campus_knowledge.json",
    persist_dir: Path = ROOT / "data/integrated_eval_chroma_db",
    collection_name: str = "campus_knowledge",
    batch_size: int = 100,
) -> dict:
    """통합 데이터셋을 새로운 격리 DB에 적재한다 (오직 새 경로만 허용)."""
    if not dataset_path.exists():
        raise FileNotFoundError(f"통합 데이터셋이 존재하지 않습니다: {dataset_path}")

    # 경로 유효성 및 보안성 검증 (새 경로만 허용)
    target_dir = validate_persist_dir(persist_dir)
    target_dir.mkdir(parents=True, exist_ok=False)
    os.environ["CHROMA_PERSIST_DIR"] = str(target_dir)
    os.environ["CHROMA_COLLECTION_NAME"] = collection_name

    from core.embedder import get_embedding_model, split_notice_into_chunks
    from langchain_chroma import Chroma

    logger.info("통합 데이터 로드: %s", dataset_path)
    with open(dataset_path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    logger.info("총 %d개 문서를 청킹으로 변환 시작...", len(notices))
    all_chunks = []
    chunk_counts_by_type = {}
    for item in notices:
        chunks = split_notice_into_chunks(item)
        all_chunks.extend(chunks)
        st = item.get("source_type", "unknown")
        chunk_counts_by_type[st] = chunk_counts_by_type.get(st, 0) + len(chunks)

    logger.info(
        "청킹 완료: 총 %d개 문서 -> %d개 청크",
        len(notices),
        len(all_chunks),
    )
    for st, cnt in chunk_counts_by_type.items():
        logger.info("  - %s: %d 청크", st, cnt)

    # 멱등성 보장을 위한 고유 chunk_id 생성 및 중복 제거
    unique_chunks = {}
    for doc in all_chunks:
        cid = doc.metadata.get("chunk_id")
        if not cid:
            base = doc.metadata.get("id") or doc.metadata.get("url")
            cid = f"{base}_c{doc.metadata.get('chunk_index', 0)}"
            doc.metadata["chunk_id"] = cid
        unique_chunks[cid] = doc

    chunks_to_ingest = list(unique_chunks.values())
    chunk_ids = list(unique_chunks.keys())

    logger.info(
        "격리 Chroma DB 적재 시작: %s (컬렉션: %s, 고유 청크 수: %d)",
        persist_dir,
        collection_name,
        len(chunks_to_ingest),
    )

    embeddings = get_embedding_model()
    vectorstore = Chroma(
        embedding_function=embeddings,
        persist_directory=str(persist_dir),
        collection_name=collection_name,
    )

    # 배치 단위 적재 (진행상황 로깅 및 안정성 확보)
    start_time = time.monotonic()
    total = len(chunks_to_ingest)
    for i in range(0, total, batch_size):
        b_docs = chunks_to_ingest[i : i + batch_size]
        b_ids = chunk_ids[i : i + batch_size]
        vectorstore.add_documents(b_docs, ids=b_ids)
        if (i + len(b_docs)) % 500 == 0 or (i + len(b_docs)) == total:
            logger.info("  적재 진행: %d / %d 청크 완료 (%.1f%%)", i + len(b_docs), total, (i + len(b_docs)) / total * 100)

    elapsed = time.monotonic() - start_time
    total_stored = vectorstore._collection.count()
    logger.info("격리 Chroma DB 적재 완료! 총 저장 청크: %d, 소요 시간: %.2f초", total_stored, elapsed)

    sqlite_path = persist_dir / "chroma.sqlite3"
    sqlite_sha256 = ""
    if sqlite_path.exists():
        sqlite_sha256 = hashlib.sha256(sqlite_path.read_bytes()).hexdigest()

    summary = {
        "dataset_path": str(dataset_path.relative_to(ROOT)),
        "persist_dir": str(persist_dir.relative_to(ROOT)),
        "collection_name": collection_name,
        "total_documents": len(notices),
        "total_chunks": len(chunks_to_ingest),
        "stored_chunks_count": total_stored,
        "sqlite_sha256": sqlite_sha256,
        "chunk_counts_by_type": chunk_counts_by_type,
        "elapsed_seconds": round(elapsed, 2),
    }

    report_path = persist_dir / "ingest_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info("적재 요약 보고서 저장: %s", report_path)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CampusRAG Unified DB Ingest Script (New Paths Only)")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/unified_campus_knowledge.json")
    parser.add_argument("--persist-dir", type=Path, default=ROOT / "data/integrated_eval_chroma_db")
    parser.add_argument("--collection", type=str, default="campus_knowledge")
    parser.add_argument("--batch-size", type=int, default=150)
    args = parser.parse_args()

    ingest_unified(
        dataset_path=args.dataset,
        persist_dir=args.persist_dir,
        collection_name=args.collection,
        batch_size=args.batch_size,
    )

