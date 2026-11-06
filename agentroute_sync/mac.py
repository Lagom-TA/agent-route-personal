"""Local transactional updater. Private state stays outside the public repository."""
from pathlib import Path
import argparse
import copy
import datetime
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import nullcontext

from . import VERSION
from .common import atomic_bytes, atomic_json, digest, identity, lock, read_json, yaml_load
from .data import UPSTREAM, IDS, resolve, download, verify, native_validate, fetch
from .adapter import render, extract_exit, egress_revision, strip_markers, validate_exit
from .backend import Backend, rule_invariants
from .transaction import new_transaction, launch_guard, unload_guard, pending, update, commit, recover, watchdog, FINAL

DEFAULT_HOME=Path.home()/'AgentRoute/automation'
PROGRAM=Path(__file__).resolve().parent.parent
JOB='local.lagom.agentroute.sync'

def freeze_program(home):
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROGRAM,text=True).strip()
    target=Path(home)/'programs'/commit
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',commit,'agentroute_sync'],cwd=PROGRAM,text=True).splitlines()
    if not names:raise ValueError('committed_program_required')
    manifest={}
    for name in names:
        raw=subprocess.check_output(['git','show',commit+':'+name],cwd=PROGRAM)
        manifest[name]=digest(raw)
        p=target/name
        if p.exists():
            if digest(p.read_bytes())!=manifest[name]:raise ValueError('installed_program_changed')
        else:atomic_bytes(p,raw,mode=0o400)
    atomic_json(target/'code-manifest.json',{'commit':commit,'files':manifest})
    return commit,target

def status(home, name, **details):
    result={'status':name,'time':time.time(),**details}
    atomic_json(Path(home)/'status.json',result)
    return result

def bootstrap(home, repository, policy=None):
    home=Path(home);home.mkdir(parents=True,exist_ok=True,mode=0o700);home.chmod(0o700)
    if (home/'settings.json').exists():raise ValueError('already_initialized')
    root=Path.home()/'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
    profiles=yaml_load(root/'profiles.yaml');item=next(i for i in profiles['items'] if i['uid']==profiles['current'])
    script_id=item['option']['script'];extension_item=next(i for i in profiles['items'] if i['uid']==script_id)
    core='/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo'
    node=shutil.which('node')
    if not node:raise ValueError('existing_node_runtime_required')
    code_commit,frozen=freeze_program(home)
    settings={'schema_version':1,'repository':repository,'core_home':str(root),
              'extension':str(root/'profiles'/extension_item['file']),'core_binary':core,'node_binary':node,
              'profile_uid':item['uid'],
              'core_version':'v1.19.33','group':'中转节点','mixed_port':yaml_load(root/'clash-verge.yaml')['mixed-port'],
              'python':sys.executable,'program':str(frozen),'code_commit':code_commit,'automatic_apply':False,
              'reviewed_upstream_master':'39c5ce06f86c08347e31a4decdf1bde58d9dc881',
              'protected_hosts':read_json(policy,{}).get('protected_hosts',[]) if policy else []}
    backend=Backend(settings);snapshot=backend.capture();backend.ready(snapshot)
    from .common import REPO
    if not REPO.fullmatch(repository):raise ValueError('repository_invalid')
    expected=backend.current_exit_ip();health=backend.health(expected)
    atomic_json(home/'bootstrap-attempts'/(uuid.uuid4().hex+'.json'),health)
    atomic_json(home/'bootstrap-health.json',health)
    if not health['passed']:raise ValueError('baseline_health_failed_no_change')
    atomic_json(home/'settings.json',settings)
    atomic_json(home/'active.json',{'schema_version':1,'revision':1,'generation':None,
                'egress_revision':egress_revision(snapshot['exit']),'expected_ip':expected,
                'exit_spec':snapshot['exit'],'paused':False,'core_version':snapshot['core_version'],
                'owned_aliases':snapshot['owned_aliases'],'created_at':time.time()})
    return status(home,'INITIALIZED',network_configuration_changed=False)

def recover_pending(home):
    for tx in sorted((Path(home)/'transactions').glob('*')) if (Path(home)/'transactions').exists() else []:
        try:record=read_json(tx/'journal.json')
        except (ValueError,OSError):record=read_json(tx/'recovery-plan.json',{})
        if record.get('state') in ('ARMED','APPLYING','RECOVERING'):
            if record.get('selftest'):continue
            if time.time()>=record.get('deadline_wall',0):
                recover(tx);unload_guard(tx)
            else:raise ValueError('transaction_still_pending')

def check_docs(home, settings):
    try:
        own_main=resolve(settings['repository'],'main')
        if own_main!=settings.get('code_commit'):
            atomic_json(Path(home)/'program-review-needed.json',{'remote_commit':own_main,'installed_commit':settings.get('code_commit'),'time':time.time(),'automatically_installed':False})
        sha=resolve(settings['repository'],'upstream-docs')
        data=json.loads(fetch('https://raw.githubusercontent.com/'+settings['repository']+'/'+sha+'/provenance.json'))
        master=data['upstream_master']
        if master!=settings['reviewed_upstream_master']:
            notice={'status':'REVIEW_REQUIRED','upstream_master':master,'reviewed_master':settings['reviewed_upstream_master'],'time':time.time()}
            atomic_json(Path(home)/'review-needed.json',notice)
            atomic_bytes(Path(home)/'review-needed.md',('AgentRoute 文档/程序有变化，请复查。\n\nhttps://github.com/'+UPSTREAM+'/compare/'+settings['reviewed_upstream_master']+'...'+master+'\n\n未自动替换本机 DNS、WebRTC、模板或同步程序。\n').encode())
        return master
    except Exception:
        atomic_json(Path(home)/'docs-check.json',{'status':'UNVERIFIED','time':time.time()})
        return None

def stage(home, settings):
    home=Path(home)
    with lock(home/'download.lock'):
        generation=resolve(settings['repository'],'rules')
        target=home/'cache'/generation
        if target.exists():
            info=verify(target)
        else:
            temp=home/'cache'/('.stage-'+uuid.uuid4().hex)
            info=download(settings['repository'],generation,temp)
            # Leave failed candidates as evidence; never switch active on a download failure.
            os.replace(temp,target)
    return generation,target,info

def copy_generation(settings, generation, cache):
    target=Path(settings['core_home'])/'rules/agent-route/generations'/generation
    if target.exists():verify(target,fresh=False);return target
    temp=target.parent/('.stage-'+uuid.uuid4().hex);temp.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(cache,temp)
    for p in temp.rglob('*'):
        p.chmod(0o700 if p.is_dir() else 0o600)
    verify(temp,fresh=False);os.replace(temp,target)
    return target

def apply_generation(home, settings, generation, cache, info, new_exit=None, expected_ip=None, lock_held=False, expected_signature=None):
    home=Path(home);backend=Backend(settings)
    with (nullcontext() if lock_held else lock(home/'operation.lock')):
        active=read_json(home/'active.json');snapshot=backend.capture();backend.ready(snapshot)
        if expected_signature and backend.signature(snapshot)!=expected_signature:
            return status(home,'DEFERRED',reason='client_changed_since_preflight')
        if egress_revision(snapshot['exit'])!=active['egress_revision']:
            return status(home,'REVIEW_REQUIRED',reason='live_exit_changed_no_overwrite')
        baseline=backend.health(active['expected_ip'],rounds=1)
        atomic_json(home/'last-baseline-health.json',baseline)
        if not baseline['passed']:return status(home,'DEFERRED',reason='current_network_baseline_failed')
        if active.get('generation'):
            old_info=verify(home/'cache'/active['generation'],fresh=False)
            if any(abs(info['counts'][n]-old_info['counts'][n])/old_info['counts'][n]>.30 for n in IDS):
                return status(home,'REVIEW_REQUIRED',reason='rule_count_changed_over_30_percent',generation=generation)
        copy_generation(settings,generation,cache)
        script,candidate=render(snapshot['source'],snapshot['config'],generation,
                                set(snapshot['owned_aliases'])|set(active.get('owned_aliases',[])),settings['node_binary'],new_exit,settings.get('protected_hosts',[]))
        if new_exit is None:rule_invariants(snapshot['config'],candidate,settings.get('protected_hosts',[]))
        else:
            validate_exit(new_exit)
            if snapshot['config']['proxy-groups']!=candidate['proxy-groups']:
                raise ValueError('rotation_group_changed')
        scratch=home/'checks'/uuid.uuid4().hex;scratch.mkdir(parents=True,mode=0o700)
        backend.native_check(candidate,scratch)
        if backend.signature(backend.capture())!=backend.signature(snapshot):
            return status(home,'DEFERRED',reason='concurrent_client_change')
        next_exit=snapshot['exit'] if new_exit is None else new_exit
        next_expected=active['expected_ip'] if expected_ip is None else expected_ip
        tx=new_transaction(home,snapshot,active,script,candidate,generation,egress_revision(next_exit),next_expected)
        atomic_json(home/'latest-transaction.json',{'transaction':str(tx)})
        launch_guard(tx,settings['python'],settings['program'])
        try:
            pending(tx);update(tx,state='APPLYING')
            if backend.signature(backend.capture())!=backend.signature(snapshot):
                raise ValueError('concurrent_change_after_guard')
            atomic_bytes(backend.extension,script.encode())
            pending(tx);backend.apply(candidate,snapshot['selected'])
            pending(tx);backend.loaded(candidate,info['counts'])
            actual=backend.capture()
            if actual['selected']!=snapshot['selected'] or actual['raw_digest']!=snapshot['raw_digest']:
                raise ValueError('subscription_or_selection_changed_during_apply')
            if actual['extension_digest']!=digest(script.encode()):raise ValueError('concurrent_extension_change')
            result=backend.health(next_expected,rounds=2);atomic_json(tx/'health.json',result)
            pending(tx)
            if not result['passed']:raise ValueError('candidate_health_failed')
            final=backend.capture()
            if final['selected']!=snapshot['selected'] or final['extension_digest']!=digest(script.encode()) or final['raw_digest']!=snapshot['raw_digest']:
                raise ValueError('client_changed_during_acceptance')
            new_active=dict(active,generation=generation,egress_revision=egress_revision(next_exit),expected_ip=next_expected,
                            exit_spec=next_exit,owned_aliases=final['owned_aliases'],last_healthy_at=time.time(),
                            upstream_release=read_json(cache/'provenance.json')['upstream_release'])
            commit(tx,new_active)
            return status(home,'HEALTHY',generation=generation,transaction=tx.name,actual_http_validation=True)
        except Exception:
            result=recover(tx)
            return status(home,result,transaction=tx.name,generation=generation)
        finally:
            record=read_json(tx/'journal.json',{})
            if record.get('state') in FINAL:unload_guard(tx)

def check(home, apply=False, retry=False):
    home=Path(home);recover_pending(home);settings=read_json(home/'settings.json')
    if not settings:raise ValueError('not_initialized')
    check_docs(home,settings)
    generation,cache,info=stage(home,settings)
    active=read_json(home/'active.json')
    backend=Backend(settings);live=backend.capture();backend.ready(live)
    if egress_revision(live['exit'])!=active['egress_revision']:
        return status(home,'REVIEW_REQUIRED',reason='live_exit_changed_no_overwrite')
    if generation==active.get('generation'):
        for name in IDS:
            provider=live['config'].get('rule-providers',{}).get('agentroute-'+name,{})
            if provider.get('type')!='file' or generation not in provider.get('path',''):
                return status(home,'REVIEW_REQUIRED',reason='live_rule_binding_changed')
        for host in settings.get('protected_hosts',[]):
            if 'DOMAIN,'+host+','+backend.group not in live['config'].get('rules',[]):
                return status(home,'REVIEW_REQUIRED',reason='local_exact_host_policy_changed')
        return status(home,'UNCHANGED',generation=generation,network_tested=False)
    if generation in read_json(home/'held.json',{}) and not retry:
        return status(home,'HELD',generation=generation)
    if active.get('paused') and not retry:return status(home,'DEFERRED',reason='paused',generation=generation)
    if not apply and not settings['automatic_apply']:return status(home,'STAGED',generation=generation)
    return apply_generation(home,settings,generation,cache,info)

def install_agent(home):
    home=Path(home);settings=read_json(home/'settings.json');active=read_json(home/'active.json')
    if not active.get('generation') or read_json(home/'status.json',{}).get('status') not in ('HEALTHY','UNCHANGED'):
        raise ValueError('verified_application_required_before_scheduling')
    settings['automatic_apply']=True;atomic_json(home/'settings.json',settings)
    args=[settings['python'],'-m','agentroute_sync.mac','check','--home',str(home)]
    plist={'Label':JOB,'ProgramArguments':args,'RunAtLoad':True,'ProcessType':'Background',
           'WorkingDirectory':settings['program'],'EnvironmentVariables':{'PYTHONPATH':settings['program']},
           'StartCalendarInterval':[{'Hour':h,'Minute':47} for h in [2,8,14,20]],
           'StandardOutPath':str(home/'scheduler.stdout.log'),'StandardErrorPath':str(home/'scheduler.stderr.log')}
    path=Path.home()/'Library/LaunchAgents'/ (JOB+'.plist');atomic_bytes(path,plistlib.dumps(plist))
    subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/'+JOB],capture_output=True)
    result=subprocess.run(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],capture_output=True)
    if result.returncode:raise RuntimeError('scheduled_agent_install_failed')
    return {'status':'SCHEDULED','hours':[2,8,14,20],'minute':47,'wake_catchup':'StartCalendarInterval','label':JOB}

def selftest(home):
    home=Path(home);settings=read_json(home/'settings.json')
    snapshot={'source':'selftest','config':{},'selected':{},'owned_aliases':[]}
    tx=new_transaction(home,snapshot,{},'selftest',{},'0'*40,'selftest','0.0.0.0',seconds=3,selftest=True)
    launch_guard(tx,settings['python'],settings['program'])
    try:
        for _ in range(70):
            record=read_json(tx/'journal.json',{})
            if record.get('state')=='SELFTEST_RECOVERED':return {'status':'SELFTEST_RECOVERED','transaction':tx.name,'network_changed':False}
            time.sleep(.1)
        raise RuntimeError('independent_guard_selftest_failed')
    finally:unload_guard(tx)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['bootstrap','check','status','install-agent','watchdog','recover','selftest','pause','resume','rotate','preflight','preflight-worker','adopt-exit'])
    parser.add_argument('--home',type=Path,default=DEFAULT_HOME)
    parser.add_argument('--repository');parser.add_argument('--transaction',type=Path)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--retry-held',action='store_true')
    parser.add_argument('--spec',type=Path);parser.add_argument('--expected-ip');parser.add_argument('--request',type=Path)
    parser.add_argument('--policy',type=Path)
    args=parser.parse_args();os.umask(0o077)
    try:
        if args.command=='bootstrap':result=bootstrap(args.home,args.repository,args.policy)
        elif args.command=='check':result=check(args.home,args.apply,args.retry_held)
        elif args.command=='status':
            active=read_json(args.home/'active.json',{});result={'state':read_json(args.home/'status.json',{}),'generation':active.get('generation'),'egress_revision':active.get('egress_revision'),'paused':active.get('paused'),'review_required':(args.home/'review-needed.json').exists()}
        elif args.command=='install-agent':result=install_agent(args.home)
        elif args.command=='watchdog':result={'status':watchdog(args.transaction)}
        elif args.command=='recover':
            path=args.transaction or Path(read_json(args.home/'latest-transaction.json')['transaction']);result={'status':recover(path,manual=True)};unload_guard(path)
        elif args.command=='selftest':result=selftest(args.home)
        elif args.command in ('pause','resume'):
            with lock(args.home/'operation.lock'):
                active=read_json(args.home/'active.json');active['paused']=args.command=='pause';active['revision']+=1;atomic_json(args.home/'active.json',active)
            result={'status':'PAUSED' if args.command=='pause' else 'RESUMED'}
        elif args.command in ('rotate','preflight'):
            from .preflight import rotate
            result=rotate(args.home,args.spec,apply=args.command=='rotate')
        elif args.command=='preflight-worker':
            from .preflight import worker
            result=worker(args.request)
        else:
            result=adopt_exit(args.home,args.expected_ip)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result.get('status') not in ('RECOVERY_UNCONFIRMED','ROLLED_BACK') else 1
    except BlockingIOError:
        print(json.dumps({'status':'DEFERRED','reason':'another_rule_or_exit_operation_is_running'}));return 0
    except Exception as error:
        # Never echo client payloads, proxy addresses or credentials in scheduler output.
        result={'status':'FAILED','error':type(error).__name__+':'+str(error)}
        if args.command not in ('watchdog','preflight-worker') and args.home.exists():atomic_json(args.home/'status.json',dict(result,time=time.time()))
        print(json.dumps(result,ensure_ascii=False));return 1

def adopt_exit(home,expected):
    import ipaddress
    if not expected:raise ValueError('expected_ip_required')
    ipaddress.ip_address(expected)
    with lock(Path(home)/'operation.lock'):
        settings=read_json(Path(home)/'settings.json');backend=Backend(settings);snapshot=backend.capture();backend.ready(snapshot)
        result=backend.health(expected)
        if not result['passed']:raise ValueError('new_live_exit_not_healthy')
        active=read_json(Path(home)/'active.json');active.update(expected_ip=expected,egress_revision=egress_revision(snapshot['exit']),exit_spec=snapshot['exit'],revision=active['revision']+1,paused=False)
        atomic_json(Path(home)/'active.json',active)
    return status(home,'EXIT_BASELINE_ADOPTED',network_configuration_changed=False)

if __name__=='__main__':sys.exit(main())
