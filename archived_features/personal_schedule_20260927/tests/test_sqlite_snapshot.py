import sqlite3

import pytest

from scripts.sqlite_snapshot import snapshot


def test_committed_wal_is_included_and_restore_preserves_values(tmp_path):
    source = tmp_path / 'source.db'
    with sqlite3.connect(source) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('CREATE TABLE records (value TEXT)')
        value = '2027-11-20T09:00:45.123456Z'
        connection.execute('INSERT INTO records VALUES (?)', (value,))
        connection.commit()
        assert (tmp_path / 'source.db-wal').stat().st_size > 0
        snapshot(source, tmp_path / 'backup.db')
    snapshot(tmp_path / 'backup.db', tmp_path / 'restored.db')
    with sqlite3.connect(tmp_path / 'restored.db') as restored:
        assert restored.execute('SELECT value FROM records').fetchall() == [(value,)]


def test_existing_destination_is_never_overwritten(tmp_path):
    source = tmp_path / 'source.db'
    sqlite3.connect(source).close()
    destination = tmp_path / 'existing.db'
    destination.write_bytes(b'keep existing backup')
    with pytest.raises(FileExistsError):
        snapshot(source, destination)
    assert destination.read_bytes() == b'keep existing backup'


def test_invalid_source_leaves_no_partial_backup(tmp_path):
    source = tmp_path / 'invalid.db'
    source.write_bytes(b'invalid database' * 100)
    destination = tmp_path / 'backup.db'
    with pytest.raises(sqlite3.DatabaseError):
        snapshot(source, destination)
    assert not destination.exists()
