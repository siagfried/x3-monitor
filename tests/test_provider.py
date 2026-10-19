import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import json
import unittest
import monitor as m
import provider


def fixture(**changes):
    value = dict(error=0, plan_monthly_data=1000*1024**3, data_counter=154*1024**3,
                 monthly_data_multiplier=1, data_next_reset=1794062530, plan='test-plan',
                 node_location='California', ip_addresses=['192.0.2.1'], suspended=False,
                 email='private@example.test', api_key='DO_NOT_EXPOSE')
    value.update(changes)
    return value


class Provider(unittest.TestCase):
    def test_units_multiplier_and_raw_fields_are_filtered(self):
        value = provider.normalize(fixture(monthly_data_multiplier=0.5))
        self.assertEqual((value['used_gb'],value['total_gb'],value['remaining_gb']),(77,500,423))
        self.assertNotIn('private@example.test',json.dumps(value))
        self.assertNotIn('DO_NOT_EXPOSE',json.dumps(value))

    def test_post_only_fixed_read_endpoint(self):
        class Fake:
            def open(self,request,timeout):
                self.request=request
                return io.BytesIO(json.dumps(fixture()).encode())
        opener=Fake()
        provider.fetch({'veid':'1','api_key':'SECRET','endpoint':'https://evil.test/stop'},opener)
        self.assertEqual(opener.request.full_url,'https://api.64clouds.com/v1/getServiceInfo')
        self.assertEqual(opener.request.get_method(),'POST')
        self.assertNotIn('SECRET',opener.request.full_url)

    def test_official_timestamp_and_failed_queries_keep_last_data(self):
        db=m.connect(':memory:')
        try:
            self.assertTrue(provider.poll(db,{},now=1000,fetcher=lambda _:provider.normalize(fixture())))
            status=provider.status(db,m.ZoneInfo('Asia/Shanghai'),now=1000,uptime_reader=lambda:'123.00 400')
            self.assertEqual(status['info']['next_reset_time'],'2026-11-07 22:42:10')
            self.assertEqual(status['uptime_seconds'],123)
            self.assertTrue(status['fresh'])
            def fail(_):raise RuntimeError('DO_NOT_EXPOSE')
            self.assertFalse(provider.poll(db,{},now=1060,fetcher=fail))
            status=provider.status(db,m.ZoneInfo('UTC'),now=1060,uptime_reader=lambda:'123 0')
            self.assertFalse(status['fresh'])
            self.assertEqual(status['info']['total_gb'],1000)
            self.assertNotIn('DO_NOT_EXPOSE',json.dumps(status))
            provider.poll(db,{},now=1120,fetcher=lambda _:provider.normalize(fixture(data_counter=0,data_next_reset=1796654530)))
            self.assertEqual(provider.status(db,m.ZoneInfo('UTC'),now=1120)['info']['used_gb'],0)
        finally:db.close()

    def test_stale_and_suspended_are_distinct(self):
        db=m.connect(':memory:')
        try:
            provider.poll(db,{},now=1000,fetcher=lambda _:provider.normalize(fixture(suspended=True)))
            self.assertTrue(provider.status(db,m.ZoneInfo('UTC'),now=1000)['info']['suspended'])
            self.assertFalse(provider.status(db,m.ZoneInfo('UTC'),now=1181)['fresh'])
        finally:db.close()


class ProviderDetails(unittest.TestCase):
    def test_read_allowlist_rejects_mutation_before_network(self):
        with self.assertRaises(ValueError):
            provider.query({'veid':'1','api_key':'SECRET'},'snapshot/create')

    def test_backup_tokens_links_and_keys_are_not_exposed(self):
        raw={'error':0,'backups':{'RESTORE_TOKEN':{'timestamp':1000,'size':'123','downloadLinkSSL':'https://secret.test/token','api_key':'SECRET','os':'Debian'}}}
        data=provider.normalize_details('backups',raw,{'api_key':'SECRET'},1000)
        self.assertEqual(data['items'][0]['size_bytes'],123)
        for secret in ('RESTORE_TOKEN','secret.test','SECRET'):
            self.assertNotIn(secret,json.dumps(data))
        data=provider.normalize_details('snapshots',{'error':0,'snapshots':[{'description':'SECRET private_abc https://example.test/token','size':'42'}]}, {'api_key':'SECRET'},1000)
        self.assertNotIn('SECRET',json.dumps(data))
        self.assertNotIn('private_abc',json.dumps(data))
        self.assertNotIn('example.test',json.dumps(data))
        self.assertEqual(data['items'][0]['timestamp'],0)

    def test_logs_order_retention_and_ip(self):
        now=40_000_000
        data=provider.normalize_details('audit',{'error':0,'log_entries':[{'timestamp':1,'summary':'old'},{'timestamp':now,'summary':'new','requestor_ipv4':2130706433}]},{},now)
        self.assertEqual(len(data['items']),1)
        self.assertEqual(data['items'][0]['ip'],'127.0.0.1')

    def test_failures_are_separate_and_preserve_last_success(self):
        db=m.connect(':memory:')
        def good(cfg,name):
            if name=='backup/list':return {'error':0,'backups':{'TOKEN':{'size':123,'timestamp':1000}}}
            return {'error':0}
        def partial(cfg,name):
            if name=='backup/list':raise RuntimeError('SECRET')
            return {'error':0}
        try:
            self.assertTrue(provider.poll_details(db,{},now=1000,query_fn=good))
            self.assertFalse(provider.poll_details(db,{},now=1060,query_fn=partial))
            details=provider.status(db,m.ZoneInfo('UTC'),now=1060)['details']
            self.assertFalse(details['backups']['fresh'])
            self.assertTrue(details['audit']['fresh'])
            self.assertEqual(details['backups']['data']['items'][0]['size_bytes'],123)
            self.assertNotIn('SECRET',json.dumps(details))
            self.assertNotIn('TOKEN',json.dumps(details))
        finally:db.close()

    def test_abuse_records_and_evidence(self):
        data=provider.normalize_details('suspensions',{'error':0,'suspensions':[{'record_id':7,'flag':'test','evidence_record_id':9,'abuse_points':5}], 'evidence':{'9':'details SECRET'},'total_abuse_points':5,'max_abuse_points':100},{'api_key':'SECRET'},1000)
        self.assertEqual(data['items'][0]['reason'],'test')
        self.assertIn('details',data['items'][0]['evidence'])
        self.assertNotIn('SECRET',json.dumps(data))


if __name__=='__main__':unittest.main()
