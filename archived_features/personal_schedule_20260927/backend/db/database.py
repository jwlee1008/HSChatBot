"""
backend/db/database.py

SQLite 영속 저장소 연결 관리 및 FastAPI 의존성 모듈.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

import config


def get_db_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """SQLite 데이터베이스 연결을 생성하고 외래키 및 Row 팩토리를 설정하여 반환한다."""
    path = Path(db_path or config.AUTH_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        check_same_thread=False,
        timeout=30.0,
        isolation_level=None,  # autocommit mode; 명시적 트랜잭션 conn.execute("BEGIN") 지원
    )
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI 엔드포인트용 DB 세션 의존성.

    각 요청마다 새로운 커넥션을 열고 요청 종료 시 안전하게 닫는다.
    테스트 환경에서는 app.dependency_overrides[get_db]를 통해 임시 DB 커넥션으로 대체 가능하다.
    """
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()
