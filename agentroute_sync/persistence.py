"""Protected verification of the app-owned service runtime bundle."""
from pathlib import Path
import json
import subprocess
import time
import uuid

from .backend import Backend
from .common import atomic_json, lock, read_json
from .data import IDS, verify
from .transaction import new_transaction, launch_guard, pending, update, commit, recover, unload_guard, FINAL


def service_pid():
    result=subprocess.run(['/bin/ps','-axo','pid=,args='],capture_output=True,text=True,timeout=5)
    found=[]
    import os
    socket='/var/run/clash-verge-service/users/'+str(os.getuid())+'/verge-mihomo.sock'
    for line in result.stdout.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)==2 and parts[1].split(' -d ',1)[0].endswith('/verge-mihomo') and '-ext-ctl-unix '+socket in parts[1]:
            found.append(int(parts[0]))
    if len(found)!=1:raise ValueError('service_core_pid_not_confirmed')
    return found[0]


def verify_persistence(home):
    from .mac import status
    home=Path(home);settings=read_json(home/'settings.json');backend=Backend(settings)
    with lock(home/'operation.lock'):
        active=read_json(home/'active.json');snapshot=backend.capture();backend.ready(snapshot)
        if not active.get('generation'):raise ValueError('rule_migration_required_first')
        pid=service_pid();baseline=backend.health(active['expected_ip'],rounds=1)
        atomic_json(home/'persistence-baseline.json',baseline)
        if not baseline['passed']:return status(home,'DEFERRED',reason='current_network_baseline_failed')
        info=verify(home/'cache'/active['generation'],fresh=False)
        backend.native_check(snapshot['config'],home/'checks'/uuid.uuid4().hex)
        tx=new_transaction(home,snapshot,active,snapshot['source'],snapshot['config'],active['generation'],active['egress_revision'],active['expected_ip'])
        atomic_json(home/'latest-transaction.json',{'transaction':str(tx)})
        launch_guard(tx,settings['python'],settings['program'])
        try:
            update(tx,state='APPLYING',phase='await_gui_reactivation')
            ready={'status':'READY_FOR_GUI_REACTIVATION','transaction':tx.name,'action':'在 Clash Verge 的订阅页面点击“重新激活订阅”，保持当前订阅和节点。','wait_seconds':45}
            atomic_json(home/'persistence-ready.json',dict(ready,time=time.time()))
            print(json.dumps(ready,ensure_ascii=False),flush=True)
            deadline=time.monotonic()+45
            while True:
                pending(tx)
                providers=backend.api('GET','/providers/rules')['providers']
                if all(providers.get('agentroute-'+n,{}).get('vehicleType')=='File' and providers['agentroute-'+n].get('ruleCount')==info['counts'][n] for n in IDS):break
                if time.monotonic()>=deadline:raise ValueError('gui_reactivation_not_verified')
                time.sleep(.3)
            if service_pid()!=pid:raise ValueError('service_core_restarted_during_gui_check')
            backend.loaded(snapshot['config'],info['counts'])
            update(tx,phase='gui_files_loaded')
            time.sleep(2)
            health=backend.health(active['expected_ip'],rounds=2);atomic_json(tx/'health.json',health)
            if not health['passed']:raise ValueError('gui_persistence_health_failed')
            final=backend.capture();backend.ready(final)
            if any(final[k]!=snapshot[k] for k in ('raw_digest','extension_digest','selected')):
                raise ValueError('client_changed_during_gui_verification')
            if service_pid()!=pid:raise ValueError('service_core_changed_during_gui_check')
            backend.loaded(snapshot['config'],info['counts'])
            new_active=dict(active,pending_gui_persistence=None,gui_persistence_verified_at=time.time())
            commit(tx,new_active)
            atomic_json(tx/'persistence-verification.json',{'core_pid_unchanged':True,'providers':'File','counts':info['counts'],'actual_http_validation':True})
            return status(home,'HEALTHY',generation=active['generation'],transaction=tx.name,gui_persistence_verified=True)
        except Exception as error:
            atomic_json(tx/'application-error.json',{'error_type':type(error).__name__,'error':str(error),'time':time.time()})
            return status(home,recover(tx),transaction=tx.name)
        finally:
            if read_json(tx/'journal.json',{}).get('state') in FINAL:unload_guard(tx)
