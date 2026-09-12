"""
CampusRAG 데이터 적재 스크립트

샘플 공지사항 JSON 데이터를 Chroma DB에 임베딩하여 적재한다.

사용법:
    python scripts/ingest.py
    python scripts/ingest.py --json-path data/sample_notices.json
"""

import argparse
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.embedder import ingest_to_chroma, load_notices_from_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="공지사항 데이터를 Chroma DB에 적재합니다."
    )
    parser.add_argument(
        "--json-path",
        type=str,
        default=config.SAMPLE_NOTICES_PATH,
        help="공지사항 JSON 파일 경로",
    )
    parser.add_argument(
        "--persist-dir",
        type=str,
        default=config.CHROMA_PERSIST_DIR,
        help="Chroma DB 영속화 디렉토리",
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("CampusRAG 데이터 적재 시작")
    logger.info("=" * 50)
    logger.info("JSON 경로: %s", args.json_path)
    logger.info("Chroma DB 경로: %s", args.persist_dir)

    # 1. JSON에서 공지사항 로드
    documents = load_notices_from_json(args.json_path)
    logger.info("로드된 공지사항: %d건", len(documents))

    # 2. Chroma DB에 적재
    vectorstore = ingest_to_chroma(documents, persist_directory=args.persist_dir)

    # 3. 적재 결과 검증
    collection = vectorstore._collection
    count = collection.count()
    logger.info("=" * 50)
    logger.info("✅ 적재 완료: Chroma DB에 %d건 저장됨", count)
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
