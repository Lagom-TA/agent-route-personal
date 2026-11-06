from pathlib import Path
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from agentroute_sync.common import atomic_json,lock
from agentroute_sync import transaction

class RecoveryTests(unittest.TestCase):
    def fixture(self,home):
        home=Path(home);extension=home/'extension.js';extension.write_text('candidate source')
        snapshot={'source':'old source','config':{},'selected':{'中转节点':'fixed-a'},'owned_aliases':['fixed-a']}
        before={'revision':1,'expected_ip':'192.0.2.1','generation':'1'*40,'egress_revision':'exit1'}
        tx=transaction.new_transaction(home,snapshot,before,'candidate source',{},'2'*40,'exit1','192.0.2.1')
        atomic_json(home/'settings.json',{});atomic_json(home/'active.json',before)
        class Fake:
            node='unused'
            def capture(inner):return {'config':{'proxies':[{'name':'original-a'},{'name':'original-b'},{'name':'fixed-a','agentroute-generated':True}]},'runtime':{'mode':'rule','tun':{'enable':True}},'selected':{'中转节点':'fixed-b'}}
            def apply(inner,candidate,selected):inner.applied=(candidate,selected)
            def health(inner,*args,**kwargs):return {'passed':True}
        fake=Fake();fake.extension=extension
        def evaluate(source,config,node):
            self.assertEqual(source,'old source')
            self.assertEqual([p['name'] for p in config['proxies']],['original-a','original-b'])
            return {'proxy-groups':[{'name':'中转节点','proxies':['fixed-a','fixed-b']}],'proxies':config['proxies']}
        return tx,fake,evaluate

    def test_recovery_preserves_new_subscription_nodes_and_selection(self):
        with tempfile.TemporaryDirectory() as home:
            tx,fake,evaluate=self.fixture(home)
            with patch('agentroute_sync.transaction.Backend',return_value=fake),patch('agentroute_sync.transaction.evaluate_script',side_effect=evaluate):
                self.assertEqual(transaction.recover(tx),'ROLLED_BACK')
            self.assertEqual(fake.applied[1],{'中转节点':'fixed-b'})
            self.assertEqual(fake.extension.read_text(),'old source')
            self.assertIn('2'*40,json.loads((Path(home)/'held.json').read_text()))
    def test_watchdog_recovery_is_not_blocked_by_long_operation_lock(self):
        with tempfile.TemporaryDirectory() as home:
            tx,fake,evaluate=self.fixture(home)
            with lock(Path(home)/'operation.lock'):
                with patch('agentroute_sync.transaction.Backend',return_value=fake),patch('agentroute_sync.transaction.evaluate_script',side_effect=evaluate):
                    self.assertEqual(transaction.recover(tx),'ROLLED_BACK')
    def test_unrelated_extension_edits_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as home:
            tx,fake,_=self.fixture(home);fake.extension.write_text('user concurrent edit')
            with patch('agentroute_sync.transaction.Backend',return_value=fake):
                self.assertEqual(transaction.recover(tx),'RECOVERY_UNCONFIRMED')
            self.assertEqual(fake.extension.read_text(),'user concurrent edit')
            self.assertFalse(hasattr(fake,'applied'))
    def test_unavailable_core_still_restores_persistent_files_and_pauses(self):
        with tempfile.TemporaryDirectory() as home:
            tx,fake,_=self.fixture(home);fake.root=Path(home)
            fake.capture=lambda: (_ for _ in ()).throw(RuntimeError('offline control'))
            fake.apply=lambda *args: (_ for _ in ()).throw(RuntimeError('offline control'))
            with patch('agentroute_sync.transaction.Backend',return_value=fake):
                self.assertEqual(transaction.recover(tx),'RECOVERY_UNCONFIRMED')
            self.assertEqual(fake.extension.read_text(),'old source')
            self.assertTrue(json.loads((Path(home)/'active.json').read_text())['paused'])

if __name__=='__main__':unittest.main()
