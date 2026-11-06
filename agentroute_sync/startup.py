"""Read-only network/configuration acceptance after the local core becomes ready."""
from pathlib import Path
import time
import uuid

from .adapter import egress_revision,graph_check
from .backend import Backend
from .common import atomic_json,boot_session_id,digest,identity,lock,read_json
from .data import verify,IDS
from .persistence import service_pid
from .transaction import process_start


def wait_ready(backend,seconds=180):
    deadline=time.monotonic()+seconds;last='core_not_ready'
    permanent=('core_version_changed_requires_review','bundled_core_version_changed_requires_review',
               'configuration_source_changed_requires_review','fixed_group_missing')
    while True:
        try:
            value=backend.capture();backend.ready(value);return value
        except Exception as error:
            last=str(error) if isinstance(error,ValueError) else type(error).__name__
            if last in permanent:raise ValueError(last)
            if time.monotonic()>=deadline:raise ValueError('startup_not_ready:'+last)
            time.sleep(2)


def structural_check(backend,snapshot,active,counts):
    config=snapshot['config'];group=backend.group;graph_check(config)
    for name in IDS:
        provider=config.get('rule-providers',{}).get('agentroute-'+name,{})
        if provider.get('type')!='file' or active['generation'] not in provider.get('path',''):
            raise ValueError('startup_disk_generation_changed')
    if egress_revision(snapshot['exit'])!=active['egress_revision']:raise ValueError('startup_exit_revision_changed')
    selected=next(g for g in config['proxy-groups'] if g['name']==group)
    if selected.get('empty-fallback')!='REJECT':raise ValueError('startup_empty_group_not_rejected')
    nodes={p['name']:p for p in config['proxies']};expected=active['exit_spec']
    for name in selected['proxies']:
        if any(nodes[name].get(k)!=expected.get(k) for k in ('type','server','port','username','password')):
            raise ValueError('startup_fixed_exit_chain_changed')
        if nodes[name].get('udp') is not False:raise ValueError('startup_exit_udp_policy_changed')
    actual=backend.api('GET','/proxies')['proxies'][group]
    if actual.get('emptyFallback')!='REJECT' or set(actual.get('all',[]))!=set(selected['proxies']):
        raise ValueError('startup_actual_group_changed')
    rules=backend.api('GET','/rules')['rules']
    if not rules or rules[-1].get('type')!='Match' or rules[-1].get('proxy')!=group:
        raise ValueError('startup_default_route_changed')
    for host in backend.settings.get('protected_hosts',[]):
        first=next((r for r in rules if r.get('type')=='Domain' and r.get('payload')==host),None)
        if not first or first.get('proxy')!=group:raise ValueError('startup_protected_host_changed')
    dns=config.get('dns',{});policy=dns.get('nameserver-policy',{})
    if dns.get('fallback'):raise ValueError('startup_dns_fallback_changed')
    for host in backend.settings.get('protected_hosts',[]):
        values=policy.get(host,[])
        if not isinstance(values,list) or not values or any(not v.startswith('https://') or not v.endswith('#'+group) for v in values):
            raise ValueError('startup_protected_dns_changed')
    backend.loaded(config,counts)


def verify_startup(home,force=False,wait_seconds=180):
    home=Path(home);settings=read_json(home/'settings.json');backend=Backend(dict(settings,control_timeout=2))
    run=home/'startup'/uuid.uuid4().hex
    result={'status':'STARTUP_UNVERIFIED','time':time.time(),'network_configuration_modified':False}
    try:
        snapshot=wait_ready(backend,wait_seconds)
        with lock(home/'operation.lock'):
            active=read_json(home/'active.json')
            if active.get('pending_gui_persistence'):raise ValueError('exit_persistence_verification_required')
            if not active.get('generation'):raise ValueError('rule_generation_missing')
            pid=service_pid();boot=boot_session_id()
            key=identity({'boot':boot,'pid':pid,'started':process_start(pid),'program':settings['code_commit'],
                          'egress':active['egress_revision'],'profile':snapshot['profile']})
            info=verify(home/'cache'/active['generation'],fresh=False)
            structural_check(backend,snapshot,active,info['counts'])
            last=read_json(home/'startup-last-passed.json',{})
            if not force and last.get('identity')==key:
                return {'status':'STARTUP_CACHED','network_tested':False,'last_passed_at':last.get('passed_at')}
            # Validate the disk files needed for a cold core as well as API delivery.
            backend.native_check(snapshot['config'],run)
            health=backend.health(active['expected_ip'],rounds=2);atomic_json(run/'health.json',health)
            if not health['passed']:raise ValueError('startup_network_acceptance_failed')
            observed=set(health.get('protected_route_hosts_observed',[]))
            if not set(settings.get('protected_hosts',[]))<=observed:raise ValueError('startup_route_evidence_incomplete')
            final=backend.capture();backend.ready(final)
            if backend.signature(final)!=backend.signature(snapshot) or service_pid()!=pid:
                raise ValueError('startup_client_changed_during_acceptance')
            result.update(status='STARTUP_PASSED',passed_at=time.time(),identity=key,boot_session=boot,
                          core_pid=pid,core_started_at=process_start(pid),core_version=final['core_version'],generation=active['generation'],
                          protected_hosts_observed=sorted(observed),actual_http_validation=True,run=str(run))
            from .backups import refresh_after_acceptance,prune_finished_snapshots
            if not refresh_after_acceptance(home,final):raise ValueError('startup_backup_refresh_failed')
            prune_finished_snapshots(home)
            atomic_json(home/'startup-last-passed.json',result)
    except BlockingIOError:
        result.update(status='STARTUP_DEFERRED',reason='another_network_operation_running')
    except Exception as error:
        result.update(status='STARTUP_UNVERIFIED',reason=str(error) if isinstance(error,ValueError) else type(error).__name__)
        from .notices import notify
        notify(home,'failure',{'reason':result['reason'],'phase':'startup'})
    atomic_json(home/'startup-report.json',result)
    # Native candidates contain credentials; only keep compact test/health evidence.
    for name in ('candidate-native.json','runtime-native.json'):
        p=run/name
        if p.is_file():p.unlink()
    return result
