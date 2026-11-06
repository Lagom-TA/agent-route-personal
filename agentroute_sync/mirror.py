"""Prepare public rule/doc snapshots and publish ordinary Git commits."""
from pathlib import Path
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile

from .common import atomic_bytes, atomic_json, digest, run_checked
from .data import UPSTREAM, IDS, DOCS, fetch, resolve, download, verify, native_validate, install_ci_core

def doc_snapshot_path(name):
    if name not in DOCS:raise ValueError('untracked_document')
    # Inert text snapshots: never publish upstream code as our executable workflow.
    return 'snapshots/source-' + name.replace('/', '__') + '.txt'

def public_files(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    names = ['manifest.json', 'index.json', 'provenance.json'] + ['mihomo/' + n + '.yaml' for n in IDS]
    names += [n for n in manifest['files'] if n in ('LICENSE', 'NOTICE.md', 'sources.json') or re.fullmatch(r'licenses/[A-Za-z0-9_.-]+',n)]
    return [n for n in names if (root / n).is_file()]

def prepare(out, core=None):
    out = Path(out)
    release = resolve(UPSTREAM, 'release')
    master = resolve(UPSTREAM, 'master')
    data = out / 'data'
    result = download(UPSTREAM, release, data)
    if core is None:
        core = install_ci_core(out / 'tools/mihomo')
    native_validate(core, data)
    atomic_json(data / 'provenance.json', {'schema_version': 1, 'upstream_repository': UPSTREAM,
                'upstream_release': release, 'upstream_master': master,
                'generated_at_utc': result['generated_at_utc'], 'publisher_version': 1})
    docs = out / 'docs'
    hashes = {}
    for name in DOCS:
        raw = fetch('https://raw.githubusercontent.com/' + UPSTREAM + '/' + master + '/' + name)
        atomic_bytes(docs / doc_snapshot_path(name), raw)
        hashes[name] = digest(raw)
    atomic_json(docs / 'provenance.json', {'schema_version': 1, 'upstream_master': master, 'files': hashes,
                                        'storage':{name:doc_snapshot_path(name) for name in DOCS}})
    return {'upstream_release': release, 'upstream_master': master, **result}

def publish_branch(repo, branch, source):
    source = Path(source).resolve()
    if branch == 'rules':
        verify(source)
        names = public_files(source)
    elif branch == 'upstream-docs':
        meta = json.loads((source / 'provenance.json').read_text())
        names = [doc_snapshot_path(name) for name in DOCS] + ['provenance.json']
        if set(meta['files']) != set(DOCS):
            raise ValueError('doc_inventory_invalid')
        if meta.get('storage')!={name:doc_snapshot_path(name) for name in DOCS}:
            raise ValueError('doc_storage_invalid')
        for name, expected in meta['files'].items():
            if digest((source / doc_snapshot_path(name)).read_bytes()) != expected:
                raise ValueError('doc_hash_mismatch')
    else:
        raise ValueError('publish_branch_invalid')
    from .common import REPO
    if not REPO.fullmatch(repo):
        raise ValueError('repository_invalid')
    env = os.environ.copy()
    token = env.get('GITHUB_TOKEN') if env.get('GITHUB_ACTIONS') == 'true' else None
    if token:
        env['GIT_CONFIG_COUNT'] = '1'
        env['GIT_CONFIG_KEY_0'] = 'http.https://github.com/.extraheader'
        env['GIT_CONFIG_VALUE_0'] = 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
    def git(args, cwd):
        return run_checked(['git'] + args, timeout=120, cwd=cwd, env=env)
    with tempfile.TemporaryDirectory(prefix='agentroute-publish-') as work:
        git(['init', '-q'], work)
        git(['remote', 'add', 'origin', 'https://github.com/' + repo + '.git'], work)
        refs = git(['ls-remote', 'origin', 'refs/heads/' + branch], work).strip()
        if refs:
            git(['fetch', '-q', '--depth=1', 'origin', branch], work)
            git(['checkout', '-q', '-b', branch, 'FETCH_HEAD'], work)
            old = Path(work) / 'provenance.json'
            key = 'upstream_release' if branch == 'rules' else 'upstream_master'
            if old.exists() and json.loads(old.read_text()).get(key) == json.loads((source / 'provenance.json').read_text()).get(key):
                return {'branch': branch, 'status': 'unchanged'}
        else:
            git(['checkout', '-q', '--orphan', branch], work)
        for name in names:
            target = Path(work) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        git(['config', 'user.name', 'github-actions[bot]'], work)
        git(['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], work)
        git(['add', '--'] + names, work)
        git(['commit', '-q', '-m', 'Mirror verified AgentRoute ' + branch], work)
        # Ordinary fast-forward push: never replace or force-rewrite published history.
        git(['push', '-q', 'origin', 'HEAD:refs/heads/' + branch], work)
        return {'branch': branch, 'status': 'published', 'commit': git(['rev-parse', 'HEAD'], work).strip()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--out', type=Path, required=True); p.add_argument('--core')
    p = sub.add_parser('publish'); p.add_argument('--repo', required=True); p.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.out, args.core)
    else:
        result = [publish_branch(args.repo, 'rules', args.out / 'data'), publish_branch(args.repo, 'upstream-docs', args.out / 'docs')]
    print(json.dumps(result))

if __name__ == '__main__':
    main()
