from pathlib import Path
import copy
import tempfile
import unittest
from unittest.mock import Mock,patch

from agentroute_sync.common import atomic_json,read_json
from agentroute_sync import backups,startup,transaction,mac


class StartupTests(unittest.TestCase):
    def test_waits_for_core_without_sending_network_probes_or_reloading(self):
        backend=Mock();backend.capture.side_effect=[RuntimeError('not ready'),{'ready':True}]
        with patch('agentroute_sync.startup.time.sleep'):
            result=startup.wait_ready(backend,seconds=180)
        self.assertEqual(result,{'ready':True});backend.health.assert_not_called();backend.apply.assert_not_called()

    def test_changed_version_is_not_silently_waited_out(self):
        backend=Mock();backend.ready.side_effect=ValueError('core_version_changed_requires_review')
        with self.assertRaisesRegex(ValueError,'version_changed'),patch('agentroute_sync.startup.time.sleep') as sleep:
            startup.wait_ready(backend)
        sleep.assert_not_called()

    def test_old_boot_pending_transaction_recovers_without_waiting_six_hours(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);tx=home/'transactions/one';tx.mkdir(parents=True)
            atomic_json(tx/'journal.json',{'state':'APPLYING','boot_session':'old','deadline_wall':10**12})
            with patch('agentroute_sync.mac.boot_session_id',return_value='new'),patch('agentroute_sync.mac.recover') as recover,patch('agentroute_sync.mac.unload_guard'):
                mac.recover_pending(home)
            recover.assert_called_once_with(tx)

    def test_old_boot_monotonic_deadline_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'journal.json',{'state':'APPLYING','boot_session':'old','deadline_wall':10**12,'deadline_monotonic':10**12})
            with patch('agentroute_sync.transaction.boot_session_id',return_value='new'),self.assertRaisesRegex(RuntimeError,'previous_boot'):
                transaction.pending(p)

    def test_startup_rejects_direct_fallback_even_with_valid_member_names(self):
        generation='a'*40;spec={'type':'socks5','server':'exit.example.invalid','port':1080,'udp':False}
        node=dict(spec,name='🌐固定出口 · airport',**{'dialer-proxy':'airport','agentroute-generated':True})
        config={'proxies':[{'name':'airport'},node],
                'proxy-groups':[{'name':'中转节点','proxies':[node['name']],'empty-fallback':'REJECT'}],
                'rule-providers':{'agentroute-'+n:{'type':'file','path':'./rules/agent-route/generations/'+generation+'/mihomo/'+n+'.yaml'} for n in ('private','reject','proxy','direct','cn-ip')},
                'dns':{'fallback':[],'nameserver-policy':{}}}
        from agentroute_sync.adapter import egress_revision
        snapshot={'config':config,'exit':spec};active={'generation':generation,'exit_spec':spec,'egress_revision':egress_revision(spec)}
        backend=Mock();backend.group='中转节点';backend.settings={'protected_hosts':[]}
        backend.api.side_effect=lambda method,path: {'proxies':{'中转节点':{'all':[node['name']],'emptyFallback':'REJECT'}}} if path=='/proxies' else {'rules':[{'type':'Match','proxy':'中转节点'}]}
        startup.structural_check(backend,snapshot,active,{})
        bad=copy.deepcopy(snapshot);bad['config']['proxy-groups'][0]['empty-fallback']='DIRECT'
        with self.assertRaisesRegex(ValueError,'empty_group_not_rejected'):startup.structural_check(backend,bad,active,{})


class BackupTests(unittest.TestCase):
    def test_only_latest_set_is_kept_after_successful_publish(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'current'
            for text in ('first','second'):
                stage=root/('stage-'+text);stage.mkdir();(stage/'rules').write_text(text)
                backups.publish(stage,target,'agentroute-current')
                backups.validate_bundle(target)
            self.assertEqual((target/'rules').read_text(),'second')
            self.assertEqual([p.name for p in root.iterdir()],['current'])

    def test_corrupt_backup_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stage=root/'stage';stage.mkdir();(stage/'rules').write_text('good')
            backups.publish(stage,root/'current','agentroute-current');(root/'current/rules').write_text('changed')
            with self.assertRaisesRegex(ValueError,'integrity_failed'):backups.validate_bundle(root/'current')
            atomic_json(root/'current/manifest.json',{'schema_version':1,'files':{'../outside':'a'*64}})
            with self.assertRaisesRegex(ValueError,'path_invalid'):backups.validate_bundle(root/'current')

    def test_failed_successor_does_not_replace_working_backup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old=root/'current';old.mkdir();(old/'value').write_text('known-good');stage=root/'stage';stage.mkdir();(stage/'value').write_text('candidate')
            with patch('agentroute_sync.backups.validate_bundle',side_effect=ValueError('invalid')),self.assertRaises(ValueError):
                backups.publish(stage,old,'agentroute-current')
            self.assertEqual((old/'value').read_text(),'known-good')

    def test_pending_transaction_keeps_its_temporary_recovery_material(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);root=home/'backups';root.mkdir()
            atomic_json(home/'settings.json',{'backup_directory':str(root)})
            state={'generation':'a'*40,'egress_revision':'fixed','pending_gui_persistence':None};atomic_json(home/'active.json',state)
            for name in ('provider-original','agentroute-current'):
                stage=root/('stage-'+name);stage.mkdir();atomic_json(stage/'active.json',state);backups.publish(stage,root/name,name)
            tx=home/'transactions/one';tx.mkdir(parents=True);atomic_json(tx/'journal.json',{'state':'APPLYING'});(tx/'snapshot.json').write_text('temporary')
            backups.prune_finished_snapshots(home);self.assertTrue((tx/'snapshot.json').exists())
            atomic_json(tx/'journal.json',{'state':'COMMITTED'});backups.prune_finished_snapshots(home)
            self.assertFalse((tx/'snapshot.json').exists());self.assertTrue((tx/'journal.json').exists())


if __name__=='__main__':unittest.main()
