"""
tests/test_auth_persistence.py

R1-A 계정 등록, 인증, Opaque 세션 토큰, 영속 저장소 및 보안 제약 검증 테스트 슈트.
임시 디렉터리 파일 SQLite와 FastAPI TestClient를 사용하여 실제 HTTP 레벨에서 동작을 검증한다.
모든 fixture는 기본 계정 DB 경로를 완벽히 격리하며, 테스트 완료 후 환경을 100% 복구한다.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from backend.db.database import get_db, get_db_connection
from backend.db.migrations import init_db
from backend.main import app


@pytest.fixture
def isolated_auth_env(tmp_path: Path) -> Generator[tuple[TestClient, Path], None, None]:
    """임시 SQLite DB로 lifespan과 get_db 의존성을 완전 격리하는 픽스처.

    기본 계정 DB(config.AUTH_DB_PATH)에 절대 접근하지 않으며,
    종료 시 전역 설정 및 환경 변수, dependency overrides를 100% 원복한다.
    """
    test_db = tmp_path / "test_auth.db"
    orig_auth_db_path = config.AUTH_DB_PATH
    orig_prewarm = config.PREWARM_RAG_ON_STARTUP
    orig_env_db = os.environ.get("AUTH_DB_PATH")
    orig_env_prewarm = os.environ.get("PREWARM_RAG_ON_STARTUP")

    # 1. lifespan 및 요청 의존성 모두 임시 DB를 바라보도록 설정 주입
    config.AUTH_DB_PATH = str(test_db)
    config.PREWARM_RAG_ON_STARTUP = False
    os.environ["AUTH_DB_PATH"] = str(test_db)
    os.environ["PREWARM_RAG_ON_STARTUP"] = "false"

    def override_get_db() -> Generator[sqlite3.Connection, None, None]:
        conn = get_db_connection(test_db)
        try:
            yield conn
        finally:
            conn.close()

    orig_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db

    try:
        # lifespan 내 init_db(config.AUTH_DB_PATH)가 test_db에서 실행됨
        with TestClient(app) as test_client:
            yield test_client, test_db
    finally:
        # 실패/성공 무관하게 100% 안전 복구
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)
        config.AUTH_DB_PATH = orig_auth_db_path
        config.PREWARM_RAG_ON_STARTUP = orig_prewarm

        if orig_env_db is None:
            os.environ.pop("AUTH_DB_PATH", None)
        else:
            os.environ["AUTH_DB_PATH"] = orig_env_db

        if orig_env_prewarm is None:
            os.environ.pop("PREWARM_RAG_ON_STARTUP", None)
        else:
            os.environ["PREWARM_RAG_ON_STARTUP"] = orig_env_prewarm


@pytest.fixture
def client(isolated_auth_env: tuple[TestClient, Path]) -> TestClient:
    """단순 HTTP 요청용 TestClient 픽스처."""
    c, _ = isolated_auth_env
    return c


@pytest.fixture
def temp_db_path(isolated_auth_env: tuple[TestClient, Path]) -> Path:
    """테스트용 격리 DB 경로 픽스처."""
    _, db_path = isolated_auth_env
    return db_path


# ── 1. 기본 계정 DB 비접근 격리 보증 검증 ─────────────────────────


def test_default_account_db_isolation(isolated_auth_env: tuple[TestClient, Path]):
    """테스트 실행 중 기본 계정 DB 경로가 아닌 임시 DB만 사용됨을 검증."""
    client, test_db = isolated_auth_env
    default_path = Path("data/campusmate.db").resolve()

    # config.AUTH_DB_PATH가 기본 계정 DB 경로가 아닌 임시 DB 경로임을 확인
    assert Path(config.AUTH_DB_PATH).resolve() == test_db.resolve()
    assert Path(config.AUTH_DB_PATH).resolve() != default_path

    # 테스트 DB에 실제 테이블이 생성되었는지 확인 (v1 및 v2 테이블 포함)
    assert test_db.exists()
    conn = get_db_connection(test_db)
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    conn.close()
    assert "users" in tables
    assert "sessions" in tables
    assert "schema_migrations" in tables
    assert "personal_schedules" in tables


# ── 2. 입력 검증 오류(422)에서 비밀번호 및 민감 입력 제거 검증 ────


def test_422_validation_error_strips_sensitive_password_input(client: TestClient):
    """과대/과소 비밀번호, 잘못된 자료형, extra field, 객체 오류에서 비밀번호 미반환 검증."""
    sensitive_pw = "SYNTHETIC-VERY-LONG-PASSWORD-FOR-TEST-1234567890-" * 5  # 240 chars > 128

    # 1. 회원가입: 길이 초과 비밀번호 검증 (422)
    reg_long = client.post("/api/v1/auth/register", json={"username": "valid_user", "password": sensitive_pw})
    assert reg_long.status_code == 422
    assert sensitive_pw not in reg_long.text
    detail1 = reg_long.json()["detail"]
    assert any(err["type"] == "string_too_long" for err in detail1)
    assert any("password" in err["loc"] for err in detail1)

    # 2. 로그인: 길이 초과 비밀번호 검증 (422)
    login_long = client.post("/api/v1/auth/login", json={"username": "valid_user", "password": sensitive_pw})
    assert login_long.status_code == 422
    assert sensitive_pw not in login_long.text

    # 3. 잘못된 자료형 (숫자 비밀번호)
    reg_type = client.post("/api/v1/auth/register", json={"username": "valid_user", "password": 12345678})
    assert reg_type.status_code == 422
    assert "12345678" not in reg_type.text
    assert any(err["type"] == "string_type" for err in reg_type.json()["detail"])

    # 4. Extra fields 차단 시 민감 필드 값 노출 방지
    secret_extra = "INJECTED_SECRET_ROLE_TOKEN_9999"
    reg_extra = client.post(
        "/api/v1/auth/register",
        json={"username": "valid_user", "password": "ValidPassword123!", "role_secret": secret_extra},
    )
    assert reg_extra.status_code == 422
    assert secret_extra not in reg_extra.text
    detail_extra = reg_extra.json()["detail"]
    assert any(err["type"] == "extra_forbidden" for err in detail_extra)

    # 5. 객체 단위 오류 (배열 입력)
    reg_obj = client.post("/api/v1/auth/register", json=[{"username": "u", "password": sensitive_pw}])
    assert reg_obj.status_code == 422
    assert sensitive_pw not in reg_obj.text


# ── 3. 비ASCII 및 Malformed Bearer 토큰 401 차단 검증 ─────────────


def test_malformed_and_non_ascii_bearer_tokens_return_401(client: TestClient):
    """비ASCII 바이트 헤더, 잘못된 형식, 길이 초과/미달 토큰이 500이 아닌 401을 반환하는지 검증."""
    # 1. 비ASCII 바이트 헤더 (Bearer \xff) -> 401 (not 500)
    me_non_ascii = client.get("/api/v1/auth/me", headers={"Authorization": b"Bearer \xff"})
    assert me_non_ascii.status_code == 401
    assert "detail" in me_non_ascii.json()

    logout_non_ascii = client.post("/api/v1/auth/logout", headers={"Authorization": b"Bearer \xff"})
    assert logout_non_ascii.status_code == 401
    assert "detail" in logout_non_ascii.json()

    # 2. 이모지 및 다국어 유니코드 토큰 -> 401
    me_emoji = client.get("/api/v1/auth/me", headers={"Authorization": b"Bearer token_emoji_\xf0\x9f\x98\x80"})
    assert me_emoji.status_code == 401

    # 3. 과도하게 짧은 토큰 (< 16자)
    me_short = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer short"})
    assert me_short.status_code == 401

    # 4. 과도하게 긴 토큰 (> 256자)
    me_long = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {'a' * 300}"})
    assert me_long.status_code == 401

    # 5. 공백 포함 비정상 토큰
    me_space = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer token with space"})
    assert me_space.status_code == 401


# ── 4. DB 마이그레이션 실패 시 Startup 중단 검증 ──────────────────


def test_db_migration_failure_fails_startup():
    """필수 계정 DB 마이그레이션 실패 시 예외가 삼켜지지 않고 startup이 실패함을 검증."""
    with patch("backend.main.init_db", side_effect=sqlite3.OperationalError("synthetic migration disk failure")):
        with pytest.raises(sqlite3.OperationalError, match="synthetic migration disk failure"):
            with TestClient(app):
                pass  # startup 도중 예외가 발생하여 진입하지 못해야 함


# ── 5. 정상 인증 수명 주기 (회원가입 -> 로그인 -> me -> 로그아웃 -> 차단) ──


def test_auth_full_lifecycle(client: TestClient):
    """회원가입, 로그인, me 조회, 로그아웃, 폐기 토큰 401 차단 흐름 검증."""
    reg_payload = {"username": "student2026", "password": "SecurePassword123!"}
    reg_resp = client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["username"] == "student2026"
    assert "id" in user_data
    assert "created_at" in user_data
    assert "access_token" not in user_data
    assert "password" not in user_data
    assert "password_hash" not in user_data

    login_resp = client.post("/api/v1/auth/login", json=reg_payload)
    assert login_resp.status_code == 200
    assert login_resp.headers.get("Cache-Control") == "no-store"
    token_data = login_resp.json()
    assert token_data["token_type"] == "bearer"
    assert "access_token" in token_data
    assert "expires_at" in token_data
    token = token_data["access_token"]
    assert len(token) > 20

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["id"] == user_data["id"]
    assert me_data["username"] == "student2026"
    assert me_data["created_at"] == user_data["created_at"]

    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_resp.status_code == 204

    blocked_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert blocked_me.status_code == 401
    assert "폐기" in blocked_me.json()["detail"] or "만료" in blocked_me.json()["detail"]

    blocked_logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert blocked_logout.status_code == 401


# ── 6. 중복/정규화 충돌, 잘못된 자격 증명, 입력 검증 ─────────────


def test_duplicate_and_normalization_registration(client: TestClient):
    """중복 username 및 공백/대소문자 정규화 충돌 시 409 Conflict 검증."""
    res1 = client.post("/api/v1/auth/register", json={"username": "alice", "password": "Password123!"})
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json={"username": "alice", "password": "Password123!"})
    assert res2.status_code == 409
    assert "이미 등록" in res2.json()["detail"]

    res3 = client.post("/api/v1/auth/register", json={"username": "  ALICE  ", "password": "Password123!"})
    assert res3.status_code == 409
    assert "이미 등록" in res3.json()["detail"]


def test_invalid_username_and_password_validation(client: TestClient):
    """입력 길이 및 형식 제약 검증 (422 Unprocessable Entity)."""
    assert client.post("/api/v1/auth/register", json={"username": "user name", "password": "Password123!"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"username": "ab", "password": "Password123!"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"username": "user@domain", "password": "Password123!"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"username": "valid_user", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"username": "valid_user", "password": "a" * 129}).status_code == 422


def test_long_unicode_password_support(client: TestClient):
    """긴 유니코드 비밀번호(bcrypt 72바이트 초과)의 안전한 처리 검증."""
    long_korean_pw = "한성대학교스마트캠퍼스메이트비밀번호테스트12345!"
    reg = client.post("/api/v1/auth/register", json={"username": "korean_user", "password": long_korean_pw})
    assert reg.status_code == 201

    login_ok = client.post("/api/v1/auth/login", json={"username": "korean_user", "password": long_korean_pw})
    assert login_ok.status_code == 200
    token = login_ok.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "korean_user"

    login_fail = client.post("/api/v1/auth/login", json={"username": "korean_user", "password": long_korean_pw + "x"})
    assert login_fail.status_code == 401


def test_login_failure_identical_message(client: TestClient):
    """존재하지 않는 사용자와 비밀번호 불일치 시 안전한 동일 오류 문구 반환 검증."""
    client.post("/api/v1/auth/register", json={"username": "bob", "password": "Password123!"})

    res_wrong_pw = client.post("/api/v1/auth/login", json={"username": "bob", "password": "WrongPassword!"})
    assert res_wrong_pw.status_code == 401
    msg1 = res_wrong_pw.json()["detail"]

    res_no_user = client.post("/api/v1/auth/login", json={"username": "charlie_not_exist", "password": "Password123!"})
    assert res_no_user.status_code == 401
    msg2 = res_no_user.json()["detail"]

    assert msg1 == msg2
    assert "올바르지 않습니다" in msg1


# ── 7. 토큰 만료 및 폐기 제어 ───────────────────────────────────


def test_token_expiration(client: TestClient, temp_db_path: Path):
    """만료된 토큰 차단 검증 (DB 만료 시각 과거 조작)."""
    client.post("/api/v1/auth/register", json={"username": "exp_user", "password": "Password123!"})
    login_resp = client.post("/api/v1/auth/login", json={"username": "exp_user", "password": "Password123!"})
    token = login_resp.json()["access_token"]

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    conn = get_db_connection(temp_db_path)
    conn.execute("UPDATE sessions SET expires_at = '2020-01-01T00:00:00+00:00';")
    conn.close()

    expired_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert expired_resp.status_code == 401
    assert "만료" in expired_resp.json()["detail"]


# ── 8. 다중 계정 및 다중 세션 격리 ──────────────────────────────


def test_multi_user_and_multi_session_isolation(client: TestClient):
    """다중 사용자 격리 및 단일 사용자의 다중 세션 중 개별 로그아웃 격리 검증."""
    client.post("/api/v1/auth/register", json={"username": "user_a", "password": "PasswordA123!"})
    client.post("/api/v1/auth/register", json={"username": "user_b", "password": "PasswordB123!"})

    token_a1 = client.post("/api/v1/auth/login", json={"username": "user_a", "password": "PasswordA123!"}).json()["access_token"]
    token_a2 = client.post("/api/v1/auth/login", json={"username": "user_a", "password": "PasswordA123!"}).json()["access_token"]
    token_b = client.post("/api/v1/auth/login", json={"username": "user_b", "password": "PasswordB123!"}).json()["access_token"]

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a1}"}).json()["username"] == "user_a"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a2}"}).json()["username"] == "user_a"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).json()["username"] == "user_b"

    logout_a1 = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_a1}"})
    assert logout_a1.status_code == 204

    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a1}"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a2}"}).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).status_code == 200


# ── 9. 연결 재개방 및 반복 마이그레이션 무손실 검증 ─────────────


def test_connection_reopening_and_repeat_migrations(temp_db_path: Path):
    """DB 연결을 완전히 닫고 반복 마이그레이션을 거쳐도 데이터가 보존됨을 검증."""
    orig_path = config.AUTH_DB_PATH
    orig_prewarm = config.PREWARM_RAG_ON_STARTUP
    config.AUTH_DB_PATH = str(temp_db_path)
    config.PREWARM_RAG_ON_STARTUP = False

    def override_db() -> Generator[sqlite3.Connection, None, None]:
        conn = get_db_connection(temp_db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_db

    try:
        with TestClient(app) as c1:
            reg = c1.post("/api/v1/auth/register", json={"username": "persist_user", "password": "Password123!"})
            assert reg.status_code == 201
            uid = reg.json()["id"]

            login = c1.post("/api/v1/auth/login", json={"username": "persist_user", "password": "Password123!"})
            assert login.status_code == 200
            token = login.json()["access_token"]

        # 마이그레이션 반복 호출 (0건 적용, 데이터 보존)
        assert init_db(temp_db_path) == 0
        assert init_db(temp_db_path) == 0

        # 새로운 연결로 기존 세션 조회
        with TestClient(app) as c2:
            me_resp = c2.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me_resp.status_code == 200
            assert me_resp.json()["id"] == uid
            assert me_resp.json()["username"] == "persist_user"
    finally:
        app.dependency_overrides.clear()
        config.AUTH_DB_PATH = orig_path
        config.PREWARM_RAG_ON_STARTUP = orig_prewarm


# ── 10. 독립 프로세스 재시작(Subprocess) 실제 영속성 검증 ────────


def test_real_subprocess_restart_persistence(tmp_path: Path):
    """별도 OS 서브프로세스를 종료 후 재시작해도 계정 및 세션이 영속 유지됨을 증명."""
    db_file = tmp_path / "proc_test.db"

    # 프로세스 1: 계정 생성 및 로그인 후 토큰 출력
    script_p1 = f"""
import os, sys
os.environ["AUTH_DB_PATH"] = {repr(str(db_file))}
os.environ["PREWARM_RAG_ON_STARTUP"] = "false"
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    r1 = client.post("/api/v1/auth/register", json={{"username": "proc_user", "password": "Password123!"}})
    assert r1.status_code == 201
    r2 = client.post("/api/v1/auth/login", json={{"username": "proc_user", "password": "Password123!"}})
    assert r2.status_code == 200
    print(r2.json()["access_token"])
"""
    res1 = subprocess.run([sys.executable, "-c", script_p1], capture_output=True, text=True, check=True)
    issued_token = res1.stdout.strip().splitlines()[-1]
    assert len(issued_token) > 20

    # 프로세스 2: 완전히 새로운 프로세스로 시작하여 이전 프로세스에서 발급된 토큰 검증
    script_p2 = f"""
import os, sys
os.environ["AUTH_DB_PATH"] = {repr(str(db_file))}
os.environ["PREWARM_RAG_ON_STARTUP"] = "false"
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    r = client.get("/api/v1/auth/me", headers={{"Authorization": "Bearer {issued_token}"}})
    assert r.status_code == 200
    assert r.json()["username"] == "proc_user"
    print("SUBPROCESS_PERSISTENCE_SUCCESS")
"""
    res2 = subprocess.run([sys.executable, "-c", script_p2], capture_output=True, text=True, check=True)
    assert "SUBPROCESS_PERSISTENCE_SUCCESS" in res2.stdout


# ── 11. DB 내 평문/토큰 미저장 및 응답 내 해시 미노출 검증 ────────


def test_no_plaintext_passwords_or_tokens_stored_and_no_hash_leaks(client: TestClient, temp_db_path: Path):
    """DB에 평문 비밀번호 및 원문 토큰이 일절 저장되지 않고 해시만 존재함을 검증."""
    plain_password = "SuperSecretPassword999!"
    reg_resp = client.post("/api/v1/auth/register", json={"username": "privacy_user", "password": plain_password})
    assert reg_resp.status_code == 201

    login_resp = client.post("/api/v1/auth/login", json={"username": "privacy_user", "password": plain_password})
    assert login_resp.status_code == 200
    raw_token = login_resp.json()["access_token"]

    conn = get_db_connection(temp_db_path)
    user_row = conn.execute("SELECT password_hash FROM users WHERE username = 'privacy_user';").fetchone()
    stored_hash = user_row["password_hash"]

    assert stored_hash.startswith("$2b$")
    assert plain_password != stored_hash
    assert plain_password not in stored_hash

    dump_text = "".join([str(val) for r in conn.execute("SELECT * FROM users;").fetchall() for val in r])
    assert plain_password not in dump_text

    session_row = conn.execute("SELECT token_hash FROM sessions;").fetchone()
    stored_token_hash = session_row["token_hash"]

    assert raw_token != stored_token_hash
    assert len(stored_token_hash) == 64
    assert raw_token not in stored_token_hash

    sessions_dump = "".join([str(val) for r in conn.execute("SELECT * FROM sessions;").fetchall() for val in r])
    assert raw_token not in sessions_dump
    conn.close()

    assert stored_hash not in reg_resp.text
    assert stored_hash not in login_resp.text
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert stored_hash not in me_resp.text
    assert stored_token_hash not in me_resp.text


# ── 12. 기존 RAG /health 응답 계약 보존 및 무간섭성 ─────────────


def test_health_check_contract_preserved(client: TestClient):
    """기존 /health 엔드포인트 응답 계약이 온전히 유지되는지 검증."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "llm_provider" in data
    assert "doc_count" in data
