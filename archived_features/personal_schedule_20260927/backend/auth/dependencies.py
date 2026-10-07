"""
backend/auth/dependencies.py

FastAPI 엔드포인트용 인증 종속성(Dependency) 모듈.
R1-B 개인 일정 CRUD 및 모든 인증 보호 엔드포인트에서 current_user를 주입받아 사용할 수 있다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from backend.auth.service import AuthService
from backend.db.database import get_db
from backend.schemas import UserResponse


import re

_BEARER_TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_.~+/-]+=*$")


def extract_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Authorization 헤더에서 Bearer 토큰을 추출하고 형식/문자 유효성을 검증한다."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 헤더가 누락되었습니다.",
        )

    try:
        parts = authorization.strip().split()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="올바른 Bearer 토큰 형식이 아닙니다.",
        )

    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="올바른 Bearer 토큰 형식이 아닙니다.",
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰 값이 비어 있습니다.",
        )

    # 비ASCII 문자, 허용되지 않는 특수문자, 과도하게 짧거나 긴 토큰 차단 (401)
    if not token.isascii() or not (16 <= len(token) <= 256) or not _BEARER_TOKEN_PATTERN.match(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰 형식입니다.",
        )

    return token


def get_current_user(
    token: str = Depends(extract_bearer_token),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """현재 세션 토큰을 검증하고 인증된 사용자 정보를 반환한다.

    반환 형식:
      {"id": "...", "username": "...", "created_at": "...", "session_id": "..."}
    """
    return AuthService.get_user_by_session_token(db, token)
