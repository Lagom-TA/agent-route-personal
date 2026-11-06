"""Python 3.11+ verified public rule cache. Never edits a client configuration."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import urllib.request

REPO = 'ryuu-restart/agent-route'
BASE = 'https://raw.githubusercontent.com/' + REPO + '/'
LIMIT = 16 * 1024 * 1024
FORMATS = {'mihomo': '.yaml', 'surge': '.list', 'sing-box': '.json'}
NAMES = ('private', 'reject', 'proxy', 'direct', 'cn-ip')
SHA = re.compile(r'^[a-f0-9]{40}$')
DIGEST = re.compile(r'^[a-f0-9]{64}$')
HELPER = 'sing-box/non-cn-ip.json'


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'AgentRoute-sync/1'}), timeout=30) as r:
        if not r.url.startswith(('https://raw.githubusercontent.com/', 'https://api.github.com/')):
            raise ValueError('redirect_origin_rejected')
        data = r.read(LIMIT + 1)
        if r.status != 200 or not data or len(data) > LIMIT:
            raise ValueError('download_invalid')
        if r.headers.get('Content-Length') and len(data) != int(r.headers['Content-Length']):
            raise ValueError('download_truncated')
        return data


def atomic(path, value):
    # Follows the umask, like the rule files: a client may run as another user.
    name = path.with_name('.pointer-' + secrets.token_hex(8))
    try:
        with open(name, 'x', encoding='utf-8') as f:
            json.dump(value, f); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


@contextmanager
def locked(root):
    if root.is_symlink(): raise ValueError('cache_symlink_rejected')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.lock'
    if lock.is_symlink(): raise ValueError('cache_symlink_rejected')
    with lock.open('a+b') as f:
        f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise ValueError('cache_busy') from e
        try: yield
        finally:
            if os.name == 'nt':
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def pointer(root):
    p = root / 'current.json'
    if p.is_symlink(): raise ValueError('cache_symlink_rejected')
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'current': None, 'previous': None}


def directory(root, generation):
    if not isinstance(generation, str) or not re.fullmatch(r'[a-f0-9]{40}-(all|mihomo|surge|sing-box)', generation):
        raise ValueError('invalid_cache_generation')
    base = root / 'generations'
    path = base / generation
    if base.is_symlink() or path.is_symlink(): raise ValueError('cache_symlink_rejected')
    return path


def validate_manifest(m):
    if not isinstance(m, dict) or m.get('scope') != 'domestic_direct_and_adblock' or m.get('schema_version', 1) != 1:
        raise ValueError('unsupported_manifest')
    if not isinstance(m.get('files'), dict): raise ValueError('invalid_file_map')
    for name, digest in m['files'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name) or any(p in ('.', '..') for p in name.split('/')) or not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('unsafe_manifest_path_or_digest')
    if not isinstance(m.get('generated_at_utc'), str): raise ValueError('invalid_timestamp')
    date = datetime.fromisoformat(m['generated_at_utc'].replace('Z', '+00:00'))
    if date.tzinfo is None: raise ValueError('missing_timestamp_timezone')
    return (datetime.now(timezone.utc) - date).total_seconds()


def verify(root, generation):
    path = directory(root, generation)
    meta_path = path / 'cache.json'
    if meta_path.is_symlink(): raise ValueError('cache_symlink_rejected')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    if (path / 'manifest.json').is_symlink(): raise ValueError('cache_symlink_rejected')
    m = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    age = validate_manifest(m)
    expected = meta['files']
    # Caches written before the helper file existed hold only the rule files; both stay valid.
    if not isinstance(expected, list) or not set(selected(generation.split('-', 1)[1])) <= set(expected) or not set(expected) <= set(m['files']):
        raise ValueError('cache_inventory_invalid')
    for name in expected:
        p = path / name
        if p.parent.is_symlink() or p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != m['files'][name]:
            raise ValueError('cached_file_corrupt')
    return {'generation': generation, 'directory': str(path.resolve()), 'age_seconds': round(age), 'stale': age > 172800, 'files': expected}


def selected(fmt):
    formats = FORMATS if fmt == 'all' else {fmt: FORMATS[fmt]}
    return ['index.json'] + [f'{f}/{n}{ext}' for f, ext in formats.items() for n in NAMES]


def operate(command, root, fmt='all', fetch=get):
    with locked(root):
        state = pointer(root)
        for key in ('current', 'previous'):
            if state[key]: directory(root, state[key])
        held = state.get('held')
        if held: directory(root, held)
        if command in ('status', 'verify'):
            if not state['current']: raise ValueError('cache_empty')
            return {'status': 'verified', **verify(root, state['current']), 'previous': state['previous']}
        if command == 'rollback':
            if not state['previous']: raise ValueError('previous_generation_unavailable')
            result = verify(root, state['previous'])
            # Remember what the user backed out of, or the next sync would select it again.
            atomic(root / 'current.json', {'current': state['previous'], 'previous': state['current'], 'held': state['current']})
            return {'status': 'rolled_back', **result}
        if state['current']:
            verify(root, state['current'])
        sha = json.loads(fetch('https://api.github.com/repos/' + REPO + '/commits/release'))['sha']
        if not isinstance(sha, str) or not SHA.fullmatch(sha): raise ValueError('invalid_release_sha')
        raw = fetch(BASE + sha + '/manifest.json'); m = json.loads(raw)
        age = validate_manifest(m)
        if not -300 <= age <= 172800: raise ValueError('publication_stale_or_future')
        generation = sha + '-' + fmt
        if state['current'] == generation:
            return {'status': 'unchanged', **verify(root, generation)}
        if held == generation:
            return {'status': 'held', 'held_generation': held, **verify(root, state['current'])}
        dest = directory(root, generation)
        dest.parent.mkdir(exist_ok=True)
        # Not mkdtemp: its 0700 would stay on the published generation directory.
        stage = dest.parent / ('.stage-' + secrets.token_hex(8))
        stage.mkdir()
        try:
            (stage / 'manifest.json').write_bytes(raw)
            names = selected(fmt) + ([HELPER] if fmt in ('all', 'sing-box') and HELPER in m['files'] else [])
            for name in names:
                data = fetch(BASE + sha + '/' + name)
                if not data or len(data) > LIMIT or hashlib.sha256(data).hexdigest() != m['files'][name]:
                    raise ValueError('resource_hash_mismatch')
                p = stage / name; p.parent.mkdir(exist_ok=True); p.write_bytes(data)
            index = json.loads((stage / 'index.json').read_bytes())
            if not isinstance(index, dict) or index.get('schema_version') != 1 or index.get('generated_at_utc') != m['generated_at_utc']:
                raise ValueError('index_generation_mismatch')
            (stage / 'cache.json').write_text(json.dumps({'files': names}), encoding='utf-8')
            if dest.exists(): verify(root, generation)
            else: os.replace(stage, dest)
            result = verify(root, generation)
            atomic(root / 'current.json', {'current': generation, 'previous': state['current']})
            # Only remove the former previous generation, never arbitrary user files.
            old = state['previous']
            if old and old not in (generation, state['current']):
                try: shutil.rmtree(directory(root, old))
                except OSError: pass
            return {'status': 'updated', **result}
        finally:
            if stage.exists():
                try: shutil.rmtree(stage)
                except OSError: pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('sync', 'verify', 'status', 'rollback'))
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--format', choices=(*FORMATS, 'all'), default='all')
    a = p.parse_args()
    try:
        result = operate(a.command, a.output.absolute(), a.format)
        print(json.dumps(result)); return 0
    except (ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as e:
        print(json.dumps({'status': 'failed', 'error': str(e), 'current_preserved': True})); return 1


if __name__ == '__main__': sys.exit(main())
