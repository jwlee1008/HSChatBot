"""
backend/auth/security.py

비밀번호 해싱, 세션 토큰 난수 생성 및 사용자명 정규화 모듈.
bcrypt 72바이트 제한을 극복하고 임의 길이의 유니코드 비밀번호를 안전하게 처리하기 위해
SHA-256 사전 해싱(Pre-hashing) 후 bcrypt를 적용한다.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

import bcrypt


def hash_password(password: str) -> str:
    """비밀번호를 SHA-256 사전 해싱 후 bcrypt로 해싱한다.

    긴 유니코드(한글 등)가 72바이트를 초과하여도 잘림(truncation)이나 예외 없이 안전하게 처리된다.
    """
    prehash = hashlib.sha256(password.encode("utf-8")).digest()
    return bcrypt.hashpw(prehash, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed_password: str) -> bool:
    """입력 비밀번호와 저장된 bcrypt 해시를 안전하게 대조 검증한다."""
    try:
        prehash = hashlib.sha256(password.encode("utf-8")).digest()
        return bcrypt.checkpw(prehash, hashed_password.encode("ascii"))
    except Exception:
        return False


def generate_session_token() -> str:
    """암호학적으로 안전한 256비트 난수 Opaque 세션 토큰을 생성한다."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """세션 토큰의 SHA-256 hex digest를 계산한다 (DB에는 원문이 아닌 해시만 저장)."""
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError:
        token_bytes = token.encode("utf-8", errors="replace")
    return hashlib.sha256(token_bytes).hexdigest()


def normalize_username(username: str) -> str:
    """사용자명의 앞뒤 공백을 제거하고 소문자로 정규화한다."""
    return username.strip().lower()


def get_current_utc() -> datetime:
    """현재 UTC 시각을 반환한다 (테스트 및 모의 시계 주입 지원)."""
    return datetime.now(timezone.utc)
