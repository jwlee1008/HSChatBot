#!/usr/bin/env python3
"""Activate a validated knowledge snapshot while the backend is stopped.

python scripts/activate_knowledge_snapshot.py data/knowledge_snapshots/RUN --server-stopped
Docker volumes: set --active-db to a child directory, never the mounted root.
Previous targets are copied and retained in the backup (beside targets across disks).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_sync(dataset, database, collection):
    # A separate process releases every Chroma/SQLite client before we copy.
    subprocess.run([sys.executable, str(ROOT / "scripts/check_data_status.py"),
                    "--json-path", str(dataset), "--db-path", str(database),
                    "--collection-name", collection, "--strict"], cwd=ROOT, check=True)


def validate_candidate(candidate):
    if not candidate.is_dir() or any(p.is_symlink() for p in candidate.rglob("*")):
        raise ValueError("Candidate must be a directory without symlinks")
    report = json.loads((candidate / "refresh_report.json").read_text())
    if report.get("status") != "validated_candidate":
        raise ValueError("Refresh report must have status validated_candidate")
    dataset = candidate / "unified_campus_knowledge.json"
    manifest = candidate / "unified_manifest.json"
    database = candidate / "chroma_db"
    summary = json.loads(manifest.read_text())["output_summary"]
    records = json.loads(dataset.read_text())
    if not isinstance(records, list) or not records or not all(isinstance(d, dict) for d in records):
        raise ValueError("Candidate dataset must contain documents")
    if len(records) != summary.get("total_documents"):
        raise ValueError("Manifest document count does not match JSON")
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != summary.get("output_sha256"):
        raise ValueError("Candidate dataset SHA-256 does not match manifest")
    if not (database / "chroma.sqlite3").is_file():
        raise ValueError("Candidate Chroma database is missing")
    collection = report.get("collection")
    if not isinstance(collection, str) or not collection:
        raise ValueError("Refresh report collection is missing")
    check_sync(dataset, database, collection)
    return (database, dataset, manifest), collection


def copy_path(source, target):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def replace_path(source, target):
    source.replace(target)


def remove_created(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def activate_snapshot(candidate, *, server_stopped=False, active_db=None, dataset=None,
                      manifest=None, backup_dir=None):
    if not server_stopped:
        raise ValueError("Stop the backend first and pass --server-stopped")
    import config
    candidate = Path(candidate).resolve()
    targets = [Path(active_db or config.CHROMA_PERSIST_DIR).absolute(),
               Path(dataset or config.NOTICES_PATH).absolute(),
               Path(manifest or ROOT / "data/unified_manifest.json").absolute()]
    if any(p.is_symlink() for p in targets):
        raise ValueError("Activation targets cannot be symlinks")
    targets = [p.resolve() for p in targets]
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup = Path(backup_dir or ROOT / "backups" / f"knowledge-{token}")
    if backup.is_symlink():
        raise ValueError("Backup directory cannot be a symlink")
    backup = backup.resolve()
    paths = [candidate, backup, *targets]
    for i, path in enumerate(paths):
        for other in paths[i + 1:]:
            if path.is_relative_to(other) or other.is_relative_to(path):
                raise ValueError("Candidate, backup and activation targets must not overlap")
    if backup.exists():
        raise FileExistsError(f"Backup directory already exists: {backup}")
    for i, target in enumerate(targets):
        if os.path.ismount(target):
            raise ValueError("Use a child directory inside the mounted volume")
        if target.exists() and (target.is_dir() != (i == 0)):
            raise ValueError(f"Target has the wrong file type: {target}")
    sources, collection = validate_candidate(candidate)  # No target changes before validation.
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "originals").mkdir()
    report_path = backup / "activation_report.json"
    report = {"status": "preparing", "candidate": str(candidate), "collection": collection,
              "backup_dir": str(backup), "targets": [str(p) for p in targets], "retained_originals": []}
    operations = []
    try:
        for source, target, name in zip(sources, targets, ("chroma_db", "dataset.json", "manifest.json")):
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.with_name(f".campusmate-staged-{target.name}-{token}")
            previous = (backup / "originals" / name if target.parent.stat().st_dev == backup.stat().st_dev
                        else target.with_name(f".campusmate-previous-{target.name}-{token}"))
            if any(p.exists() or p.is_symlink() for p in (stage, previous)):
                raise FileExistsError("Activation temporary path already exists")
            operation = {"target": target, "stage": stage, "previous": previous,
                         "original_moved": False, "installed": False}
            operations.append(operation)
            if target.exists():
                copy_path(target, backup / name)
            copy_path(source, stage)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        for op in operations:
            if op["target"].exists():
                replace_path(op["target"], op["previous"])
                op["original_moved"] = True
                report["retained_originals"].append(str(op["previous"]))
            replace_path(op["stage"], op["target"])
            op["installed"] = True
        report["status"] = "activated"
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    except BaseException:
        rollback_errors = []
        for op in reversed(operations):
            try:
                if op["installed"]:
                    replace_path(op["target"], op["stage"])
                if op["original_moved"]:
                    replace_path(op["previous"], op["target"])
            except OSError as error:
                rollback_errors.append(str(error))
        report.update(status="rollback_failed" if rollback_errors else "rolled_back", rollback_errors=rollback_errors)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        raise
    finally:
        for op in operations:
            remove_created(op["stage"])
    report["report_path"] = str(report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--server-stopped", action="store_true")
    for name in ("active-db", "dataset", "manifest", "backup-dir"):
        parser.add_argument("--" + name, type=Path)
    try:
        report = activate_snapshot(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
