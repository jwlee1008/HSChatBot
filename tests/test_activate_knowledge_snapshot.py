"""Exercise activation and rollback using file sentinels, never a real Chroma DB."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import activate_knowledge_snapshot as activation


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    payload = json.dumps([{"id": "notice-1", "title": "공지", "content": "최신 본문"}]).encode()
    (candidate / "unified_campus_knowledge.json").write_bytes(payload)
    (candidate / "unified_manifest.json").write_text(json.dumps({"output_summary": {
        "total_documents": 1, "output_sha256": hashlib.sha256(payload).hexdigest()}}))
    (candidate / "refresh_report.json").write_text(json.dumps({"status": "validated_candidate", "collection": "campus_knowledge"}))
    (candidate / "chroma_db").mkdir()
    (candidate / "chroma_db/chroma.sqlite3").write_text("candidate database")
    live = tmp_path / "live"
    live.mkdir()
    database = live / "chroma_db"
    database.mkdir()
    (database / "chroma.sqlite3").write_text("previous database")
    dataset = live / "dataset.json"
    dataset.write_text("previous dataset")
    manifest = live / "manifest.json"
    manifest.write_text("previous manifest")
    options = {"server_stopped": True, "active_db": database, "dataset": dataset,
               "manifest": manifest, "backup_dir": tmp_path / "backup"}
    monkeypatch.setattr(activation, "check_sync", lambda *args: None)
    return candidate, options


def assert_old(options):
    assert (options["active_db"] / "chroma.sqlite3").read_text() == "previous database"
    assert options["dataset"].read_text() == "previous dataset"
    assert options["manifest"].read_text() == "previous manifest"


def test_explicit_stopped_assertion_required_before_validation(snapshot, monkeypatch):
    candidate, options = snapshot
    monkeypatch.setattr(activation, "validate_candidate", lambda *args: pytest.fail("should refuse first"))
    options["server_stopped"] = False
    with pytest.raises(ValueError, match="server-stopped"):
        activation.activate_snapshot(candidate, **options)
    assert_old(options)
    assert not options["backup_dir"].exists()


@pytest.mark.parametrize("damage", ["status", "hash", "count", "database"])
def test_invalid_snapshot_never_touches_active_or_creates_backup(snapshot, damage):
    candidate, options = snapshot
    if damage == "status":
        (candidate / "refresh_report.json").write_text(json.dumps({"status": "failed"}))
    elif damage == "hash":
        (candidate / "unified_campus_knowledge.json").write_text('[{"id": "tampered"}]')
    elif damage == "count":
        manifest = json.loads((candidate / "unified_manifest.json").read_text())
        manifest["output_summary"]["total_documents"] = 2
        (candidate / "unified_manifest.json").write_text(json.dumps(manifest))
    else:
        (candidate / "chroma_db/chroma.sqlite3").unlink()
    with pytest.raises(ValueError):
        activation.activate_snapshot(candidate, **options)
    assert_old(options)
    assert not options["backup_dir"].exists()


def test_strict_sync_failure_never_copies_or_changes_active(snapshot, monkeypatch):
    candidate, options = snapshot
    def fail(*args):
        raise subprocess.CalledProcessError(1, "strict check")
    monkeypatch.setattr(activation, "check_sync", fail)
    with pytest.raises(subprocess.CalledProcessError):
        activation.activate_snapshot(candidate, **options)
    assert_old(options)
    assert not options["backup_dir"].exists()


def test_success_retains_originals_backup_and_candidate(snapshot):
    candidate, options = snapshot
    report = activation.activate_snapshot(candidate, **options)
    assert report["status"] == "activated"
    assert (options["active_db"] / "chroma.sqlite3").read_text() == "candidate database"
    assert options["dataset"].read_bytes() == (candidate / "unified_campus_knowledge.json").read_bytes()
    assert options["manifest"].read_bytes() == (candidate / "unified_manifest.json").read_bytes()
    assert (options["backup_dir"] / "chroma_db/chroma.sqlite3").read_text() == "previous database"
    assert (options["backup_dir"] / "dataset.json").read_text() == "previous dataset"
    assert (options["backup_dir"] / "manifest.json").read_text() == "previous manifest"
    originals = [Path(p) for p in report["retained_originals"]]
    assert len(originals) == 3 and all(p.exists() for p in originals)
    assert (originals[0] / "chroma.sqlite3").read_text() == "previous database"
    assert not list(options["active_db"].parent.glob(".campusmate-staged-*"))
    assert json.loads(Path(report["report_path"]).read_text())["status"] == "activated"


def test_failure_after_first_swap_rolls_every_target_back(snapshot, monkeypatch):
    candidate, options = snapshot
    original = activation.replace_path
    failed = False
    def fail_once(source, target):
        nonlocal failed
        if target == options["dataset"] and ".campusmate-staged-" in source.name and not failed:
            failed = True
            raise OSError("simulated swap failure")
        original(source, target)
    monkeypatch.setattr(activation, "replace_path", fail_once)
    with pytest.raises(OSError, match="simulated"):
        activation.activate_snapshot(candidate, **options)
    assert_old(options)
    assert (candidate / "chroma_db/chroma.sqlite3").read_text() == "candidate database"
    assert json.loads((options["backup_dir"] / "activation_report.json").read_text())["status"] == "rolled_back"
    assert not list(options["active_db"].parent.glob(".campusmate-staged-*"))
    assert not list(options["active_db"].parent.glob(".campusmate-previous-*"))


def test_copy_failure_preserves_originals_and_cleans_only_created_stages(snapshot, monkeypatch):
    candidate, options = snapshot
    original = activation.copy_path
    def fail(source, target):
        if source == candidate / "unified_manifest.json":
            target.write_text("partial script-created file")
            raise OSError("copy failed")
        original(source, target)
    monkeypatch.setattr(activation, "copy_path", fail)
    with pytest.raises(OSError, match="copy failed"):
        activation.activate_snapshot(candidate, **options)
    assert_old(options)
    assert not list(options["active_db"].parent.glob(".campusmate-staged-*"))


@pytest.mark.parametrize("problem", ["overlap", "symlink", "backup_exists", "mounted_root"])
def test_unsafe_target_layout_is_rejected(snapshot, monkeypatch, problem):
    candidate, options = snapshot
    if problem == "overlap":
        options["active_db"] = candidate / "chroma_db"
    elif problem == "symlink":
        link = options["active_db"].parent / "database-link"
        link.symlink_to(options["active_db"], target_is_directory=True)
        options["active_db"] = link
    elif problem == "backup_exists":
        options["backup_dir"].mkdir()
    else:
        monkeypatch.setattr(activation.os.path, "ismount", lambda p: p == options["active_db"])
    with pytest.raises((ValueError, FileExistsError)):
        activation.activate_snapshot(candidate, **options)


def test_missing_targets_are_created_only_after_successful_validation(snapshot):
    candidate, options = snapshot
    for key in ("active_db", "dataset", "manifest"):
        options[key] = options[key].parent / f"new-{options[key].name}"
    report = activation.activate_snapshot(candidate, **options)
    assert report["retained_originals"] == []
    assert (options["active_db"] / "chroma.sqlite3").read_text() == "candidate database"


def test_sync_validation_runs_in_separate_process(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(activation.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    activation.check_sync(tmp_path / "dataset.json", tmp_path / "chroma", "campus_knowledge")
    command, kwargs = calls[0]
    assert command[0] == activation.sys.executable
    assert "--strict" in command
    assert command[command.index("--collection-name") + 1] == "campus_knowledge"
    assert kwargs["check"] is True
