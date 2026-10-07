"""Create a consistent SQLite snapshot, including committed WAL records.

Usage: python scripts/sqlite_snapshot.py SOURCE NEW_DESTINATION
For restore, stop the service and snapshot the backup into a NEW DB path;
switch AUTH_DB_PATH only after integrity checking. Existing files are refused.
"""
import argparse
import os
from pathlib import Path
import sqlite3


def snapshot(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise RuntimeError('SQLite integrity check failed')
                if dst.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('SQLite foreign key check failed')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    snapshot(args.source, args.destination)
    print('SQLite snapshot verified')
