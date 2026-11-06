from pathlib import Path
import copy
import json
import re
import subprocess

from .common import SHA, identity

PREFIX = '🌐固定出口 · '
MARKER = '// AGENTROUTE-PERSONAL-MANAGED-V1'
OLD_MARKER = '// AgentRoute 2026-11-06: preserve transport chains and manual selector.'

def base_script(source):
    if MARKER in source:
        source = source.split(MARKER, 1)[0]
    elif OLD_MARKER in source:
        source = source.split(OLD_MARKER, 1)[0]
    else:
        raise ValueError('unrecognized_extension_requires_review')
    if source.count('function legacyMain(config)') != 1 or source.count('const newExit = ') != 1:
        raise ValueError('unrecognized_legacy_generator')
    return source

def extract_exit(source):
    line = next((line for line in source.splitlines() if line.startswith('const newExit = ')), None)
    if not line or not line.endswith(';'):
        raise ValueError('exit_spec_unavailable')
    return json.loads(line[len('const newExit = '):-1])

def egress_revision(spec):
    return identity(spec)

def strip_markers(config):
    result = copy.deepcopy(config)
    for node in result.get('proxies', []):
        node.pop('agentroute-generated', None)
    return result

def render(source, config, generation, ownership, node_binary, new_exit=None, protected_hosts=()):
    if not SHA.fullmatch(generation):
        raise ValueError('generation_invalid')
    legacy = base_script(source)
    if new_exit is not None:
        validate_exit(new_exit)
        legacy = re.sub(r'^const newExit = .*;$', 'const newExit = ' + json.dumps(new_exit, ensure_ascii=False) + ';', legacy, count=1, flags=re.M)
        legacy = legacy.replace("{name, type: 'socks5', udp: false, 'dialer-proxy': p.name}", "{name, type: newExit.type, udp: false, 'dialer-proxy': p.name}")
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.[a-z]{2,}',host) for host in protected_hosts):
        raise ValueError('protected_host_must_be_exact_dns_name')
    binding = {'generation': generation, 'ownedAliases': sorted(ownership), 'protectedHosts':list(protected_hosts), 'schema': 1}
    script = legacy.rstrip() + '\n\n' + MARKER + '\nconst agentrouteManaged = ' + json.dumps(binding, ensure_ascii=False) + ';\n' + Path(__file__).with_name('extension.js').read_text()
    js = "const fs=require('fs'),vm=require('vm');const input=JSON.parse(fs.readFileSync(0,'utf8'));const context={};vm.createContext(context);vm.runInContext(input.script,context,{timeout:3000});process.stdout.write(JSON.stringify(context.main(input.config)));"
    result = subprocess.run([str(node_binary), '-e', js], input=json.dumps({'script':script, 'config':config}, ensure_ascii=False), capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError('extension_render_failed')
    candidate = json.loads(result.stdout)
    graph_check(candidate)
    return script, candidate

def graph_check(config):
    nodes = config.get('proxies', [])
    by_name = {p['name']:p for p in nodes}
    if len(by_name) != len(nodes):
        raise ValueError('duplicate_proxy_name')
    for p in nodes:
        seen = set()
        cursor = p
        while cursor.get('dialer-proxy'):
            if cursor['name'] in seen:
                raise ValueError('proxy_cycle')
            seen.add(cursor['name'])
            name = cursor['dialer-proxy']
            if name not in by_name:
                raise ValueError('proxy_dialer_missing')
            cursor = by_name[name]
        if p.get('agentroute-generated'):
            if not p['name'].startswith(PREFIX) or p['dialer-proxy'] != p['name'][len(PREFIX):] or by_name[p['dialer-proxy']].get('agentroute-generated'):
                raise ValueError('nested_generated_chain')
    for group in config.get('proxy-groups', []):
        if group['name'] == '中转节点':
            members = group.get('proxies', [])
            if not members or any(n not in by_name or not by_name[n].get('agentroute-generated') for n in members):
                raise ValueError('fixed_group_escape')

def validate_exit(spec):
    if spec.get('type') not in ('socks5', 'http'):
        raise ValueError('unsupported_exit_protocol_requires_review')
    if not isinstance(spec.get('server'), str) or not spec['server'] or not isinstance(spec.get('port'), int) or not 1 <= spec['port'] <= 65535:
        raise ValueError('invalid_exit_address')
    if spec.get('udp') is True or spec.get('skip-cert-verify') is True or 'dialer-proxy' in spec:
        raise ValueError('unsafe_exit_option')
