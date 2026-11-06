from pathlib import Path
from datetime import datetime, timezone, timedelta
import copy
import json
import shutil
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

from agentroute_sync.common import atomic_json, digest, yaml_load
from agentroute_sync import adapter, data, transaction
from agentroute_sync.backend import Backend
from agentroute_sync.notices import notify

LEGACY = r'''
const routingData={group:'中转节点',defaultTransit:'airport',domains:['+.cn'],cncidrs:['1.0.1.0/24'],lanRules:['DOMAIN-SUFFIX,lan,DIRECT','IP-CIDR,198.18.0.0/16,DIRECT,no-resolve']};
const newExit = {"type":"socks5","server":"old.example.invalid","port":1080,"username":"fixture-user","password":"fixture-password","udp":false};
function legacyMain(config) {
 const prefix='🌐固定出口 · ';
 const originals=(config.proxies||[]).filter(p => !(p.name.indexOf(prefix)===0 && p.type==='socks5' && p.server===newExit.server && p.port===newExit.port));
 const eligible=originals.filter(p=>p.server);
 const chains=eligible.map(p=>{const name=prefix+p.name;return Object.assign({},newExit,{name, type: 'socks5', udp: false, 'dialer-proxy': p.name});});
 config.proxies=originals.concat(chains);
 config['proxy-groups']=[{name:routingData.group,type:'select',proxies:chains.map(p=>p.name)}];
 config['rule-providers']={ 'pluwen-china-domain':{type:'inline',behavior:'domain',payload:routingData.domains},'loyalsoldier-cncidr':{type:'inline',behavior:'ipcidr',payload:routingData.cncidrs}};
 config.dns={enable:true,ipv6:false,'nameserver-policy':{},fallback:[]};
 return config;
}
// AgentRoute 2026-11-06: preserve transport chains and manual selector.
function main(config) {return legacyMain(config);}
'''

def original():
    return {'mode':'rule','tun':{'enable':True},'proxies':[{'name':'airport','type':'socks5','server':'entry.example.invalid','port':1080}], 'ipv6':True}

class AdapterSafety(unittest.TestCase):
    def setUp(self):
        self.node=shutil.which('node')
        if not self.node:self.skipTest('Node is required by the installed client adapter')
    def render(self,source=LEGACY,config=None,new_exit=None,protected=()):
        return adapter.render(source,original() if config is None else config,'a'*40,['🌐固定出口 · airport'],self.node,new_exit,protected)
    def test_rotation_entry_port_and_repeated_generation_are_idempotent(self):
        script,old=self.render()
        new={'type':'socks5','server':'new.example.invalid','port':2080,'username':'new-user','password':'new-password','udp':False}
        script,result=self.render(script,old,new)
        self.assertEqual(len(result['proxies']),2)
        self.assertEqual(result['proxies'][1]['server'],new['server'])
        self.assertEqual(result['proxies'][1]['dialer-proxy'],'airport')
        self.assertEqual(self.render(script,result)[1],result)
    def test_protocol_change_uses_new_type_without_old_chain_residue(self):
        script,old=self.render()
        new={'type':'http','server':'new.example.invalid','port':443,'tls':True,'username':'fixture','password':'fixture','udp':False}
        _,result=self.render(script,old,new)
        self.assertEqual(result['proxies'][1]['type'],'http')
        self.assertEqual(len(result['proxies']),2)
    def test_ambiguous_user_proxy_is_not_deleted(self):
        config=original();config['proxies'].append({'name':'🌐固定出口 · custom','type':'socks5','server':'custom.example.invalid','port':9})
        with self.assertRaises(ValueError):self.render(config=config)
    def test_exact_local_policy_precedes_generic_reject_and_stays_after_repeat(self):
        host='api.example.org';script,result=self.render(protected=[host])
        self.assertEqual(result['rules'][1],'DOMAIN,'+host+',中转节点')
        self.assertIn('#中转节点',result['dns']['nameserver-policy'][host][0])
        _,again=self.render(script,result,protected=[host]);self.assertEqual(again['rules'],result['rules'])
        self.assertNotIn('DOMAIN-SUFFIX,example.org,中转节点',result['rules'])
    def test_global_ipv6_tun_and_original_nodes_are_preserved(self):
        _,result=self.render();self.assertEqual(result['tun'],original()['tun']);self.assertEqual(result['ipv6'],True)
        self.assertEqual(result['proxies'][0],original()['proxies'][0])
        self.assertFalse(any('198.18.0.0/16,DIRECT' in r for r in result['rules']))
    def test_cyclic_or_direct_escape_graph_rejected(self):
        config={'proxies':[{'name':'a','dialer-proxy':'b'},{'name':'b','dialer-proxy':'a'}]}
        with self.assertRaisesRegex(ValueError,'cycle'):adapter.graph_check(config)
        config={'proxies':[],'proxy-groups':[{'name':'中转节点','proxies':['DIRECT']}]}
        with self.assertRaises(ValueError):adapter.graph_check(config)
    def test_unsafe_exit_options_rejected(self):
        with self.assertRaises(ValueError):adapter.validate_exit({'type':'socks5','server':'x','port':1,'udp':True})
        with self.assertRaises(ValueError):adapter.validate_exit({'type':'http','server':'x','port':443,'skip-cert-verify':True})

def bundle(root):
    stamp=datetime.now(timezone.utc).isoformat()
    files={};datasets=[]
    for name in data.IDS:
        raw=("payload:\n  - '"+('1.0.1.0/24' if name=='cn-ip' else '+.'+name+'.example')+"'\n").encode()
        p=root/'mihomo'/(name+'.yaml');p.parent.mkdir(exist_ok=True);p.write_bytes(raw)
        path='mihomo/'+name+'.yaml';files[path]=digest(raw)
        datasets.append({'id':name,'mihomo_behavior':'ipcidr' if name=='cn-ip' else 'domain','resources':{'mihomo':{'path':path,'sha256':digest(raw),'entries':1}}})
    index={'schema_version':1,'scope':'public_routing_data_only','generated_at_utc':stamp,'datasets':datasets}
    atomic_json(root/'index.json',index);files['index.json']=digest((root/'index.json').read_bytes())
    manifest={'schema_version':1,'scope':'domestic_direct_and_adblock','generated_at_utc':stamp,'files':files}
    atomic_json(root/'manifest.json',manifest)
    return manifest,index

class DataSafety(unittest.TestCase):
    def test_transport_retry_does_not_change_source_or_hide_final_failure(self):
        with patch('agentroute_sync.data._fetch_once',side_effect=[urllib.error.URLError('EOF'),b'validated-by-caller']) as get,patch('agentroute_sync.data.time.sleep'):
            self.assertEqual(data.fetch('https://raw.githubusercontent.com/example/file'),b'validated-by-caller')
            self.assertEqual(get.call_count,2)
            self.assertEqual(get.call_args_list[0],get.call_args_list[1])
    def test_integrity_and_empty_or_corrupt_payload(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle(root);self.assertEqual(data.verify(root)['counts']['proxy'],1)
            (root/'mihomo/proxy.yaml').write_text("payload:\n - '+.changed.example'\n")
            with self.assertRaisesRegex(ValueError,'hash'):data.verify(root)
        with self.assertRaisesRegex(ValueError,'empty'):data.payload(b'payload:\n')
    def test_unknown_schema_and_mixed_generation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m,i=bundle(root);m['schema_version']=2;atomic_json(root/'manifest.json',m)
            with self.assertRaises(ValueError):data.verify(root)
            m['schema_version']=1;m['generated_at_utc']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat();atomic_json(root/'manifest.json',m)
            with self.assertRaisesRegex(ValueError,'generation'):data.verify(root)
    def test_stale_download_rejected_but_local_rollback_can_verify(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m,i=bundle(root);old=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat();i['generated_at_utc']=old;m['generated_at_utc']=old
            atomic_json(root/'index.json',i);m['files']['index.json']=digest((root/'index.json').read_bytes());atomic_json(root/'manifest.json',m)
            with self.assertRaisesRegex(ValueError,'stale'):data.verify(root)
            self.assertTrue(data.verify(root,fresh=False)['stale'])
    def test_no_arbitrary_program_in_yaml_data(self):
        for raw in [b'!!python/object/apply:os.system [echo]\n',b'payload:\n  run: command\n']:
            with self.assertRaises(ValueError):data.payload(raw)

class GuardSafety(unittest.TestCase):
    def make(self,home,seconds=.01):
        snapshot={'source':'old source','config':{},'selected':{},'owned_aliases':[]}
        return transaction.new_transaction(home,snapshot,{'revision':1,'expected_ip':'192.0.2.1'},'new source',{},'a'*40,'exit-v1','192.0.2.1',seconds=seconds,selftest=True)
    def test_independent_deadline_action_runs_without_success(self):
        with tempfile.TemporaryDirectory() as d:
            tx=self.make(Path(d));self.assertEqual(transaction.watchdog(tx),'SELFTEST_RECOVERED');self.assertTrue((tx/'selftest-restored').exists())
    def test_corrupt_success_record_does_not_disarm(self):
        with tempfile.TemporaryDirectory() as d:
            tx=self.make(Path(d));(tx/'journal.json').write_text('{incomplete')
            # Watchdog is already armed before a later record is damaged.
            plan=json.loads((tx/'recovery-plan.json').read_text())
            with patch('agentroute_sync.transaction.read_json',side_effect=lambda p,default=None: plan if Path(p).name=='journal.json' and not (tx/'ready.json').exists() else __import__('agentroute_sync.common',fromlist=['read_json']).read_json(p,default)):
                self.assertEqual(transaction.watchdog(tx),'SELFTEST_RECOVERED')
    def test_wrong_generation_success_does_not_disarm(self):
        with tempfile.TemporaryDirectory() as d:
            tx=self.make(Path(d));transaction.update(tx,state='COMMITTED',generation='b'*40)
            self.assertEqual(transaction.watchdog(tx),'SELFTEST_RECOVERED')
    def test_no_commit_if_exit_revision_changed(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);tx=self.make(home,seconds=60);atomic_json(home/'active.json',{'revision':2,'expected_ip':'192.0.2.2'})
            with self.assertRaisesRegex(ValueError,'revision'):transaction.commit(tx,{'generation':'a'*40})

class YAMLCompatibility(unittest.TestCase):
    @unittest.skipUnless(Path('/usr/bin/ruby').exists(),'Ruby parser is a Mac integration dependency')
    def test_ipv6_is_not_converted_to_a_ruby_symbol(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.yaml';p.write_text('value: ::1/128\nenabled: true\ntext: on\n')
            self.assertEqual(yaml_load(p),{'value':'::1/128','enabled':True,'text':'on'})
    @unittest.skipUnless(Path('/usr/bin/ruby').exists(),'Ruby parser is a Mac integration dependency')
    def test_arbitrary_ruby_objects_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.yaml';p.write_text('x: !ruby/object:Gem::Installer {}\n')
            with self.assertRaises(ValueError):yaml_load(p)

class ProbeCoverage(unittest.TestCase):
    def test_preview_tests_protected_hosts_through_the_preview_proxy(self):
        backend=Backend({'core_home':'/unused','extension':'/unused','core_binary':'/unused','node_binary':'/unused',
                         'protected_hosts':['api.example.org']})
        runtime={'mode':'rule','tun':{'enable':True}}
        with patch.object(backend,'api',return_value=runtime),patch.object(backend,'curl',return_value={'passed':True}) as curl:
            result=backend.health('192.0.2.1',rounds=1,proxy='http://127.0.0.1:12345')
        protected=[x for x in curl.call_args_list if x.args[0]=='protected:api.example.org']
        self.assertEqual(len(protected),1)
        self.assertEqual(protected[0].args[3],'http://127.0.0.1:12345')
        self.assertEqual(result['path'],'isolated-preview')
    def test_notices_are_durable_and_deduplicated_even_without_desktop_permission(self):
        with tempfile.TemporaryDirectory() as d,patch('agentroute_sync.notices.subprocess.run',side_effect=OSError) as send:
            notify(d,'review',{'upstream_master':'a'*40})
            notify(d,'review',{'upstream_master':'a'*40})
            self.assertEqual(send.call_count,1)
            records=json.loads((Path(d)/'notices.json').read_text())
            self.assertEqual(len(records),1)
            self.assertFalse(next(iter(records.values()))['desktop_display_verified'])

if __name__=='__main__':unittest.main()
