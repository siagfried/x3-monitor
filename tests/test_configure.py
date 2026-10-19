import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import configure as c

DNS='server.example.ts.net'
PROXY='http://127.0.0.1:8098'


def cfg(**kwargs):
    return c.make_config(DNS,'123456','TEST_KEY','http://127.0.0.1:2053/panel/','user','password',**kwargs)


def served():
    return {'TCP':{'8443':{'HTTPS':True}},'Web':{DNS+':8443':{'Handlers':{'/':{'Proxy':PROXY}}}}}


class Setup(unittest.TestCase):
    def test_config_is_loopback_tailnet_and_sixty_seconds(self):
        value=cfg()
        self.assertEqual(value['web']['host'],'127.0.0.1')
        self.assertEqual(value['web']['public_origin'],'https://'+DNS+':8443')
        self.assertEqual(value['interval_seconds'],60)
        self.assertFalse(value['web']['auth'])
        self.assertEqual(value['retention_days'],365)

    def test_invalid_provider_and_public_panel_link_rejected(self):
        for veid,key in [('abc','key'),('123',''),('123','bad key')]:
            with self.assertRaises(ValueError):
                c.make_config(DNS,veid,key,'http://127.0.0.1/','user','pass')
        with self.assertRaises(ValueError):cfg(panel_link='https://public.example/')
        with self.assertRaises(ValueError):cfg(connect_host='0.0.0.0')

    def test_existing_ports_and_funnel_are_never_overwritten(self):
        c.require_route_available({},DNS,8443,PROXY)
        c.require_route_available(served(),DNS,8443,PROXY,owned=True)
        with self.assertRaises(ValueError):c.require_route_available(served(),DNS,8443,PROXY)
        other=served();other['Web'][DNS+':8443']['Handlers']['/']['Proxy']='http://127.0.0.1:9999'
        with self.assertRaises(ValueError):c.require_route_available(other,DNS,8443,PROXY,owned=True)
        public=served();public['AllowFunnel']={DNS+':8443':True}
        with self.assertRaises(ValueError):c.require_route_available(public,DNS,8443,PROXY,owned=True)

    def test_public_monitor_origin_is_rejected(self):
        value=cfg()
        value['web']['public_origin']='https://public.example:8443'
        with patch.object(c,'tailnet',return_value=(DNS,{})):
            with self.assertRaises(ValueError):c.preflight(value)

    def test_secret_prompt_uses_getpass_and_never_echoes_value(self):
        stream=io.StringIO()
        with patch.object(c.getpass,'getpass',return_value='TEST_SECRET') as prompt,contextlib.redirect_stdout(stream):
            self.assertEqual(c.ask('API Key',secret=True),'TEST_SECRET')
        prompt.assert_called_once()
        self.assertNotIn('TEST_SECRET',stream.getvalue())

    def test_setup_does_not_run_noninteractively(self):
        with patch.object(c.sys.stdin,'isatty',return_value=False),patch.object(c,'tailnet') as network:
            with self.assertRaises(ValueError):c.wizard()
            network.assert_not_called()

    def test_uninstall_only_removes_exact_owned_route(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)):
            marker=Path(tmp)/'.serve-owned.json'
            marker.write_text(json.dumps(dict(dns=DNS,port=8443,proxy=PROXY)))
            with patch.object(c,'ts_json',return_value=served()),patch.object(c.subprocess,'run') as run:
                c.remove_owned_serve()
                self.assertEqual(run.call_args.args[0],['tailscale','serve','--https=8443','off'])
            self.assertFalse(marker.exists())
            marker.write_text(json.dumps(dict(dns=DNS,port=8443,proxy=PROXY)))
            other=served();other['Web'][DNS+':8443']['Handlers']['/']['Proxy']='http://127.0.0.1:7777'
            with patch.object(c,'ts_json',return_value=other),patch.object(c.subprocess,'run') as run:
                with self.assertRaises(ValueError):c.remove_owned_serve()
                run.assert_not_called()
            self.assertTrue(marker.exists())

    def test_activate_checks_isolation_and_only_adds_chosen_port(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)),patch.object(c,'preflight',return_value=(DNS,8443,PROXY,{})),patch.object(c,'ts_json',return_value=served()),patch.object(c.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            c.activate_serve(cfg())
            self.assertEqual(run.call_args.args[0],['tailscale','serve','--bg','--https=8443',PROXY])
            self.assertTrue((Path(tmp)/'.serve-owned.json').exists())


if __name__=='__main__':unittest.main()
