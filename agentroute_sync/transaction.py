"""Private per-operation snapshots and an independently supervised rollback."""
from pathlib import Path
import json
import os
import plistlib
import signal
import subprocess
import time
import uuid

from .common import atomic_bytes, atomic_json, digest, lock, read_json
from .backend import Backend, evaluate_script

FINAL = {'COMMITTED','ROLLED_BACK','RECOVERY_UNCONFIRMED','SELFTEST_RECOVERED'}

def valid_commit(tx, record):
    plan=read_json(Path(tx)/'recovery-plan.json')
    if any(record.get(k)!=plan.get(k) for k in ('id','generation','egress_revision')):
        return False
    active=read_json(Path(plan['home'])/'active.json',{})
    return (record.get('state')=='COMMITTED' and active.get('last_transaction')==plan['id']
            and active.get('generation')==plan['generation'] and active.get('egress_revision')==plan['egress_revision']
            and read_json(Path(tx)/'health.json',{}).get('passed') is True)

def process_start(pid):
    result=subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True)
    return result.stdout.strip()

def update(tx, **fields):
    tx=Path(tx)
    with lock(tx/'state.lock',blocking=True):
        record=read_json(tx/'journal.json')
        record.update(fields)
        atomic_json(tx/'journal.json',record)
        return record

def pending(tx):
    record=read_json(Path(tx)/'journal.json')
    if record['state'] not in ('ARMED','APPLYING') or time.time()>=record['deadline_wall'] or time.monotonic()>=record['deadline_monotonic']:
        raise RuntimeError('transaction_not_pending')
    return record

def new_transaction(home, snapshot, state_before, script, candidate, generation, egress, expected_ip, seconds=150, selftest=False):
    home=Path(home);tx=home/'transactions'/uuid.uuid4().hex;tx.mkdir(parents=True,mode=0o700)
    atomic_json(tx/'snapshot.json',snapshot)
    atomic_json(tx/'state-before.json',state_before)
    atomic_bytes(tx/'source-before.js',snapshot['source'].encode())
    atomic_bytes(tx/'source-candidate.js',script.encode())
    atomic_json(tx/'candidate.json',candidate)
    record={'id':tx.name,'state':'ARMED','created_at':time.time(),'home':str(home),
            'owner_pid':os.getpid(),'owner_started':process_start(os.getpid()),
            'deadline_wall':time.time()+seconds,'deadline_monotonic':time.monotonic()+seconds,
            'snapshot_digest':digest((tx/'snapshot.json').read_bytes()),
            'source_before_digest':digest(snapshot['source'].encode()),'source_candidate_digest':digest(script.encode()),
            'generation':generation,'egress_revision':egress,'expected_ip':expected_ip,'selftest':selftest}
    atomic_json(tx/'journal.json',record)
    atomic_json(tx/'recovery-plan.json',record)
    return tx

def recover(tx, manual=False):
    tx=Path(tx)
    try:record=read_json(tx/'journal.json')
    except (ValueError,OSError):record=read_json(tx/'recovery-plan.json')
    home=Path(record['home'])
    if record['state'] in ('ROLLED_BACK','SELFTEST_RECOVERED'):
        return record['state']
    if record['state']=='COMMITTED' and not manual and valid_commit(tx,record):
        return 'COMMITTED'
    with lock(tx/'state.lock',blocking=True):
        try:record=read_json(tx/'journal.json')
        except (ValueError,OSError):record=read_json(tx/'recovery-plan.json')
        if record['state']=='COMMITTED' and not manual and valid_commit(tx,record):return 'COMMITTED'
        plan=read_json(tx/'recovery-plan.json')
        if any(record.get(k)!=plan.get(k) for k in ('id','generation','egress_revision')):record=plan
        atomic_json(tx/'journal.json',dict(record,state='RECOVERING',recovery_started=time.time()))
    if record.get('selftest'):
        atomic_bytes(tx/'selftest-restored',b'recovered\n')
        update(tx,state='SELFTEST_RECOVERED',recovered_at=time.time())
        return 'SELFTEST_RECOVERED'
    pid=record['owner_pid']
    if pid!=os.getpid() and process_start(pid)==record['owner_started']:
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass
    settings=read_json(home/'settings.json');backend=Backend(settings)
    try:
        if digest((tx/'snapshot.json').read_bytes())!=record['snapshot_digest']:
            raise ValueError('rollback_snapshot_corrupt')
        snapshot=read_json(tx/'snapshot.json')
        current_source=backend.extension.read_bytes()
        if digest(current_source) not in (record['source_before_digest'],record['source_candidate_digest']):
            raise ValueError('concurrent_extension_change_no_overwrite')
        # A GUI subscription refresh may legitimately update nodes while the transaction is open.
        # Re-evaluate the previous extension against current input rather than overwriting the subscription.
        current=backend.capture()
        old_source=(tx/'source-before.js').read_text()
        original_input=dict(current['config'])
        original_input['proxies']=[p for p in original_input.get('proxies',[]) if p['name'] not in snapshot['owned_aliases'] and not p.get('agentroute-generated')]
        restored=evaluate_script(old_source,original_input,backend.node)
        restored['mode']=current['runtime']['mode']
        restored.setdefault('tun',{})['enable']=current['runtime']['tun']['enable']
        selected={}
        groups={g['name']:g.get('proxies',[]) for g in restored.get('proxy-groups',[])}
        for group,name in current['selected'].items():
            selected[group]=name if name in groups.get(group,[]) else snapshot['selected'].get(group,name)
        atomic_bytes(backend.extension,old_source.encode())
        backend.apply(restored,selected)
        if current['runtime']['mode']=='rule' and current['runtime']['tun']['enable']:
            result=backend.health(read_json(tx/'state-before.json')['expected_ip'],rounds=1)
        else:
            result={'passed':False,'reason':'mode_or_tun_changed_by_user'}
        atomic_json(tx/'recovery-health.json',result)
        old=read_json(tx/'state-before.json');live=read_json(home/'active.json',{})
        old['revision']=max(old.get('revision',0),live.get('revision',0))+1
        old['paused']=manual or not result['passed']
        atomic_json(home/'active.json',old)
        held=read_json(home/'held.json',{})
        held[record['generation']]={'transaction':tx.name,'reason':'manual_rollback' if manual else 'application_not_accepted','time':time.time()}
        atomic_json(home/'held.json',held)
        state='ROLLED_BACK' if result['passed'] else 'RECOVERY_UNCONFIRMED'
        update(tx,state=state,recovered_at=time.time())
        atomic_json(home/'status.json',{'status':state,'transaction':tx.name,'time':time.time()})
        return state
    except Exception as error:
        update(tx,state='RECOVERY_UNCONFIRMED',recovery_error=type(error).__name__+':'+str(error))
        atomic_json(home/'status.json',{'status':'RECOVERY_UNCONFIRMED','transaction':tx.name,'time':time.time()})
        return 'RECOVERY_UNCONFIRMED'

def watchdog(tx):
    tx=Path(tx);record=read_json(tx/'journal.json')
    deadline_wall=record['deadline_wall'];deadline_monotonic=record['deadline_monotonic']
    if digest((tx/'snapshot.json').read_bytes())!=record['snapshot_digest']:
        raise ValueError('guard_snapshot_unreadable')
    atomic_json(tx/'ready.json',{'transaction':tx.name,'pid':os.getpid(),'time':time.time()})
    while True:
        try:
            record=read_json(tx/'journal.json')
        except (ValueError,OSError):
            # A malformed success record must never silently disarm recovery.
            time.sleep(.5)
            if time.time()>=deadline_wall or time.monotonic()>=deadline_monotonic:
                break
            continue
        deadline_wall=record['deadline_wall'];deadline_monotonic=record['deadline_monotonic']
        if record['state']=='COMMITTED':
            if valid_commit(tx,record):return 'COMMITTED'
        elif record['state'] in FINAL:return record['state']
        if time.time()>=deadline_wall or time.monotonic()>=deadline_monotonic:
            return recover(tx)
        time.sleep(.5)
    return recover(tx)

def launch_guard(tx, python, program):
    tx=Path(tx);label='local.lagom.agentroute.guard.'+tx.name
    config={'Label':label,'ProgramArguments':[python,'-m','agentroute_sync.mac','watchdog','--transaction',str(tx)],
            'RunAtLoad':True,'ProcessType':'Background','WorkingDirectory':str(program),
            'EnvironmentVariables':{'PYTHONPATH':str(program)},
            'StandardOutPath':str(tx/'guard.stdout.log'),'StandardErrorPath':str(tx/'guard.stderr.log')}
    path=tx/'guard.plist';atomic_bytes(path,plistlib.dumps(config))
    result=subprocess.run(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],capture_output=True)
    if result.returncode:raise RuntimeError('independent_guard_not_started')
    for _ in range(50):
        ready=read_json(tx/'ready.json',{})
        if ready.get('transaction')==tx.name:return label
        time.sleep(.1)
    raise RuntimeError('independent_guard_not_ready')

def unload_guard(tx):
    label='local.lagom.agentroute.guard.'+Path(tx).name
    subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True)

def commit(tx, active):
    tx=Path(tx);record=pending(tx);home=Path(record['home'])
    with lock(tx/'state.lock',blocking=True):
        pending(tx)
        old=read_json(home/'active.json')
        before=read_json(tx/'state-before.json')
        if old!=before:raise ValueError('active_revision_changed')
        active=dict(active,revision=old.get('revision',0)+1,last_transaction=tx.name,paused=False)
        atomic_json(home/'active.json',active)
        atomic_json(tx/'journal.json',dict(record,state='COMMITTED',committed_at=time.time()))
