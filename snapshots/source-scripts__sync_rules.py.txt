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
import stat
import sys
import urllib.request

# BEGIN GENERATED RULE CATALOG
# Regenerate with scripts/update_rule_catalog.py --write.
REPO = 'ryuu-restart/agent-route'
FORMATS = {'mihomo': '.yaml', 'surge': '.list', 'sing-box': '.json'}
NAMES = ('private', 'reject', 'proxy', 'direct', 'cn-ip')
HELPER = 'sing-box/non-cn-ip.json'
REQUIRED_FILES = {
    'mihomo': ('mihomo/private.yaml', 'mihomo/reject.yaml', 'mihomo/proxy.yaml', 'mihomo/direct.yaml', 'mihomo/cn-ip.yaml'),
    'surge': ('surge/private.list', 'surge/reject.list', 'surge/proxy.list', 'surge/direct.list', 'surge/cn-ip.list'),
    'sing-box': ('sing-box/private.json', 'sing-box/reject.json', 'sing-box/proxy.json', 'sing-box/direct.json', 'sing-box/cn-ip.json'),
}
OPTIONAL_FILES = {
    'mihomo': ('mihomo/webrtc-guard.yaml',),
    'surge': ('surge/webrtc-guard.list',),
    'sing-box': ('sing-box/webrtc-guard.json', 'sing-box/non-cn-ip.json'),
}
VARIANT_FILES = {
    'mrs': {
        'private': 'mihomo/private.mrs',
        'reject': 'mihomo/reject.mrs',
        'proxy': 'mihomo/proxy.mrs',
        'direct': 'mihomo/direct.mrs',
        'cn-ip': 'mihomo/cn-ip.mrs',
    },
    'srs': {
        'private': 'sing-box/private.srs',
        'reject': 'sing-box/reject.srs',
        'proxy': 'sing-box/proxy.srs',
        'direct': 'sing-box/direct.srs',
        'cn-ip': 'sing-box/cn-ip.srs',
        'webrtc-guard': 'sing-box/webrtc-guard.srs',
        'non-cn-ip': 'sing-box/non-cn-ip.srs',
    },
    'domain-set': {
        'private': 'private.domains',
        'reject': 'reject.domains',
        'proxy': 'proxy.domains',
        'direct': 'direct.domains',
    },
}
COMPANION_FILES = {
    'mrs': ('mihomo/webrtc-guard.yaml',),
    'srs': (),
    'domain-set': ('surge/private.list', 'surge/proxy.list', 'surge/direct.list', 'surge/cn-ip.list', 'surge/webrtc-guard.list'),
}
# END GENERATED RULE CATALOG
BASE = 'https://raw.githubusercontent.com/' + REPO + '/'
LIMIT = 16 * 1024 * 1024
SHA = re.compile(r'^[a-f0-9]{40}$')
DIGEST = re.compile(r'^[a-f0-9]{64}$')
DOWNLOAD_FORMATS = (*FORMATS, *VARIANT_FILES, 'all')
GENERATION = re.compile(r'[a-f0-9]{40}-(' + '|'.join(map(re.escape, DOWNLOAD_FORMATS)) + ')')
STAGE = re.compile(r'\.stage-[a-f0-9]{16}')


def optional_resources(fmt, files):
    if fmt in VARIANT_FILES:
        return []  # These profiles include all companions as required files.
    formats = FORMATS if fmt == 'all' else (fmt,)
    return [name for f in formats for name in OPTIONAL_FILES[f] if name in files]


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


def is_link(path):
    if os.name != 'nt':
        return path.is_symlink()
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False


@contextmanager
def locked(root):
    if is_link(root): raise ValueError('cache_symlink_rejected')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.lock'
    if is_link(lock): raise ValueError('cache_symlink_rejected')
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
    if is_link(p): raise ValueError('cache_symlink_rejected')
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'current': None, 'previous': None}


def directory(root, generation):
    if not isinstance(generation, str) or not GENERATION.fullmatch(generation):
        raise ValueError('invalid_cache_generation')
    base = root / 'generations'
    path = base / generation
    if is_link(base) or is_link(path): raise ValueError('cache_symlink_rejected')
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
    return date


def cached_publication(path):
    manifest = path / 'manifest.json'
    if is_link(manifest): raise ValueError('cache_symlink_rejected')
    value = json.loads(manifest.read_bytes())
    return value, validate_manifest(value)


def verify(root, generation):
    path = directory(root, generation)
    meta_path = path / 'cache.json'
    if is_link(meta_path): raise ValueError('cache_symlink_rejected')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    m, published = cached_publication(path)
    age = (datetime.now(timezone.utc) - published).total_seconds()
    expected = meta['files']
    # Caches written before the helper file existed hold only the rule files; both stay valid.
    if not isinstance(expected, list) or not set(selected(generation.split('-', 1)[1])) <= set(expected) or not set(expected) <= set(m['files']):
        raise ValueError('cache_inventory_invalid')
    optional = optional_resources(generation.split('-', 1)[1], m['files'])
    if meta.get('schema_version') == 2 and not set(optional) <= set(expected):
        raise ValueError('cache_inventory_invalid')
    for name in expected:
        p = path / name
        if is_link(p.parent) or is_link(p) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != m['files'][name]:
            raise ValueError('cached_file_corrupt')
    return {'generation': generation, 'directory': str(path.resolve()), 'age_seconds': round(age),
            'stale': age > 172800, 'files': expected,
            'missing_optional_resources': sorted(set(optional) - set(expected))}


def selected(fmt):
    if fmt in VARIANT_FILES:
        return ['index.json', *VARIANT_FILES[fmt].values(), *COMPANION_FILES[fmt]]
    formats = FORMATS if fmt == 'all' else (fmt,)
    return ['index.json'] + [name for f in formats for name in REQUIRED_FILES[f]]


def check_variant_index(fmt, index, files):
    if fmt not in VARIANT_FILES:
        return
    variants = index.get('format_variants')
    if not isinstance(variants, list) or not all(isinstance(row, dict) for row in variants):
        raise ValueError('format_not_advertised:' + fmt)
    rows = [row for row in variants if row.get('format') == fmt]
    expected = VARIANT_FILES[fmt]
    if len(rows) != len(expected) or {row.get('id'): row.get('path') for row in rows} != expected:
        raise ValueError('format_index_mismatch:' + fmt)
    if any(row.get('sha256') != files[row['path']] for row in rows):
        raise ValueError('format_index_digest_mismatch:' + fmt)


def remove_owned(path, *, formerly_referenced=False, stage_record=None):
    """Remove only a known cache layout, preserving unexpected entries and links."""
    try:
        if is_link(path.parent) or is_link(path) or not path.is_dir(): return
        record = path / 'cache.json'
        meta = stage_record
        if meta is None:
            if is_link(record) or not record.is_file() or record.stat().st_size > 16 * 1024: return
            meta = json.loads(record.read_bytes())
        if not isinstance(meta, dict) or meta.get('schema_version') not in (None, 2): return
        if 'stage' not in meta and 'generation' not in meta:
            # Old writers had no ownership marker. Only the pointer identifies their caches.
            if not formerly_referenced: return
            generation = path.name
        else:
            generation, stage = meta.get('generation'), meta.get('stage')
            if not isinstance(stage, str) or not STAGE.fullmatch(stage) or path.name not in (stage, generation):
                return
        if not isinstance(generation, str) or not GENERATION.fullmatch(generation): return
        fmt = generation.split('-', 1)[1]
        inventory = meta.get('files')
        if not isinstance(inventory, list) or not all(isinstance(name, str) for name in inventory): return
        required = set(selected(fmt))
        if set(inventory) != required.union(optional_resources(fmt, inventory)): return
        files = {'manifest.json', *inventory}
        folders = {name.split('/')[0] for name in inventory if '/' in name}
        pending, removable = [path], []
        for folder in pending:
            for item in folder.iterdir():
                name = item.relative_to(path).as_posix()
                if is_link(item): return
                if name in folders and item.is_dir():
                    pending.append(item)
                elif name in files and item.is_file():
                    removable.append(item)
                elif item != record or not item.is_file():
                    return
        for item in removable: item.unlink()
        for folder in reversed(pending[1:]): folder.rmdir()
        record.unlink(missing_ok=True)
        path.rmdir()
    except (OSError, ValueError, RecursionError):
        # A cleanup failure must not undo a committed pointer. Later syncs retry marked caches.
        return


def cleanup_orphans(root, state):
    base = root / 'generations'
    if is_link(base): raise ValueError('cache_symlink_rejected')
    if not base.exists(): return
    keep = {state['current'], state['previous'], state.get('held')}
    for path in base.iterdir():
        if path.name not in keep and (GENERATION.fullmatch(path.name) or STAGE.fullmatch(path.name)):
            remove_owned(path)


def operate(command, root, fmt='all', fetch=get, release_sha=None):
    if release_sha is not None:
        if command != 'sync':
            raise ValueError('release_sha_requires_sync')
        if not isinstance(release_sha, str) or not SHA.fullmatch(release_sha):
            raise ValueError('invalid_release_sha')
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
            swapped = {'current': state['previous'], 'previous': state['current']}
            if held != swapped['current']:
                swapped['held'] = state['current']
            atomic(root / 'current.json', swapped)
            return {'status': 'rolled_back', **result}
        if state['current']:
            verify(root, state['current'])
        cleanup_orphans(root, state)
        sha = release_sha
        if sha is None:
            sha = json.loads(fetch('https://api.github.com/repos/' + REPO + '/commits/release'))['sha']
        if not isinstance(sha, str) or not SHA.fullmatch(sha): raise ValueError('invalid_release_sha')
        raw = fetch(BASE + sha + '/manifest.json'); m = json.loads(raw)
        published = validate_manifest(m)
        age = (datetime.now(timezone.utc) - published).total_seconds()
        if not -300 <= age <= 172800: raise ValueError('publication_stale_or_future')
        generation = sha + '-' + fmt
        if state['current'] == generation:
            return {'status': 'unchanged', **verify(root, generation)}
        if held:
            held_path = directory(root, held)
            if sha == held.split('-', 1)[0] or published <= cached_publication(held_path)[1]:
                return {'status': 'held', 'held_generation': held, **verify(root, state['current'])}
        dest = directory(root, generation)
        dest.parent.mkdir(exist_ok=True)
        # Not mkdtemp: its 0700 would stay on the published generation directory.
        stage = dest.parent / ('.stage-' + secrets.token_hex(8))
        names = selected(fmt) + optional_resources(fmt, m['files'])
        if not set(names) <= m['files'].keys():
            raise ValueError('format_files_unavailable:' + fmt)
        meta = {'schema_version': 2, 'files': names, 'generation': generation, 'stage': stage.name}
        stage.mkdir()
        created_record = False
        uncommitted_dest = False
        try:
            with (stage / 'cache.json').open('x', encoding='utf-8') as record:
                created_record = True
                json.dump(meta, record)
            (stage / 'manifest.json').write_bytes(raw)
            for name in names:
                data = fetch(BASE + sha + '/' + name)
                if not data or len(data) > LIMIT or hashlib.sha256(data).hexdigest() != m['files'][name]:
                    raise ValueError('resource_hash_mismatch')
                p = stage / name; p.parent.mkdir(exist_ok=True); p.write_bytes(data)
            index = json.loads((stage / 'index.json').read_bytes())
            if not isinstance(index, dict) or index.get('schema_version') != 1 or index.get('generated_at_utc') != m['generated_at_utc']:
                raise ValueError('index_generation_mismatch')
            check_variant_index(fmt, index, m['files'])
            if dest.exists(): verify(root, generation)
            else:
                os.replace(stage, dest)
                uncommitted_dest = True
            result = verify(root, generation)
            atomic(root / 'current.json', {'current': generation, 'previous': state['current']})
            uncommitted_dest = False
            old = state['previous']
            if old and old not in (generation, state['current']):
                remove_owned(dest.parent / old, formerly_referenced=True)
            return {'status': 'updated', **result}
        finally:
            if created_record:
                remove_owned(stage, stage_record=meta)
            else:
                try: stage.rmdir()
                except OSError: pass
            # A process can stop between the two renames. Never delete a referenced generation.
            if uncommitted_dest and generation not in pointer(root).values():
                remove_owned(dest)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('sync', 'verify', 'status', 'rollback'))
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--format', choices=DOWNLOAD_FORMATS, default='all')
    p.add_argument('--release-sha', help='sync only: verified full release SHA; all data checks still apply')
    a = p.parse_args()
    try:
        options = {'release_sha': a.release_sha} if a.release_sha is not None else {}
        result = operate(a.command, a.output.absolute(), a.format, **options)
        print(json.dumps(result)); return 0
    except (ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as e:
        print(json.dumps({'status': 'failed', 'error': str(e), 'current_preserved': True})); return 1


if __name__ == '__main__': sys.exit(main())
