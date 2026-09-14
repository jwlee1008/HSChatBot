"""
CampusRAG 데이터 파이프라인 무결성 및 해시 기반 상태 진단 단위 테스트
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.check_data_status import inspect_data_status, compute_content_hash


@pytest.fixture
def sample_json(tmp_path):
    """테스트용 샘플 공지 JSON 파일 생성."""
    notices = [
        {
            "id": "notice_001",
            "title": "2026학년도 2학기 폐강 강좌 수강신청 정정 안내",
            "content": "폐강 강좌 수강신청 정정 기간은 9월 9일부터 9월 10일까지입니다.",
            "source": "학사운영팀",
            "category": "학사",
            "date": "2026-09-08",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224608/artclView.do",
            "content_status": "text",
        },
        {
            "id": "notice_002",
            "title": "편입생 전적대학 학점 재인정 신청 안내",
            "content": "일반편입생 전적대학 학점 재인정 신청 접수를 안내합니다.",
            "source": "학사운영팀",
            "category": "학사",
            "date": "2026-09-08",
            "url": "https://www.hansung.ac.kr/bbs/hansung/2127/224588/artclView.do",
            "content_status": "text",
        },
    ]
    p = tmp_path / "test_notices.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False)
    return p, notices


def test_in_sync_full_match(sample_json, tmp_path):
    """1. JSON과 DB의 ID 및 내용 해시가 완전 일치할 때 IN_SYNC=True 반환."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    mock_vs = MagicMock()
    mock_vs.get.return_value = {
        "ids": ["chunk_001", "chunk_002"],
        "metadatas": [
            {
                "parent_id": "notice_001",
                "id": "notice_001",
                "url": notices[0]["url"],
                "title": notices[0]["title"],
                "content_hash": compute_content_hash(notices[0]["title"], notices[0]["content"]),
                "chunk_index": 0,
            },
            {
                "parent_id": "notice_002",
                "id": "notice_002",
                "url": notices[1]["url"],
                "title": notices[1]["title"],
                "content_hash": compute_content_hash(notices[1]["title"], notices[1]["content"]),
                "chunk_index": 0,
            },
        ],
        "documents": [
            f"{notices[0]['title']}\n{notices[0]['content']}",
            f"{notices[1]['title']}\n{notices[1]['content']}",
        ],
    }

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        report = inspect_data_status(
            json_path=str(json_path),
            db_path=str(fake_db),
            strict=True,
        )

    assert report["in_sync"] is True
    assert report["matched_in_db_count"] == 2
    assert len(report["missing_in_db"]) == 0
    assert len(report["stale_in_db"]) == 0
    assert len(report["extra_in_db"]) == 0


def test_same_count_different_ids_fails(sample_json, tmp_path):
    """2. 공지 건수는 동일(2건)하지만 공지 ID가 서로 다른 경우 불일치(IN_SYNC=False) 감지."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    mock_vs = MagicMock()
    # DB에는 notice_001 대신 전혀 다른 notice_999가 들어있음 (건수는 2건으로 동일)
    mock_vs.get.return_value = {
        "ids": ["chunk_999", "chunk_002"],
        "metadatas": [
            {
                "parent_id": "notice_999",
                "id": "notice_999",
                "url": "https://other.url/999",
                "title": "전혀 다른 공지",
                "content_hash": "hash_999",
                "chunk_index": 0,
            },
            {
                "parent_id": "notice_002",
                "id": "notice_002",
                "url": notices[1]["url"],
                "title": notices[1]["title"],
                "content_hash": compute_content_hash(notices[1]["title"], notices[1]["content"]),
                "chunk_index": 0,
            },
        ],
        "documents": [
            "전혀 다른 공지\n내용",
            f"{notices[1]['title']}\n{notices[1]['content']}",
        ],
    }

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        report = inspect_data_status(
            json_path=str(json_path),
            db_path=str(fake_db),
        )

    # 단순 건수 비교(2건 == 2건)였으면 통과했겠지만, 해시/ID 기반 진단에서는 반드시 실패해야 함
    assert report["in_sync"] is False
    assert "notice_001" in report["missing_in_db"]
    assert "notice_999" in report["extra_in_db"]
    assert any("누락되어 있습니다" in issue for issue in report["issues"])


def test_same_ids_different_content_stale_detected(sample_json, tmp_path):
    """3. 공지 ID는 같으나 내용 해시가 변경된 경우(Stale DB) 불일치(IN_SYNC=False) 감지."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    mock_vs = MagicMock()
    # DB에는 notice_001의 과거 내용(다른 해시)이 들어있음
    old_hash = "old_stale_hash_001"
    mock_vs.get.return_value = {
        "ids": ["chunk_001", "chunk_002"],
        "metadatas": [
            {
                "parent_id": "notice_001",
                "id": "notice_001",
                "url": notices[0]["url"],
                "title": notices[0]["title"],
                "content_hash": old_hash,
                "chunk_index": 0,
            },
            {
                "parent_id": "notice_002",
                "id": "notice_002",
                "url": notices[1]["url"],
                "title": notices[1]["title"],
                "content_hash": compute_content_hash(notices[1]["title"], notices[1]["content"]),
                "chunk_index": 0,
            },
        ],
        "documents": [
            "과거 제목\n과거 내용 변경 전",
            f"{notices[1]['title']}\n{notices[1]['content']}",
        ],
    }

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        report = inspect_data_status(
            json_path=str(json_path),
            db_path=str(fake_db),
        )

    assert report["in_sync"] is False
    assert len(report["stale_in_db"]) == 1
    assert report["stale_in_db"][0]["id"] == "notice_001"
    assert any("내용 해시가 불일치하는 공지" in issue for issue in report["issues"])


def test_historical_preservation_allowed_in_normal_mode(sample_json, tmp_path):
    """4. DB에 과거 공지가 추가 보존된 경우 일반 모드에서는 in_sync=True, strict 모드에서는 False."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    mock_vs = MagicMock()
    mock_vs.get.return_value = {
        "ids": ["chunk_001", "chunk_002", "chunk_old_past"],
        "metadatas": [
            {
                "parent_id": "notice_001",
                "id": "notice_001",
                "url": notices[0]["url"],
                "title": notices[0]["title"],
                "content_hash": compute_content_hash(notices[0]["title"], notices[0]["content"]),
                "chunk_index": 0,
            },
            {
                "parent_id": "notice_002",
                "id": "notice_002",
                "url": notices[1]["url"],
                "title": notices[1]["title"],
                "content_hash": compute_content_hash(notices[1]["title"], notices[1]["content"]),
                "chunk_index": 0,
            },
            {
                "parent_id": "notice_past_2024",
                "id": "notice_past_2024",
                "url": "https://past.url/2024",
                "title": "2024학년도 과거 공지",
                "content_hash": "past_hash",
                "chunk_index": 0,
            },
        ],
        "documents": ["doc1", "doc2", "past_doc"],
    }

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        # 일반 모드: 현재 JSON 공지가 모두 최신으로 존재하면 통과
        rep_normal = inspect_data_status(
            json_path=str(json_path),
            db_path=str(fake_db),
            strict=False,
        )
        assert rep_normal["in_sync"] is True
        assert len(rep_normal["extra_in_db"]) == 1

        # Strict 모드: 추가 공지가 있으면 불일치
        rep_strict = inspect_data_status(
            json_path=str(json_path),
            db_path=str(fake_db),
            strict=True,
        )
        assert rep_strict["in_sync"] is False
        assert any("[Strict 모드]" in issue for issue in rep_strict["issues"])


def test_prefix_same_tail_deadline_changed_fails_as_stale(sample_json, tmp_path):
    """5. 제목과 본문 앞 100글자가 동일하더라도 뒤쪽 마감일이 변경된 경우 stale(불일치)로 감지."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    # JSON은 마감일이 9월 10일
    # DB에는 앞부분 100글자는 동일하지만 뒤쪽 마감일이 9월 17일인 과거 버전이 들어있음
    prefix_text = "이 공지는 앞 100글자가 완전히 동일한 공지사항입니다. " * 3  # 약 90글자
    json_notice = {
        "id": "notice_deadline_diff",
        "title": "2026학년도 수강신청 정정 일정 안내",
        "content": prefix_text + "\n최종 마감일: 2026년 9월 10일 18:00까지",
        "url": "https://hansung.ac.kr/notice/deadline",
        "category": "학사",
        "date": "2026-09-08",
        "content_status": "text",
    }
    custom_json = tmp_path / "deadline_notices.json"
    with open(custom_json, "w", encoding="utf-8") as f:
        json.dump([json_notice], f, ensure_ascii=False)

    db_content = prefix_text + "\n최종 마감일: 2026년 9월 17일 18:00까지 (연장전)"
    db_hash = compute_content_hash(json_notice["title"], db_content)

    mock_vs = MagicMock()
    mock_vs.get.return_value = {
        "ids": ["chunk_dl_001"],
        "metadatas": [
            {
                "parent_id": "notice_deadline_diff",
                "id": "notice_deadline_diff",
                "url": json_notice["url"],
                "title": json_notice["title"],
                "content_hash": db_hash,
                "chunk_index": 0,
            }
        ],
        "documents": [f"{json_notice['title']}\n{db_content}"],
    }

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        report = inspect_data_status(
            json_path=str(custom_json),
            db_path=str(fake_db),
        )

    # 앞 80글자 휴리스틱이 제거되었으므로, 해시 불일치로 인해 반드시 stale 및 in_sync=False이어야 함
    assert report["in_sync"] is False
    assert len(report["stale_in_db"]) == 1
    assert report["stale_in_db"][0]["id"] == "notice_deadline_diff"
    assert any("내용 해시가 불일치하는 공지" in issue for issue in report["issues"])


def test_legacy_data_unverifiable_hash_fails(sample_json, tmp_path):
    """6. DB 메타데이터에 content_hash가 없고 문서 텍스트도 비어있어 해시를 알 수 없는 레거시 데이터는 검증 불가 및 불일치 처리."""
    json_path, notices = sample_json
    fake_db = tmp_path / "fake_db"
    fake_db.mkdir()

    mock_vs = MagicMock()
    mock_vs.get.return_value = {
        "ids": ["chunk_001"],
        "metadatas": [
            {
                "parent_id": "notice_001",
                "id": "notice_001",
                "url": notices[0]["url"],
                "title": notices[0]["title"],
                # content_hash 필드 부재
                "chunk_index": 0,
            }
        ],
        "documents": [""],  # 문서 본문도 비어있어 해시 도출 불가
    }

    # notice_001 1건만 포함된 json 사용
    single_json = tmp_path / "single_notice.json"
    with open(single_json, "w", encoding="utf-8") as f:
        json.dump([notices[0]], f, ensure_ascii=False)

    with patch("scripts.check_data_status.get_chroma_vectorstore", return_value=mock_vs):
        report = inspect_data_status(
            json_path=str(single_json),
            db_path=str(fake_db),
        )

    assert report["in_sync"] is False
    assert len(report["unverifiable_in_db"]) == 1
    assert report["unverifiable_in_db"][0]["id"] == "notice_001"
    assert any("검증 불가" in issue for issue in report["issues"])

