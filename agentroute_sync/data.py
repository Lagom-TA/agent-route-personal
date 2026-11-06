"""Public-data-only downloader. No client credentials or local proxy settings."""
from datetime import datetime, timezone
from pathlib import Path
import gzip
import ipaddress
import json
import os
import re
import subprocess
import tempfile
import time
import http.client
import urllib.error
import urllib.request

from .common import SHA, REPO, atomic_bytes, atomic_json, digest

UPSTREAM = 'ryuu-restart/agent-route'
IDS = ('private', 'reject', 'proxy', 'direct', 'cn-ip')
LIMIT = 16 * 1024 * 1024
CORE_VERSION = 'v1.19.33'
CORE_ASSET = 'mihomo-linux-amd64-v1-v1.19.33.gz'
CORE_DIGEST = '8ec92e7b2fdc6b853ba00156bab7e4e965c8b0d843b8c4ac8ab98795f02ad524'
DOCS = ('AGENTS.md', 'docs/CLIENTS.md', 'docs/DNS-WEBRTC.md', 'docs/SYNC.md',
        'scripts/sync_rules.py', 'examples/full/mihomo.yaml', '.github/workflows/run.yml')

def _fetch_once(url, limit=LIMIT):
    if not url.startswith(('https://api.github.com/', 'https://raw.githubusercontent.com/', 'https://github.com/MetaCubeX/mihomo/releases/download/')):
        raise ValueError('download_origin_rejected')
    request = urllib.request.Request(url, headers={'User-Agent': 'AgentRoutePersonal/1', 'Accept': 'application/vnd.github+json' if 'api.github.com' in url else '*/*'})
    # Only GitHub-hosted runners may use the ephemeral workflow token.
    token = os.environ.get('GITHUB_TOKEN') if os.environ.get('GITHUB_ACTIONS') == 'true' else None
    if token and url.startswith('https://api.github.com/'):
        request.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(request, timeout=30) as response:
        final = response.url
        allowed = ('https://api.github.com/', 'https://raw.githubusercontent.com/', 'https://github.com/MetaCubeX/mihomo/releases/download/', 'https://release-assets.githubusercontent.com/')
        if not final.startswith(allowed):
            raise ValueError('redirect_origin_rejected')
        data = response.read(limit + 1)
        if response.status != 200 or not data or len(data) > limit:
            raise ValueError('download_invalid')
        if response.headers.get('Content-Length') and int(response.headers['Content-Length']) != len(data):
            raise ValueError('download_truncated')
        return data

def fetch(url,limit=LIMIT):
    for attempt in range(3):
        try:
            return _fetch_once(url,limit)
        except urllib.error.HTTPError as error:
            if error.code not in (429,500,502,503,504) or attempt==2:raise
        except (urllib.error.URLError,OSError,http.client.HTTPException):
            if attempt==2:raise
        time.sleep(attempt+1)

def resolve(repo, branch, get=fetch):
    if not REPO.fullmatch(repo) or branch not in ('master', 'release', 'rules', 'upstream-docs', 'main'):
        raise ValueError('repository_or_branch_invalid')
    result = json.loads(get('https://api.github.com/repos/' + repo + '/git/ref/heads/' + branch))
    value = result.get('object', {}).get('sha')
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('commit_invalid')
    return value

def payload(data):
    text = data.decode('utf-8')
    values = []
    seen = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line == 'payload:' and not seen:
            seen = True
            continue
        if not seen or not line.startswith('- '):
            raise ValueError('unexpected_rule_structure')
        value = line[2:].strip()
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        elif value.startswith('"'):
            value = json.loads(value)
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError('invalid_rule_value')
        values.append(value)
    if not seen or not values:
        raise ValueError('empty_rules')
    if len(set(values)) != len(values):
        raise ValueError('duplicate_rules')
    return values

def verify(directory, fresh=True, now=None):
    root = Path(directory)
    if root.is_symlink():
        raise ValueError('cache_symlink_rejected')
    manifest = json.loads((root / 'manifest.json').read_text())
    index = json.loads((root / 'index.json').read_text())
    if manifest.get('schema_version') != 1 or index.get('schema_version') != 1:
        raise ValueError('schema_version_unsupported')
    if manifest.get('scope') != 'domestic_direct_and_adblock' or index.get('scope') != 'public_routing_data_only':
        raise ValueError('rule_scope_invalid')
    stamp = datetime.fromisoformat(manifest['generated_at_utc'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or index.get('generated_at_utc') != manifest['generated_at_utc']:
        raise ValueError('generation_mismatch')
    age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
    if fresh and not -300 <= age <= 172800:
        raise ValueError('publication_stale_or_future')
    hashes = manifest['files']
    if not isinstance(hashes,dict) or any(not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',name) or any(p in ('.','..') for p in name.split('/')) or not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value) for name,value in hashes.items()):
        raise ValueError('manifest_path_or_digest_invalid')
    inventory = {'index.json': hashes['index.json']}
    datasets = {entry['id']: entry for entry in index['datasets']}
    if set(datasets) != set(IDS):
        raise ValueError('dataset_inventory_invalid')
    counts = {}
    for name in IDS:
        expected_path = 'mihomo/' + name + '.yaml'
        entry = datasets[name]
        resource = entry['resources']['mihomo']
        if resource['path'] != expected_path or resource['sha256'] != hashes[expected_path]:
            raise ValueError('resource_identity_mismatch')
        if entry['mihomo_behavior'] != ('ipcidr' if name == 'cn-ip' else 'domain'):
            raise ValueError('behavior_mismatch')
        inventory[expected_path] = hashes[expected_path]
    for path, expected in inventory.items():
        file = root / path
        if file.is_symlink() or file.parent.is_symlink() or not file.is_file():
            raise ValueError('unsafe_cache_file')
        raw = file.read_bytes()
        if not raw or len(raw) > LIMIT or digest(raw) != expected:
            raise ValueError('resource_hash_mismatch')
        if path.startswith('mihomo/'):
            name = Path(path).stem
            values = payload(raw)
            if len(values) != datasets[name]['resources']['mihomo']['entries']:
                raise ValueError('entry_count_mismatch')
            if name == 'cn-ip':
                for value in values:
                    ipaddress.ip_network(value)
            else:
                if any('/' in value or ',' in value or ':' in value for value in values):
                    raise ValueError('domain_rule_invalid')
            counts[name] = len(values)
    return {'counts': counts, 'generated_at_utc': manifest['generated_at_utc'], 'age_seconds': round(age), 'stale': age > 172800}

def download(repo, sha, directory, get=fetch, fresh=True):
    if not REPO.fullmatch(repo) or not SHA.fullmatch(sha):
        raise ValueError('download_identity_invalid')
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    base = 'https://raw.githubusercontent.com/' + repo + '/' + sha + '/'
    raw = get(base + 'manifest.json')
    manifest = json.loads(raw)
    if not isinstance(manifest.get('files'), dict):
        raise ValueError('manifest_files_invalid')
    atomic_bytes(root / 'manifest.json', raw)
    names = ['index.json'] + ['mihomo/' + name + '.yaml' for name in IDS]
    names += [p for p in manifest['files'] if p in ('LICENSE', 'NOTICE.md', 'sources.json') or (p.startswith('licenses/') and re.fullmatch(r'licenses/[A-Za-z0-9_.-]+', p))]
    for name in names:
        data = get(base + name)
        if digest(data) != manifest['files'][name]:
            raise ValueError('resource_hash_mismatch')
        atomic_bytes(root / name, data)
    result = verify(root, fresh=fresh)
    if repo != UPSTREAM:
        provenance = json.loads(get(base + 'provenance.json'))
        if provenance.get('upstream_repository') != UPSTREAM or not SHA.fullmatch(provenance.get('upstream_release', '')):
            raise ValueError('mirror_provenance_invalid')
        if provenance.get('generated_at_utc') != result['generated_at_utc']:
            raise ValueError('mirror_generation_mismatch')
        atomic_json(root / 'provenance.json', provenance)
    return result

def native_validate(core, directory):
    root = Path(directory).resolve()
    verify(root, fresh=False)
    with tempfile.TemporaryDirectory(prefix='agentroute-native-') as work:
        work = Path(work)
        for name in IDS:
            behavior = 'ipcidr' if name == 'cn-ip' else 'domain'
            result = subprocess.run([str(core), 'convert-ruleset', behavior, 'yaml', str(root / 'mihomo' / (name + '.yaml')), str(work / (name + '.mrs'))], capture_output=True, timeout=45)
            if result.returncode:
                raise ValueError('native_rule_compile_failed:' + name)
        config = {'mode': 'rule', 'tun': {'enable': False}, 'dns': {'enable': False},
                  'rule-providers': {name: {'type': 'file', 'behavior': 'ipcidr' if name == 'cn-ip' else 'domain', 'path': 'mihomo/' + name + '.yaml', 'format': 'yaml'} for name in IDS},
                  'rules': ['RULE-SET,' + name + ',REJECT' for name in IDS] + ['MATCH,REJECT']}
        atomic_json(root / 'native-config.json', config)
        result = subprocess.run([str(core), '-t', '-d', str(root), '-f', str(root / 'native-config.json')], capture_output=True, timeout=45)
        if result.returncode:
            raise ValueError('native_config_check_failed')

def install_ci_core(target, get=fetch):
    url = 'https://github.com/MetaCubeX/mihomo/releases/download/' + CORE_VERSION + '/' + CORE_ASSET
    archive = get(url, limit=40 * 1024 * 1024)
    if digest(archive) != CORE_DIGEST:
        raise ValueError('official_core_digest_mismatch')
    atomic_bytes(target, gzip.decompress(archive), mode=0o700)
    return Path(target)
