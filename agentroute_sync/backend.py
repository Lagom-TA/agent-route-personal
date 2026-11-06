from pathlib import Path
from urllib.parse import quote
import concurrent.futures
import copy
import http.client
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import uuid

from .common import atomic_json, digest, identity, yaml_load
from .adapter import extract_exit, graph_check, strip_markers
from .data import IDS, payload, verify

def evaluate_script(source, config, node):
    js = "const fs=require('fs'),vm=require('vm');let v=JSON.parse(fs.readFileSync(0,'utf8')),c={};vm.createContext(c);vm.runInContext(v.source,c,{timeout:3000});process.stdout.write(JSON.stringify(c.main(v.config)));"
    r = subprocess.run([node, '-e', js], input=json.dumps({'source':source,'config':config},ensure_ascii=False),capture_output=True,text=True,timeout=10)
    if r.returncode:
        raise ValueError('restore_render_failed')
    return json.loads(r.stdout)

class Backend:
    def __init__(self, settings):
        self.settings = settings
        self.root = Path(settings['core_home'])
        self.extension = Path(settings['extension'])
        self.core = settings['core_binary']
        self.node = settings['node_binary']
        self.group = settings.get('group','中转节点')

    def api(self, method, endpoint, data=None, timeout=12):
        timeout=min(timeout,self.settings.get('control_timeout',timeout))
        cfg = yaml_load(self.root / 'clash-verge.yaml')
        paths = ['/var/run/clash-verge-service/users/%s/verge-mihomo.sock' % os.getuid(), cfg.get('external-controller-unix','')]
        sock = next((p for p in paths if p and Path(p).exists()), None)
        if not sock:
            raise RuntimeError('core_control_unavailable')
        class Conn(http.client.HTTPConnection):
            def connect(inner):
                inner.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                inner.sock.settimeout(timeout); inner.sock.connect(sock)
        c = Conn('localhost',timeout=timeout)
        headers = {'Authorization':'Bearer '+str(cfg.get('secret',''))}
        if data is not None: headers['Content-Type']='application/json'
        c.request(method,endpoint,body=None if data is None else json.dumps(data,ensure_ascii=False).encode(),headers=headers)
        r=c.getresponse();raw=r.read();status=r.status;c.close()
        if status>=300:
            private=Path(self.settings.get('diagnostic_home',Path.home()/'AgentRoute/automation'))
            atomic_json(private/'api-errors'/(uuid.uuid4().hex+'.json'),{'method':method,'endpoint':endpoint,'status':status,'response':raw.decode(errors='replace'),'time':time.time()})
            raise RuntimeError('core_api_failed:'+str(status))
        return json.loads(raw) if raw else None

    def capture(self):
        profiles=yaml_load(self.root/'profiles.yaml')
        profile=next(x for x in profiles['items'] if x['uid']==profiles['current'])
        runtime=self.api('GET','/configs'); proxies=self.api('GET','/proxies')['proxies']
        selected={k:v['now'] for k,v in proxies.items() if v.get('type')=='Selector' and k!='GLOBAL'}
        config=yaml_load(self.root/'clash-verge.yaml')
        source=self.extension.read_text()
        return {'config':config,'source':source,'runtime':runtime,'selected':selected,
                'core_version':self.api('GET','/version')['version'],'profile':profile['uid'],
                'raw_digest':digest((self.root/'profiles'/profile['file']).read_bytes()),
                'extension_digest':digest(source.encode()),'exit':extract_exit(source),
                'owned_aliases':proxies[self.group]['all']}

    @staticmethod
    def signature(snapshot):
        return identity({k:snapshot[k] for k in ['config','selected','core_version','profile','raw_digest','extension_digest']})

    def ready(self, snapshot):
        if snapshot['core_version'] != self.settings['core_version']:
            raise ValueError('core_version_changed_requires_review')
        if snapshot['runtime']['mode']!='rule' or not snapshot['runtime']['tun']['enable']:
            raise ValueError('rule_mode_and_tun_required')
        if self.group not in snapshot['selected']:
            raise ValueError('fixed_group_missing')
        if self.settings.get('profile_uid') and snapshot['profile']!=self.settings['profile_uid']:
            raise ValueError('configuration_source_changed_requires_review')
        native=subprocess.run([self.core,'-v'],capture_output=True,text=True,timeout=5)
        if not re.search(r'\b'+re.escape(self.settings['core_version'])+r'\b',native.stdout):
            raise ValueError('bundled_core_version_changed_requires_review')

    def native_check(self, candidate, directory):
        p=Path(directory)/'candidate-native.json';atomic_json(p,candidate)
        r=subprocess.run([self.core,'-t','-d',str(self.root),'-f',str(p)],capture_output=True,timeout=30)
        atomic_json(Path(directory)/'native-check.json',{'exit':r.returncode})
        if r.returncode: raise ValueError('native_candidate_check_failed')
        runtime=self.runtime_candidate(candidate)
        runtime_path=Path(directory)/'runtime-native.json';atomic_json(runtime_path,runtime)
        result=subprocess.run([self.core,'-t','-d',str(self.root),'-f',str(runtime_path)],capture_output=True,timeout=30)
        atomic_json(Path(directory)/'runtime-native-check.json',{'exit':result.returncode})
        if result.returncode:raise ValueError('native_runtime_candidate_check_failed')

    def runtime_candidate(self, candidate):
        runtime=copy.deepcopy(candidate)
        providers=runtime.get('rule-providers',{})
        local=[n for n in IDS if providers.get('agentroute-'+n,{}).get('type')=='file']
        if not local:return runtime
        if set(local)!=set(IDS):raise ValueError('partial_managed_file_generation')
        generations=set()
        for name in IDS:
            value=providers['agentroute-'+name]['path']
            match=re.fullmatch(r'\./rules/agent-route/generations/([a-f0-9]{40})/mihomo/'+name+r'\.yaml',value)
            if not match:raise ValueError('managed_file_path_changed')
            generations.add(match.group(1))
        if len(generations)!=1:raise ValueError('mixed_runtime_generation')
        root=self.root/'rules/agent-route/generations'/next(iter(generations))
        verify(root,fresh=False)
        for name in IDS:
            providers['agentroute-'+name]={'type':'inline','behavior':'ipcidr' if name=='cn-ip' else 'domain',
                                          'payload':payload((root/'mihomo'/(name+'.yaml')).read_bytes())}
        return runtime

    def apply(self, candidate, selected):
        # Service mode has its own protected -d directory. GUI reloads stage local
        # files through the app's owner session; direct API reloads must carry data.
        runtime=self.runtime_candidate(candidate)
        self.api('PUT','/configs',{'payload':json.dumps(runtime,ensure_ascii=False)},timeout=20)
        # Generated config is also kept on disk for source/compatibility checks.
        atomic_json(self.root/'clash-verge.yaml',candidate)
        current=self.api('GET','/proxies')['proxies']
        for group,name in selected.items():
            if group not in current or name not in current[group].get('all',[]):
                raise ValueError('selected_node_disappeared')
            if current[group].get('now')!=name:
                self.api('PUT','/proxies/'+quote(group,safe=''),{'name':name})

    def loaded(self, candidate, counts):
        actual=self.api('GET','/providers/rules')['providers']
        private=Path(self.settings.get('diagnostic_home',Path.home()/'AgentRoute/automation'))
        atomic_json(private/'last-loaded-counts.json',{'actual':{n:actual.get('agentroute-'+n,{}).get('ruleCount') for n in IDS},'expected':counts,'time':time.time()})
        for name in IDS:
            if actual.get('agentroute-'+name,{}).get('ruleCount')!=counts[name]:
                raise ValueError('actual_rules_not_loaded:'+name)
        current=yaml_load(self.root/'clash-verge.yaml')
        for name in IDS:
            key='agentroute-'+name
            if current['rule-providers'][key]!=candidate['rule-providers'][key]:
                raise ValueError('provider_binding_changed')

    def curl(self, name, url, expected_ip=None, proxy=None, statuses=(200,), media=False):
        attempts=[]
        for attempt in range(2):
            result=self._curl_once(name,url,expected_ip,proxy,statuses,media)
            attempts.append(dict(result))
            if result['passed'] or result['curl_exit'] not in (7,28,35,52,56):break
            if attempt==0:time.sleep(1)
        result['attempts']=attempts
        return result

    def _curl_once(self, name, url, expected_ip=None, proxy=None, statuses=(200,), media=False):
        with tempfile.TemporaryDirectory(prefix='agentroute-http-') as work:
            out=Path(work)/'body'
            args=['/usr/bin/curl','--disable','--noproxy','' if proxy else '*','-4','--http1.1','-sS','--connect-timeout','6','--max-time','14']
            if proxy: args+=['--proxy',proxy]
            if media: args+=['--range','0-1023']
            args += [url,'-o',str(out),'-w','%{http_code} %{ssl_verify_result}']
            r=subprocess.run(args,capture_output=True,text=True,timeout=18)
            parts=r.stdout.split();status=int(parts[0]) if parts and parts[0].isdigit() else 0
            tls=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else -1
            result={'probe':name,'curl_exit':r.returncode,'http':status,'tls_verify':tls}
            if expected_ip is not None:
                body=out.read_text(errors='replace') if out.exists() else ''
                value=next((s[3:] for s in body.splitlines() if s.startswith('ip=')),None)
                result['exit_matches']=value is not None and ipaddress.ip_address(value)==ipaddress.ip_address(expected_ip)
                result['observed_ip']=value
            result['passed']=r.returncode==0 and status in statuses and tls==0 and result.get('exit_matches',True)
            return result

    def health(self, expected_ip, rounds=2, proxy=None):
        runtime=self.api('GET','/configs')
        if runtime['mode']!='rule' or not runtime['tun']['enable']:
            return {'passed':False,'reason':'mode_or_tun_not_ready_no_direct_probe'}
        records=[];routes=[]
        for iteration in range(rounds):
            jobs=[('exit','https://www.cloudflare.com/cdn-cgi/trace',expected_ip,proxy,(200,),False),
                  ('domestic','https://www.baidu.com/',None,None,(200,),False),
                  ('chatgpt','https://chatgpt.com/robots.txt',None,proxy,(200,),False),
                  ('claude','https://claude.ai/robots.txt',None,proxy,(200,),False),
                  ('media','https://media.w3.org/2010/05/sintel/trailer.mp4',None,proxy,(200,206),True)]
            if proxy is None:
                jobs.append(('system-proxy-exit','https://www.cloudflare.com/cdn-cgi/trace',expected_ip,'http://127.0.0.1:'+str(self.settings['mixed_port']),(200,),False))
            for host in self.settings.get('protected_hosts',[]):
                jobs.append(('protected:'+host,'https://'+host+'/',None,proxy,tuple(range(200,500)),False))
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(self.curl,*args) for args in jobs]
                while not all(f.done() for f in futures):
                    try:
                        for connection in self.api('GET','/connections',timeout=3).get('connections',[]):
                            meta=connection.get('metadata',{});host=meta.get('host')
                            if host in self.settings.get('protected_hosts',[]) or host in ('www.cloudflare.com','www.baidu.com','chatgpt.com','claude.ai'):
                                value={'host':host,'inbound':meta.get('type'),'chains':connection.get('chains',[]),'rule':connection.get('rule'),'rule_payload':connection.get('rulePayload')}
                                if value not in routes:routes.append(value)
                    except Exception:
                        pass
                    time.sleep(.2)
                values=[f.result() for f in futures]
            records.extend(dict(v,round=iteration+1) for v in values)
            if not all(v['passed'] for v in values):
                return {'passed':False,'probes':records,'routes':routes}
            if iteration+1<rounds:time.sleep(2)
        violation=any(r['host'] in self.settings.get('protected_hosts',[]) and self.group not in r['chains'] for r in routes)
        return {'passed':not violation,'probes':records,'routes':routes,'protected_route_violation':violation,
                'protected_route_hosts_observed':sorted({r['host'] for r in routes if r['host'] in self.settings.get('protected_hosts',[])}) if proxy is None else [],
                'path':'main' if proxy is None else 'isolated-preview'}

    def current_exit_ip(self):
        with tempfile.TemporaryDirectory(prefix='agentroute-exit-') as work:
            p=Path(work)/'body'
            r=subprocess.run(['/usr/bin/curl','--disable','--noproxy','*','-4','-sS','--connect-timeout','6','--max-time','15','https://www.cloudflare.com/cdn-cgi/trace','-o',str(p)],capture_output=True,timeout=18)
            if r.returncode:raise ValueError('current_exit_probe_failed')
            value=next((l[3:] for l in p.read_text().splitlines() if l.startswith('ip=')),None)
            ipaddress.ip_address(value)
            return value

def rule_invariants(before, candidate, protected_hosts=()):
    old,new=strip_markers(before),strip_markers(candidate)
    for key in ['proxies','proxy-groups','tun','mode','ipv6','mixed-port','secret','sniffer']:
        if old.get(key)!=new.get(key):raise ValueError('preserved_field_changed:'+key)
    # Only provider transport/binding and ownership metadata change during rules updates.
    def without_local_rules(config):
        result=copy.deepcopy(config)
        allowed=set()
        for host in protected_hosts:
            allowed.add('DOMAIN,'+host+',中转节点')
            allowed.add('AND,((NETWORK,UDP),(DOMAIN,'+host+')),REJECT')
            result.get('dns',{}).get('nameserver-policy',{}).pop(host,None)
        result['rules']=[r for r in result.get('rules',[]) if r not in allowed]
        return result
    old,new=without_local_rules(old),without_local_rules(new)
    if old.get('rules')!=new.get('rules') or old.get('dns')!=new.get('dns'):
        raise ValueError('routing_or_dns_policy_changed')
