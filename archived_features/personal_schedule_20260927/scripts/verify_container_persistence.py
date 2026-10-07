"""Isolated local Docker acceptance: health/assets, recreate, SQLite backup/restore.

Build first. Run with --image IMAGE. Creates a unique Compose project, synthetic
account and volumes; removes only that project's containers/volumes on exit.
Never loads the repository .env or invokes RAG/model APIs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    project = 'campusmate-check-' + secrets.token_hex(5)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT / 'data').rglob('*') if p.is_file()}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, CAMPUSMATE_PORT=str(port), PREWARM_RAG_ON_STARTUP='false',
               LLM_PROVIDER='local', GEMINI_API_KEY='', OPENAI_API_KEY='')
    base_url = f'http://127.0.0.1:{port}'
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        override = Path(tmp) / 'override.json'
        def write_override(db='campusmate.db'):
            override.write_text(json.dumps({'services': {'backend': {
                'image': args.image,
                'environment': {'AUTH_DB_PATH': '/var/lib/campusmate/' + db,
                                'PREWARM_RAG_ON_STARTUP': 'false'},
            }}}))
        write_override()
        compose = ['docker', 'compose', '--env-file', '/dev/null', '-p', project,
                   '-f', str(ROOT / 'docker-compose.yml'), '-f', str(override)]
        def run(*cmd):
            result = subprocess.run([*compose, *cmd], env=env, cwd=ROOT,
                                    capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr[-3000:])
            return result.stdout.strip()
        def api(path, payload=None, token=None, method=None):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            req = urllib.request.Request(base_url + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read()
                return json.loads(body) if body else None
        def healthy():
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                cid = run('ps', '-q', 'backend')
                if cid:
                    state = subprocess.check_output(['docker', 'inspect', '--format',
                             '{{.State.Health.Status}}', cid], text=True).strip()
                    if state == 'healthy':
                        assert api('/health')['status'] == 'ok'
                        return
                time.sleep(1)
            raise RuntimeError('Container did not become healthy; ' + run('logs', '--tail', '40', 'backend'))
        try:
            run('up', '-d', '--no-build', 'backend')
            healthy()
            with urllib.request.urlopen(base_url + '/') as response:
                html = response.read().decode()
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
            assert assets, 'Built frontend assets missing'
            for asset in assets:
                with urllib.request.urlopen(base_url + asset) as response:
                    assert response.status == 200
            checks.append('docker_health_and_built_react_assets')
            credentials = {'username': 'container_audit', 'password': secrets.token_urlsafe(20)}
            api('/api/v1/auth/register', credentials)
            token = api('/api/v1/auth/login', credentials)['access_token']
            schedule = api('/api/v1/schedules', {
                'title': 'Container persistence audit', 'schedule_kind': 'TIME_CONFIRMED_DEADLINE',
                'end_date': '2027-11-20', 'end_datetime': '2027-11-20T18:00:45.123456+09:00',
                'confirmed': True}, token)
            def verify_record():
                assert api('/api/v1/auth/me', token=token)['username'] == credentials['username']
                record = api('/api/v1/schedules/' + schedule['id'], token=token)
                assert record == schedule, 'Record changed across lifecycle operation'
                assert api('/api/v1/auth/login', credentials)['access_token']
            run('restart', 'backend')
            healthy()
            verify_record()
            checks.append('restart_preserves_account_session_schedule_precision')
            cid = run('ps', '-q', 'backend')
            run('up', '-d', '--no-build', '--force-recreate', 'backend')
            healthy()
            assert run('ps', '-q', 'backend') != cid
            verify_record()
            checks.append('new_container_preserves_named_volume')
            run('exec', '-T', 'backend', 'python', 'scripts/sqlite_snapshot.py',
                '/var/lib/campusmate/campusmate.db', '/var/lib/campusmate/audit-backup.db')
            backup = Path(tmp) / 'backup.db'
            run('cp', 'backend:/var/lib/campusmate/audit-backup.db', str(backup))
            assert backup.stat().st_size > 0
            checks.append('online_sqlite_backup_and_export')
            api('/api/v1/schedules/' + schedule['id'], token=token, method='DELETE')
            assert api('/api/v1/schedules', token=token)['total'] == 0
            run('stop', 'backend')
            # Clean restore volume: prove the backup alone is sufficient, with no WAL files.
            override.write_text(json.dumps({'services': {'backend': {
                'image': args.image, 'environment': {'AUTH_DB_PATH': '/var/lib/campusmate/campusmate.db'},
                'volumes': ['restore_data:/var/lib/campusmate'],
            }}, 'volumes': {'restore_data': {}}}))
            run('run', '--rm', '--no-deps', '-v', f'{backup}:/backup/input.db:ro', 'backend',
                'python', 'scripts/sqlite_snapshot.py', '/backup/input.db', '/var/lib/campusmate/campusmate.db')
            run('up', '-d', '--no-build', '--force-recreate', 'backend')
            healthy()
            verify_record()
            checks.append('restore_to_fresh_volume_recovers_deleted_record')
        finally:
            # Compose down uses the same unique project; remove both test volumes explicitly.
            run('down', '--volumes', '--remove-orphans')
            for volume in ('auth_data', 'restore_data'):
                subprocess.run(['docker', 'volume', 'rm', project + '_' + volume],
                               capture_output=True)
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (ROOT / 'data').rglob('*') if p.is_file()}
    assert before == after, 'Repository data changed'
    print(json.dumps({'project': project, 'checks': checks, 'data_files': len(before),
                      'data_unchanged': True}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
