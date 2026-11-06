"""Two current, verified local backup sets; transaction snapshots are temporary."""
from pathlib import Path
import json
import os
import shutil
import shlex
import time
import tempfile
import uuid

from .common import atomic_bytes, atomic_json, digest, lock, read_json,SHA
from .data import verify,UPSTREAM


def backup_root(home):
    return Path(read_json(Path(home)/'settings.json')['backup_directory'])


def validate_bundle(directory):
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('backup_symlink_rejected')
    meta=read_json(directory/'manifest.json')
    if not meta or meta.get('schema_version')!=1:raise ValueError('backup_manifest_invalid')
    for name,expected in meta['files'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('backup_path_invalid')
        file=directory/p
        if file.is_symlink() or not file.is_file() or digest(file.read_bytes())!=expected:
            raise ValueError('backup_integrity_failed')
    return meta


def publish(stage,target,kind):
    stage=Path(stage);target=Path(target)
    hashes={str(p.relative_to(stage)):digest(p.read_bytes()) for p in stage.rglob('*') if p.is_file()}
    atomic_json(stage/'manifest.json',{'schema_version':1,'kind':kind,'created_at':time.time(),'files':hashes})
    validate_bundle(stage)
    retired=target.parent/('.replaced-'+uuid.uuid4().hex)
    if target.is_symlink():raise ValueError('backup_target_symlink_rejected')
    if target.exists():os.replace(target,retired)
    try:os.replace(stage,target)
    except Exception:
        if retired.exists():os.replace(retired,target)
        raise
    # The user explicitly selected one latest copy per set. Only replace our own
    # validated set after the successor is fully written and verified.
    if retired.exists():shutil.rmtree(retired)


def refresh(home,snapshot):
    home=Path(home);settings=read_json(home/'settings.json');active=read_json(home/'active.json')
    if not settings.get('backup_directory'):return {'status':'NOT_CONFIGURED'}
    if active.get('pending_gui_persistence'):raise ValueError('exit_persistence_not_finished')
    from .adapter import egress_revision
    if egress_revision(snapshot['exit'])!=active['egress_revision']:raise ValueError('backup_exit_revision_mismatch')
    for name in ('private','reject','proxy','direct','cn-ip'):
        expected='./rules/agent-route/generations/'+active['generation']+'/mihomo/'+name+'.yaml'
        if snapshot['config']['rule-providers']['agentroute-'+name].get('path')!=expected:
            raise ValueError('backup_rule_generation_mismatch')
    raw_path=Path(settings['core_home'])/'profiles'/settings['original_profile_file']
    raw=raw_path.read_bytes()
    if digest(raw)!=snapshot['raw_digest']:raise ValueError('subscription_changed_before_backup')
    root=backup_root(home);root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    with lock(home/'backup.lock'),tempfile.TemporaryDirectory(prefix='.building-',dir=root) as workspace:
        original=Path(workspace)/'original';original.mkdir(mode=0o700)
        atomic_bytes(original/'provider-subscription.yaml',raw)
        atomic_json(original/'source.json',{'profile_uid':snapshot['profile'],'file':raw_path.name,'sha256':digest(raw)})
        atomic_bytes(original/'README.md','# 原始订阅使用指南\n\nprovider-subscription.yaml 是供应商原始订阅，未叠加本机扩展。仅在明确选择恢复供应商规则时，通过 Clash 订阅页面导入本地文件；这会改变现有分流与出口。日常恢复使用 agentroute-current，不直接导入本文件。manifest.json 可核对摘要。\n'.encode())
        publish(original,root/'provider-original','provider-original')
        current=Path(workspace)/'current';current.mkdir(mode=0o700)
        atomic_json(current/'snapshot.json',snapshot)
        atomic_json(current/'active.json',active)
        atomic_json(current/'settings.json',settings)
        atomic_bytes(current/'subscription-extension.js',snapshot['source'].encode())
        atomic_json(current/'effective-config.yaml',snapshot['config'])
        atomic_bytes(current/'provider-subscription.yaml',raw)
        for name in ('profiles.yaml','verge.yaml'):
            atomic_bytes(current/name,(Path(settings['core_home'])/name).read_bytes())
        cache=home/'cache'/active['generation'];verify(cache,fresh=False)
        shutil.copytree(cache,current/'rule-data')
        program=Path(settings['program']);manifest=read_json(program/'code-manifest.json')
        for name,expected in manifest['files'].items():
            data=(program/name).read_bytes()
            if digest(data)!=expected:raise ValueError('installed_program_changed')
            atomic_bytes(current/'program'/name,data,mode=0o400)
        atomic_json(current/'program/code-manifest.json',manifest)
        atomic_bytes(current/'README.md','# 当前 AgentRoute 备份使用指南\n\n此目录是最近一次验收通过的配置，后续通过验收时原位更新，不保留历史副本。日常恢复运行目录上级的“恢复当前 AgentRoute.command”。恢复前校验 manifest.json，保留当前订阅与仍有效的节点选择，恢复后暂停自动应用。涉及出口恢复时，按主使用指南核对服务持久化。全部内容仅本机使用。\n'.encode())
        publish(current,root/'agentroute-current','agentroute-current')
        write_recovery_entry(home,root,settings)
        result={'status':'VERIFIED','directory':str(root),'sets':['provider-original','agentroute-current'],
                'generation':active['generation'],'egress_revision':active['egress_revision'],'time':time.time()}
        atomic_json(home/'backup-status.json',result)
        return result


def write_recovery_entry(home,root,settings):
    script='''from pathlib import Path
import json,hashlib,sys
home=Path(__HOME__)
bundle=Path(__BUNDLE__)
meta=json.loads((bundle/'manifest.json').read_text())
for name,expected in meta['files'].items():
    p=Path(name)
    if p.is_absolute() or '..' in p.parts:raise SystemExit('备份路径不符，未执行恢复。')
    p=bundle/p
    if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise SystemExit('备份校验失败，未执行恢复。')
sys.path.insert(0,str(bundle/'program'))
from agentroute_sync.backups import restore_current
if '--verify-only' in sys.argv:
    print(json.dumps({'status':'BACKUP_VERIFIED','files':len(meta['files']),'network_configuration_modified':False}))
    raise SystemExit(0)
try:
    result=restore_current(home)
    print(json.dumps({'status':result,'automatic_application':'paused'},ensure_ascii=False))
    raise SystemExit(0 if result=='ROLLED_BACK' else 1)
except BlockingIOError:raise SystemExit('正在执行规则或出口事务，请等本轮结束后再恢复。')
'''.replace('__HOME__',repr(str(home))).replace('__BUNDLE__',repr(str(root/'agentroute-current')))
    atomic_bytes(root/'restore-current.py',script.encode(),mode=0o600)
    command='#!/bin/zsh\n'+shlex.quote(settings['python'])+' '+shlex.quote(str(root/'restore-current.py'))+'\nTASK_RESULT=$?\nif [[ -t 0 ]]; then read -r \'?按回车关闭窗口\'; fi\nexit $TASK_RESULT\n'
    atomic_bytes(root/'恢复当前 AgentRoute.command',command.encode(),mode=0o700)


def refresh_after_acceptance(home,snapshot):
    try:refresh(home,snapshot);return True
    except Exception as error:
        home=Path(home);active=read_json(home/'active.json')
        active.update(paused=True,revision=active['revision']+1);atomic_json(home/'active.json',active)
        atomic_json(home/'backup-status.json',{'status':'FAILED','error_type':type(error).__name__,'time':time.time()})
        from .notices import notify
        notify(home,'failure',{'reason':'latest_backup_refresh_failed'})
        return False


def prune_finished_snapshots(home):
    home=Path(home);settings=read_json(home/'settings.json');active=read_json(home/'active.json')
    if not settings.get('backup_directory') or not settings.get('backup_cleanup_ready',True) or active.get('pending_gui_persistence'):return
    root=backup_root(home);validate_bundle(root/'provider-original');validate_bundle(root/'agentroute-current')
    backed=read_json(root/'agentroute-current/active.json')
    if any(backed.get(k)!=active.get(k) for k in ('generation','egress_revision')):return
    final={'COMMITTED','ROLLED_BACK','RECOVERY_UNCONFIRMED','SELFTEST_RECOVERED'}
    transactions=list((home/'transactions').glob('*'))
    if any(read_json(t/'journal.json',{}).get('state') not in final for t in transactions):return
    removed=[]
    for t in transactions:
        for name in ('snapshot.json','state-before.json','source-before.js','source-candidate.js','candidate.json'):
            p=t/name
            if p.is_file() and not p.is_symlink():p.unlink();removed.append(str(p.relative_to(home)))
    # These files are generated, credential-bearing scratch configs, not evidence.
    # Callers hold operation.lock; a preflight additionally needs an exited child.
    for directory in (home/'checks').glob('*'):
        for name in ('candidate-native.json','runtime-native.json','candidate.json'):
            p=directory/name
            if p.is_file() and not p.is_symlink():p.unlink();removed.append(str(p.relative_to(home)))
    for directory in (home/'preflights').glob('*'):
        if not (directory/'child-exited.json').is_file():continue
        for name in ('request.json','shadow.json'):
            p=directory/name
            if p.is_file() and not p.is_symlink():p.unlink();removed.append(str(p.relative_to(home)))
    if removed:atomic_json(home/'snapshot-retention.json',{'time':time.time(),'removed':removed,'permanent_sets':2})
    for cache_root in (home/'cache',Path(settings['core_home'])/'rules/agent-route/generations') if settings.get('core_home') else (home/'cache',):
        for p in cache_root.glob('*'):
            if p.is_dir() and not p.is_symlink() and SHA.fullmatch(p.name) and p.name!=active['generation']:
                if read_json(p/'provenance.json',{}).get('upstream_repository')==UPSTREAM:
                    shutil.rmtree(p)


def restore_current(home):
    from .backend import Backend
    from .transaction import new_transaction,recover
    home=Path(home);settings=read_json(home/'settings.json');root=backup_root(home)/'agentroute-current'
    validate_bundle(root);snapshot=read_json(root/'snapshot.json');before=read_json(root/'active.json')
    with lock(home/'operation.lock'):
        backend=Backend(settings);source=backend.extension.read_text()
        verify(root/'rule-data',fresh=False)
        for target in (home/'cache'/before['generation'],Path(settings['core_home'])/'rules/agent-route/generations'/before['generation']):
            valid=False
            try:
                verify(target,fresh=False)
                valid=digest((target/'manifest.json').read_bytes())==digest((root/'rule-data/manifest.json').read_bytes())
            except (OSError,ValueError):pass
            if not valid:
                target.parent.mkdir(parents=True,exist_ok=True)
                stage=target.parent/('.restore-'+uuid.uuid4().hex);shutil.copytree(root/'rule-data',stage)
                retired=target.parent/('.damaged-'+uuid.uuid4().hex)
                if target.exists():os.replace(target,retired)
                os.replace(stage,target)
                if retired.exists():shutil.rmtree(retired)
        tx=new_transaction(home,snapshot,before,source,snapshot['config'],before['generation'],before['egress_revision'],before['expected_ip'])
        atomic_json(home/'latest-transaction.json',{'transaction':str(tx)})
        result=recover(tx,manual=True)
        if result=='ROLLED_BACK':prune_finished_snapshots(home)
        return result
