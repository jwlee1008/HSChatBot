"""
backend/db/migrations.py

버전 관리형 SQLite 스키마 마이그레이션 모듈.
임의의 drop/reset 없이 기존 데이터를 보존하며 안전하게 초기화 및 업그레이드를 수행한다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.db.database import get_db_connection

logger = logging.getLogger(__name__)

# 마이그레이션 정의 (순차 버전별 SQL 목록)
MIGRATIONS = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        """,
    ],
    2: [
        """
        CREATE TABLE IF NOT EXISTS personal_schedules (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            course_name TEXT,
            schedule_kind TEXT NOT NULL,
            is_all_day INTEGER NOT NULL,
            is_time_confirmed INTEGER NOT NULL,
            start_date TEXT,
            end_date TEXT,
            start_datetime TEXT,
            end_datetime TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
            source_url TEXT,
            source_title TEXT,
            extracted_quote TEXT,
            is_completed INTEGER NOT NULL DEFAULT 0,
            priority TEXT NOT NULL DEFAULT 'MEDIUM',
            user_confirmed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (is_all_day IN (0, 1)),
            CHECK (is_time_confirmed IN (0, 1)),
            CHECK (is_completed IN (0, 1)),
            CHECK (priority IN ('HIGH', 'MEDIUM', 'LOW')),
            CHECK (timezone = 'Asia/Seoul'),
            CHECK (schedule_kind IN (
                'ALL_DAY_EVENT',
                'DATE_ONLY_DEADLINE',
                'TIME_CONFIRMED_DEADLINE',
                'TIME_CONFIRMED_EVENT',
                'SINGLE_POINT_APPOINTMENT'
            ))
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_schedules_user_id ON personal_schedules(user_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_schedules_dates ON personal_schedules(user_id, start_date, end_date);
        """,
    ],
}


def get_applied_versions(conn: sqlite3.Connection) -> set[int]:
    """이미 적용된 마이그레이션 버전 집합을 반환한다."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
    return {row["version"] for row in cursor.fetchall()}


def run_migrations(conn: sqlite3.Connection) -> int:
    """미적용된 마이그레이션을 순차 적용하고 새로 적용된 버전 수를 반환한다."""
    applied = get_applied_versions(conn)
    applied_count = 0

    for version in sorted(MIGRATIONS.keys()):
        if version in applied:
            continue

        logger.info("마이그레이션 v%d 적용 중...", version)
        conn.execute("BEGIN IMMEDIATE;")
        try:
            for sql in MIGRATIONS[version]:
                conn.execute(sql)

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                (version, now_iso),
            )
            conn.execute("COMMIT;")
            applied_count += 1
            logger.info("마이그레이션 v%d 적용 완료", version)
        except Exception as e:
            conn.execute("ROLLBACK;")
            logger.error("마이그레이션 v%d 실패: %s", version, e)
            raise

    return applied_count


def init_db(db_path: str | Path | None = None) -> int:
    """데이터베이스를 초기화하고 필요한 마이그레이션을 적용한다.

    반복 실행해도 기존 데이터를 보존한다 (Idempotent).
    """
    conn = get_db_connection(db_path)
    try:
        return run_migrations(conn)
    finally:
        conn.close()
