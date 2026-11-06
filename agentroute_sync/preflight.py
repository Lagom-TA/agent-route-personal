"""A supervised, loopback-only, no-TUN preview of a proposed exit chain."""
from pathlib import Path
import copy
import ipaddress
import json
import os
import plistlib
import signal
import socket
import subprocess
import threading
import time
import uuid

from .common import atomic_bytes, atomic_json, lock, read_json
from .adapter import render, validate_exit
from .backend import Backend

def physical_interface():
    result=subprocess.run(['/sbin/route','-n','get','default'],capture_output=True,text=True,timeout=5)
    value=next((l.split(':',1)[1].strip() for l in result.stdout.splitlines() if l.strip().startswith('interface:')),None)
    if not value or value.startswith('utun'):raise ValueError('physical_interface_not_confirmed')
    return value

def worker(request_file):
    request_file=Path(request_file);request=read_json(request_file);work=request_file.parent
    backend=Backend(request['settings']);snapshot=request['snapshot']
    proposed=request['proxy'];validate_exit(proposed)
    _,full=render(snapshot['source'],snapshot['config'],request['generation'],snapshot['owned_aliases'],backend.node,proposed,request['settings'].get('protected_hosts',[]))
    selected=snapshot['selected'][backend.group];all_nodes={p['name']:p for p in full['proxies']}
    names=[];cursor=selected
    while cursor:
        if cursor in names:raise ValueError('preflight_cycle')
        names.append(cursor);cursor=all_nodes[cursor].get('dialer-proxy')
    if len([n for n in names if all_nodes[n].get('agentroute-generated')])!=1:raise ValueError('preflight_nested_exit')
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    dns=copy.deepcopy(full['dns']);dns.pop('listen',None)
    dns['nameserver-policy']={}
    config={'mode':'rule','allow-lan':False,'bind-address':'127.0.0.1','mixed-port':port,
            'tun':{'enable':False},'ipv6':full.get('ipv6',True),'interface-name':request['physical_interface'],
            'external-controller':'','dns':dns,'log-level':'info',
            'proxies':[all_nodes[n] for n in names],
            'proxy-groups':[{'name':backend.group,'type':'select','proxies':[selected],'disable-udp':True}],
            'rules':['NETWORK,UDP,REJECT','MATCH,'+backend.group]}
    atomic_json(work/'shadow.json',config)
    log=(work/'shadow.log').open('wb')
    proc=subprocess.Popen([backend.core,'-d',str(work),'-f',str(work/'shadow.json')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    atomic_json(work/'child.json',{'pid':proc.pid,'port':port,'tun':False,'bind':'127.0.0.1','physical_interface':request['physical_interface']})
    def stop():
        if proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
    timer=threading.Timer(75,stop);timer.daemon=True;timer.start()
    try:
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError('preflight_core_exited')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('preflight_listener_not_ready')
        result=backend.health(request['expected_ip'],rounds=2,proxy='http://127.0.0.1:'+str(port))
        result.update(status='PREFLIGHT_HEALTHY' if result['passed'] else 'PREFLIGHT_FAILED',no_main_core_change=True,
                      physical_interface=request['physical_interface'],only_one_generated_exit=True)
        atomic_json(work/'result.json',result)
        return {'status':result['status'],'preflight':work.name,'main_network_changed':False}
    finally:
        timer.cancel();stop()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=3)
        log.close();atomic_json(work/'child-exited.json',{'pid':proc.pid,'exit':proc.returncode,'time':time.time()})

def supervised(home,settings,snapshot,spec,generation):
    home=Path(home);work=home/'preflights'/uuid.uuid4().hex;work.mkdir(parents=True,mode=0o700)
    atomic_json(work/'request.json',{'settings':settings,'snapshot':snapshot,'proxy':spec['proxy'],'expected_ip':spec['expected_ip'],
                                   'generation':generation,'physical_interface':physical_interface()})
    label='local.lagom.agentroute.preflight.'+work.name
    job={'Label':label,'ProgramArguments':[settings['python'],'-m','agentroute_sync.mac','preflight-worker','--request',str(work/'request.json')],
         'RunAtLoad':True,'ProcessType':'Background','WorkingDirectory':settings['program'],
         'EnvironmentVariables':{'PYTHONPATH':settings['program']},'StandardOutPath':str(work/'worker.stdout.log'),'StandardErrorPath':str(work/'worker.stderr.log')}
    atomic_bytes(work/'worker.plist',plistlib.dumps(job))
    result=subprocess.run(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),str(work/'worker.plist')],capture_output=True)
    if result.returncode:raise RuntimeError('preflight_supervisor_not_started')
    try:
        for _ in range(110):
            value=read_json(work/'result.json',{})
            if value and (work/'child-exited.json').exists():return work,value
            time.sleep(1)
        raise RuntimeError('preflight_supervisor_timeout')
    finally:
        subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True)

def rotate(home,spec_file,apply=True):
    from .mac import apply_generation,status,require_exit_persistence
    home=Path(home);settings=read_json(home/'settings.json');spec=read_json(spec_file)
    if not spec or set(spec)-{'proxy','expected_ip','provider'}:raise ValueError('exit_spec_format_invalid')
    validate_exit(spec['proxy']);ipaddress.ip_address(spec['expected_ip'])
    with lock(home/'operation.lock'):
        active=read_json(home/'active.json');backend=Backend(settings);snapshot=backend.capture();backend.ready(snapshot)
        if apply and active.get('pending_gui_persistence'):raise ValueError('previous_exit_persistence_verification_required')
        generation=active.get('generation') or '0'*40
        signature=backend.signature(snapshot)
        work,result=supervised(home,settings,snapshot,spec,generation)
        if not result['passed']:return status(home,'PREFLIGHT_FAILED',preflight=work.name,main_network_changed=False)
        if not apply:return status(home,'PREFLIGHT_HEALTHY',preflight=work.name,main_network_changed=False)
        if not active.get('generation'):raise ValueError('rule_migration_required_first')
        from .data import verify
        cache=home/'cache'/generation;info=verify(cache,fresh=False)
        result=apply_generation(home,settings,generation,cache,info,spec['proxy'],spec['expected_ip'],lock_held=True,expected_signature=signature)
        return require_exit_persistence(home,result) if result.get('status')=='HEALTHY' else result
