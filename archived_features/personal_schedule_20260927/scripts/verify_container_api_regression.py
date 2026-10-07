"""In-container core API regression suite for CampusMate.

Runs inside the Docker container using only the image's installed Python packages
(FastAPI, TestClient, pydantic, sqlite3, etc.) without requiring external pytest or Playwright.
Uses an isolated temporary SQLite database and never modifies repository data.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_tests() -> int:
    print("=" * 60)
    print("CampusMate In-Container Core API Regression Suite")
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform} / {os.uname().machine}")
    print("=" * 60)

    passed_count = 0
    failed_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "container_test.db"
        os.environ["AUTH_DB_PATH"] = str(test_db)
        os.environ["PREWARM_RAG_ON_STARTUP"] = "false"

        # Import modules after setting environment
        import config
        config.AUTH_DB_PATH = str(test_db)
        config.PREWARM_RAG_ON_STARTUP = False

        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.db.migrations import init_db
        from backend.schedules.extraction import extract_schedule_candidates
        from scripts.build_unified_dataset import parse_iso_datetime
        from scripts.sqlite_snapshot import snapshot

        init_db(test_db)

        client = TestClient(app)
        client.__enter__()

        def check(desc: str, func):
            nonlocal passed_count, failed_count
            try:
                func()
                print(f"[PASS] {desc}")
                passed_count += 1
            except Exception as e:
                print(f"[FAIL] {desc}: {e}")
                failed_count += 1

        # 1. Health check
        def test_health():
            res = client.get("/health")
            assert res.status_code == 200, f"Status: {res.status_code}"
            data = res.json()
            assert data["status"] == "ok"
            assert "llm_provider" in data and "doc_count" in data
        check("1. GET /health contract", test_health)

        # 2. Auth lifecycle & validation
        user_a = {"username": "container_user_a", "password": "Password123!"}
        user_b = {"username": "container_user_b", "password": "Password456!"}
        tokens = {}

        def test_auth_registration():
            res = client.post("/api/v1/auth/register", json=user_a)
            assert res.status_code == 201
            assert res.json()["username"] == user_a["username"]

            # Duplicate registration rejected
            res_dup = client.post("/api/v1/auth/register", json=user_a)
            assert res_dup.status_code == 409

            # Register user B
            res_b = client.post("/api/v1/auth/register", json=user_b)
            assert res_b.status_code == 201
        check("2. Auth registration and duplicate rejection", test_auth_registration)

        def test_auth_login():
            res = client.post("/api/v1/auth/login", json=user_a)
            assert res.status_code == 200
            tokens["a"] = res.json()["access_token"]

            res_b = client.post("/api/v1/auth/login", json=user_b)
            assert res_b.status_code == 200
            tokens["b"] = res_b.json()["access_token"]

            # Wrong password rejected
            res_fail = client.post("/api/v1/auth/login", json={"username": user_a["username"], "password": "wrong"})
            assert res_fail.status_code == 401
        check("3. Auth login and invalid password rejection", test_auth_login)

        def test_auth_me():
            headers = {"Authorization": f"Bearer {tokens['a']}"}
            res = client.get("/api/v1/auth/me", headers=headers)
            assert res.status_code == 200
            assert res.json()["username"] == user_a["username"]
        check("4. GET /api/v1/auth/me session resolution", test_auth_me)

        # 3. Schedule CRUD & BOLA isolation
        sched_id = None
        orig_end_datetime = None

        def test_schedule_create_and_precision():
            nonlocal sched_id, orig_end_datetime
            headers = {"Authorization": f"Bearer {tokens['a']}"}
            payload = {
                "title": "Container Docker Precision Test",
                "schedule_kind": "TIME_CONFIRMED_DEADLINE",
                "end_date": "2027-11-20",
                "end_datetime": "2027-11-20T18:00:45.123456+09:00",
                "confirmed": True,
            }
            res = client.post("/api/v1/schedules", json=payload, headers=headers)
            assert res.status_code == 201, res.text
            created = res.json()
            assert "123456" in created["end_datetime"], f"Microseconds lost: {created['end_datetime']}"
            assert created["schedule_kind"] == "TIME_CONFIRMED_DEADLINE"
            sched_id = created["id"]
            orig_end_datetime = created["end_datetime"]
        check("5. POST /api/v1/schedules with microsecond precision", test_schedule_create_and_precision)

        def test_schedule_bola_isolation():
            # User B attempts to access User A's schedule
            headers_b = {"Authorization": f"Bearer {tokens['b']}"}
            res_get = client.get(f"/api/v1/schedules/{sched_id}", headers=headers_b)
            assert res_get.status_code == 404, f"BOLA violation on GET: {res_get.status_code}"

            res_patch = client.patch(f"/api/v1/schedules/{sched_id}", json={"title": "Hacked", "confirmed": True}, headers=headers_b)
            assert res_patch.status_code == 404, f"BOLA violation on PATCH: {res_patch.status_code}"

            res_del = client.delete(f"/api/v1/schedules/{sched_id}", headers=headers_b)
            assert res_del.status_code == 404, f"BOLA violation on DELETE: {res_del.status_code}"
        check("6. Schedule BOLA multi-user isolation (404 enforced)", test_schedule_bola_isolation)

        def test_schedule_patch_atomic_precision():
            headers = {"Authorization": f"Bearer {tokens['a']}"}
            patch_payload = {
                "title": "Container Docker Precision Test - Patched",
                "confirmed": True,
            }
            res = client.patch(f"/api/v1/schedules/{sched_id}", json=patch_payload, headers=headers)
            assert res.status_code == 200
            patched = res.json()
            assert patched["title"] == patch_payload["title"]
            assert patched["end_datetime"] == orig_end_datetime, "Microseconds corrupted on patch"
        check("7. PATCH /api/v1/schedules preserves untouched microsecond datetime", test_schedule_patch_atomic_precision)

        def test_schedule_delete_and_list():
            headers = {"Authorization": f"Bearer {tokens['a']}"}
            res_del = client.delete(f"/api/v1/schedules/{sched_id}", headers=headers)
            assert res_del.status_code == 204

            res_list = client.get("/api/v1/schedules", headers=headers)
            assert res_list.status_code == 200
            assert res_list.json()["total"] == 0
        check("8. DELETE /api/v1/schedules and verify empty list", test_schedule_delete_and_list)

        # 4. Schedule extraction & date parsing
        def test_schedule_extraction_logic():
            sample_text = "중간고사 기간: 2026.10.19 ~ 2026.10.24"
            resp = extract_schedule_candidates(sample_text, reference_time="2026-09-25T10:00:00+09:00")
            assert resp.total_candidates >= 1
            cand = resp.candidates[0]
            assert cand.start_date == "2026-10-19"
            assert cand.end_date == "2026-10-24"
            assert cand.source_quote in sample_text
        check("9. Schedule extraction logic & candidate grounding", test_schedule_extraction_logic)

        def test_date_parsing_logic():
            assert parse_iso_datetime("2026-09-23") is not None
            assert parse_iso_datetime("2026.09.23") is not None
            assert parse_iso_datetime("invalid") is None
            assert parse_iso_datetime("2026-02-30") is None
            assert parse_iso_datetime("2026.09.23garbage") is None
        check("10. Date parsing & strict calendar rejection", test_date_parsing_logic)

        # 5. SQLite snapshot API verification
        def test_snapshot_backup():
            backup_file = Path(tmp_dir) / "snapshot.db"
            snapshot(test_db, backup_file)
            assert backup_file.is_file()
            assert backup_file.stat().st_size > 0

            # Overwrite rejected
            try:
                snapshot(test_db, backup_file)
                raise AssertionError("Should reject overwrite")
            except FileExistsError:
                pass
        check("11. SQLite snapshot WAL backup and overwrite protection", test_snapshot_backup)

        client.__exit__(None, None, None)

    print("=" * 60)
    print(f"Results: {passed_count} passed, {failed_count} failed")
    print("=" * 60)
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
