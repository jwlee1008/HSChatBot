"""
backend/routers/auth.py

계정 등록, 로그인, 현재 사용자 조회 및 로그아웃 REST API 라우터.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Response, status

from backend.auth.dependencies import extract_bearer_token, get_current_user
from backend.auth.service import AuthService
from backend.db.database import get_db
from backend.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["인증 및 계정"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="신규 사용자 회원가입",
)
def register(
    request: UserRegisterRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> UserResponse:
    """새로운 일반 사용자를 등록한다.

    - 중복 ID 등록 시 409 Conflict 반환
    - 등록 성공 시 공개 사용자 정보만 반환하며 자동 로그인은 수행하지 않음
    """
    return AuthService.register(db, request)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="사용자 로그인 및 세션 토큰 발급",
)
def login(
    request: UserLoginRequest,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
) -> TokenResponse:
    """사용자 자격 증명을 검증하고 Opaque Bearer 세션 토큰을 발급한다.

    - 토큰 응답에 Cache-Control: no-store 헤더 적용
    - 인증 실패 시 안전한 일관 401 오류 반환
    """
    token_resp = AuthService.login(db, request)
    response.headers["Cache-Control"] = "no-store"
    return token_resp


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="현재 로그인 사용자 본인 정보 조회",
)
def get_me(
    current_user: dict = Depends(get_current_user),
) -> UserResponse:
    """유효한 Bearer 세션 토큰을 통해 본인의 공개 계정 정보를 조회한다."""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        created_at=current_user["created_at"],
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="현재 세션 로그아웃 (세션 폐기)",
)
def logout(
    token: str = Depends(extract_bearer_token),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    """현재 세션 토큰을 폐기한다.

    - 204 No Content 반환
    - 동일 사용자의 다른 활성 세션은 유지됨
    """
    AuthService.logout(db, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
