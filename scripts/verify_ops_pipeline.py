"""
CampusRAG 최소 운영 파이프라인 무결성 검증 도구

[검증 범위]
격리 DB 적재와 프로세스 내부 검색 검증 (실제 서버 재시작·HTTP 검증 미포함)

운영 DB(data/chroma_db) 및 기존 디렉터리를 절대 삭제·수정하지 않고,
이번 실행 전용으로 생성된 격리 임시 디렉터리에서:
1. 검증 완료된 JSON 준비 (data/crawled_notices.json)
2. 격리된 임시 Chroma DB 생성 (core.embedder.ingest_to_chroma)
3. 무결성 및 해시 동기화 진단 (check_data_status.inspect_data_status)
4. 프로세스 내부 설정(CHROMA_PERSIST_DIR) 전환 및 RAG 검색 파이프라인 검증
   (실제 uvicorn/streamlit 서버 프로세스 재시작 및 외부 HTTP 검증은 포함되지 않음)
을 안전하게 수행합니다.
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 프로젝트 루트 sys.path 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.embedder import ingest_to_chroma, load_notices_from_json
from scripts.check_data_status import inspect_data_status


def verify_ops_pipeline(
    json_path: str = "data/crawled_notices.json",
    temp_db_path: str | None = None,
    cleanup: bool = True,
) -> bool:
    """
    격리 DB 적재와 프로세스 내부 검색 검증 (실제 서버 재시작·HTTP 검증 미포함)

    안전 방어 원칙:
    - 운영 DB(config.CHROMA_PERSIST_DIR) 경로 지정 시 즉시 거부 (ValueError)
    - 기존에 존재하는 디렉터리/파일 지정 시 삭제하지 않고 즉시 거부 (ValueError)
    - 심볼릭 링크 지정 시 링크 대상 삭제 방지를 위해 즉시 거부 (ValueError)
    - temp_db_path 미지정 시 전용 임시 디렉터리를 새로 생성하며, 이번 실행이 생성한 경로만 정리
    """
    print("=" * 70)
    print("🚀 CampusRAG 최소 운영 파이프라인 검증 (격리 DB 적재와 프로세스 내부 검색 검증)")
    print("   * 주의: 실제 서버 재시작 및 HTTP 검증은 포함되지 않습니다.")
    print("=" * 70)
    print(f"1. 입력 공지 JSON: {json_path}")

    j_path = Path(json_path)
    if not j_path.exists():
        print(f"❌ [실패] 입력 JSON 파일이 존재하지 않습니다: {json_path}")
        return False

    prod_db_path = Path(config.CHROMA_PERSIST_DIR).resolve()
    t_db = None
    created_by_this_run = False

    try:
        # 안전한 대상 디렉터리 결정 및 방어 검사
        if temp_db_path is None:
            data_dir = Path("data")
            base_dir = str(data_dir) if data_dir.is_dir() else None
            created_temp_str = tempfile.mkdtemp(prefix="ops_verify_", dir=base_dir)
            t_db = Path(created_temp_str)
            created_by_this_run = True
            print(f"2. 전용 임시 DB 디렉터리 생성: {t_db} (운영 DB 보호)")
        else:
            t_db = Path(temp_db_path)
            print(f"2. 사용자 지정 임시 DB 경로 검증: {t_db}")

            # 방어 1: 운영 DB 보호
            if t_db.resolve() == prod_db_path:
                raise ValueError(
                    f"보안 거부: 운영 DB 경로({config.CHROMA_PERSIST_DIR})는 검증용 임시 DB로 지정할 수 없습니다."
                )

            # 방어 2: 심볼릭 링크 보호 (심볼릭 링크 대상 삭제 방지)
            if t_db.is_symlink():
                raise ValueError(
                    f"보안 거부: 심볼릭 링크({temp_db_path})는 검증용 임시 DB로 지정할 수 없으며 삭제되지 않습니다."
                )

            # 방어 3: 기존에 이미 존재하는 디렉터리/파일 삭제 방어
            if t_db.exists():
                raise ValueError(
                    f"보안 거부: 기존에 존재하는 경로({temp_db_path})는 삭제하거나 덮어쓸 수 없습니다. "
                    f"새로운 경로를 지정하거나 기본 임시 디렉터리를 사용하세요."
                )

            t_db.mkdir(parents=True, exist_ok=False)
            created_by_this_run = True

        temp_db_str = str(t_db)

        # Step 1: 임시 DB 생성 및 인덱싱
        print("\n[Step 1/4] 임시 Chroma DB에 공지 데이터 인덱싱 중...")
        docs = load_notices_from_json(json_path)
        vectorstore = ingest_to_chroma(
            documents=docs,
            persist_directory=temp_db_str,
            collection_name="ops_verify_notices",
            replace=True,
        )
        ingested_count = vectorstore._collection.count()
        print(f"✅ [성공] 총 {ingested_count}개 청크가 격리 DB에 적재되었습니다.")

        # Step 2: check_data_status 무결성 검증
        print("\n[Step 2/4] check_data_status 해시 기반 동기화 무결성 진단 실행...")
        status_report = inspect_data_status(
            json_path=json_path,
            db_path=temp_db_str,
            collection_name="ops_verify_notices",
            strict=True,
        )
        if not status_report["in_sync"]:
            print(f"❌ [실패] 데이터 무결성 검사 불일치: {status_report['issues']}")
            return False
        print(
            f"✅ [성공] 무결성 검사 통과 (완전 일치: {status_report['matched_in_db_count']}건, 누락: 0건, stale: 0건)"
        )

        # Step 3: 앱 환경변수 전환 및 프로세스 내부 검색 파이프라인 검증
        print("\n[Step 3/4] 프로세스 내부 설정(CHROMA_PERSIST_DIR) 전환 및 검색 파이프라인 검증...")
        print("   (주의: 실제 서버 재시작 및 외부 HTTP 검증은 수행하지 않는 프로세스 내부 검증입니다.)")
        original_db = config.CHROMA_PERSIST_DIR
        original_col = config.CHROMA_COLLECTION_NAME
        try:
            os.environ["CHROMA_PERSIST_DIR"] = temp_db_str
            os.environ["CHROMA_COLLECTION_NAME"] = "ops_verify_notices"
            config.CHROMA_PERSIST_DIR = temp_db_str
            config.CHROMA_COLLECTION_NAME = "ops_verify_notices"

            from core.rag import CampusRAG

            rag = CampusRAG(load_llm=False)
            test_query = "2026학년도 2학기 폐강 강좌 수강신청 정정 기간이 언제야?"
            docs = rag.retrieve(test_query, top_k=2)
            if not docs:
                print("❌ [실패] 격리 DB에서 검색 결과가 반환되지 않았습니다.")
                return False

            top_doc = docs[0]
            print(
                f"✅ [성공] 격리 DB 프로세스 내부 검색 정상 동작! (Top 1: {top_doc.metadata.get('title')[:35]}, 점수: {top_doc.metadata.get('_score', 0):.3f})"
            )
        finally:
            # 환경변수 및 설정 원복
            os.environ["CHROMA_PERSIST_DIR"] = original_db
            os.environ["CHROMA_COLLECTION_NAME"] = original_col
            config.CHROMA_PERSIST_DIR = original_db
            config.CHROMA_COLLECTION_NAME = original_col

        print("\n[Step 4/4] 운영 파이프라인 검증 완료")
        if cleanup and created_by_this_run and t_db.exists():
            print(f"🧹 이번 실행이 생성한 전용 임시 DB 정리 완료: {temp_db_str}")
            shutil.rmtree(t_db, ignore_errors=True)

        print("=" * 70)
        print("🎉 [격리 DB 적재 및 프로세스 내부 검색 검증 완료]")
        print("   수집 JSON -> 임시 DB -> 무결성 검사 -> 프로세스 검색 전 과정 통과!")
        print("   (실제 서버 재시작·HTTP 검증 미포함)")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"❌ [예외 발생] {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        # 이번 실행에서 생성한 전용 경로만 정리하며, 운영 DB나 심볼릭 링크는 절대 건드리지 않음
        if (
            cleanup
            and created_by_this_run
            and t_db is not None
            and t_db.exists()
            and not t_db.is_symlink()
        ):
            if t_db.resolve() != prod_db_path:
                shutil.rmtree(t_db, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="최소 운영 파이프라인 검증 (격리 DB 적재와 프로세스 내부 검색 검증, 실제 서버 재시작·HTTP 검증 미포함)"
    )
    parser.add_argument("--json-path", default="data/crawled_notices.json", help="공지 JSON 경로")
    parser.add_argument(
        "--temp-db-path",
        default=None,
        help="임시 DB 경로 (미지정 시 전용 임시 디렉터리 자동 생성 및 안전 정리)",
    )
    parser.add_argument("--no-cleanup", action="store_true", help="테스트 완료 후 임시 DB 보존")
    args = parser.parse_args()

    try:
        success = verify_ops_pipeline(
            json_path=args.json_path,
            temp_db_path=args.temp_db_path,
            cleanup=not args.no_cleanup,
        )
    except Exception:
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

