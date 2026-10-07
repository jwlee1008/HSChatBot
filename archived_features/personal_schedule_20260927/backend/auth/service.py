"""
backend/auth/service.py

사용자 등록, 로그인 자격 증명 검증, 세션 관리 및 로그아웃 비즈니스 로직 모듈.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

import config
from backend.auth.security import (
    generate_session_token,
    get_current_utc,
    hash_password,
    hash_session_token,
    verify_password,
)
from backend.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

# 무차별 대입 및 타이밍 공격 방지를 위한 더미 bcrypt 해시
_DUMMY_BCRYPT_HASH = "$2b$12$e80yvV8Q0L5Rkn6/Fepk8eJvPqVd1p9w3Z0yvV8Q0L5Rkn6/Fepk8"


class AuthService:
    """계정 등록, 자격 증명 검증 및 Opaque 세션 토큰 수명 주기 관리 서비스."""

    @staticmethod
    def register(conn: sqlite3.Connection, request: UserRegisterRequest) -> UserResponse:
        """새 사용자를 등록한다.

        - 중복 사용자명: 409 Conflict 반환
        - 자동 로그인은 수행하지 않음
        """
        username = request.username
        now_iso = get_current_utc().isoformat()
        user_id = str(uuid.uuid4())
        pw_hash = hash_password(request.password)

        try:
            # 중복 검사
            cursor = conn.execute("SELECT id FROM users WHERE username = ?;", (username,))
            if cursor.fetchone() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="이미 등록된 사용자명입니다.",
                )

            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (user_id, username, pw_hash, now_iso, now_iso),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 등록된 사용자명입니다.",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("회원가입 처리 중 데이터베이스 오류: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="회원가입 처리 중 서버 오류가 발생했습니다.",
            )

        return UserResponse(id=user_id, username=username, created_at=now_iso)

    @staticmethod
    def login(conn: sqlite3.Connection, request: UserLoginRequest) -> TokenResponse:
        """사용자 자격 증명을 검증하고 신규 세션 토큰을 발급한다.

        - 존재하지 않는 사용자명과 잘못된 비밀번호는 동일한 401 오류 문구를 반환
        - 원문 세션 토큰은 클라이언트에 1회 반환되며 DB에는 SHA-256 해시만 저장
        """
        username = request.username
        cursor = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?;",
            (username,),
        )
        user = cursor.fetchone()

        if user is None:
            # 타이밍 차이를 줄이기 위해 더미 검증 수행
            verify_password(request.password, _DUMMY_BCRYPT_HASH)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="사용자명 또는 비밀번호가 올바르지 않습니다.",
            )

        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="사용자명 또는 비밀번호가 올바르지 않습니다.",
            )

        # 새 세션 토큰 생성 및 해싱
        raw_token = generate_session_token()
        token_hash = hash_session_token(raw_token)
        session_id = str(uuid.uuid4())

        now = get_current_utc()
        expires_at = (now + timedelta(seconds=config.SESSION_EXPIRE_SECONDS)).isoformat()
        now_iso = now.isoformat()

        try:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL);
                """,
                (session_id, user["id"], token_hash, now_iso, expires_at),
            )
        except Exception as e:
            logger.error("세션 생성 중 데이터베이스 오류: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="로그인 처리 중 서버 오류가 발생했습니다.",
            )

        return TokenResponse(
            access_token=raw_token,
            token_type="bearer",
            expires_at=expires_at,
        )

    @staticmethod
    def get_user_by_session_token(conn: sqlite3.Connection, token: str) -> dict:
        """세션 토큰을 검증하고 소유 사용자 레코드를 반환한다.

        - 토큰 누락, 변조, 만료, 폐기(`revoked_at`)된 경우 401 Unauthorized 발생
        """
        token_hash = hash_session_token(token)
        cursor = conn.execute(
            """
            SELECT s.id AS session_id, s.user_id, s.expires_at, s.revoked_at,
                   u.username, u.created_at
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token_hash = ?;
            """,
            (token_hash,),
        )
        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않거나 만료된 세션입니다.",
            )

        if row["revoked_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="폐기된 세션입니다.",
            )

        # 만료 시각 검증
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= get_current_utc():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="만료된 세션입니다.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="세션 타임스탬프 오류입니다.",
            )

        return {
            "id": row["user_id"],
            "username": row["username"],
            "created_at": row["created_at"],
            "session_id": row["session_id"],
        }

    @staticmethod
    def logout(conn: sqlite3.Connection, token: str) -> None:
        """현재 세션을 폐기(`revoked_at` 설정)한다.

        - 동일 사용자의 다른 활성 세션은 유지됨
        - 유효하지 않거나 이미 폐기/만료된 토큰은 401 반환
        """
        token_hash = hash_session_token(token)
        cursor = conn.execute(
            "SELECT id, expires_at, revoked_at FROM sessions WHERE token_hash = ?;",
            (token_hash,),
        )
        session = cursor.fetchone()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않거나 만료된 세션입니다.",
            )

        if session["revoked_at"] is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이미 로그아웃된 세션입니다.",
            )

        try:
            expires_at = datetime.fromisoformat(session["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= get_current_utc():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="만료된 세션입니다.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="세션 타임스탬프 오류입니다.",
            )

        now_iso = get_current_utc().isoformat()
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?;",
            (now_iso, token_hash),
        )
