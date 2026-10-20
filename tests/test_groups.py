import sys,json,threading,tempfile,unittest,urllib.request,urllib.error
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import monitor as m
from push_support import validate_groups,preferences
class Groups(unittest.TestCase):
 def test_validation_and_membership_guards(self):
  groups=[dict(id='g_1',name=' Desktop ',hidden=True)]
  clean,members=validate_groups(groups,{'1:a':'g_1'},{'1:a'})
  self.assertEqual(clean[0]['name'],'Desktop');self.assertTrue(clean[0]['hidden'])
  for bad_groups,bad_members in [(groups,{'1:a':'missing'}),(groups,{'__overview__':'g_1'}),(groups*2,{}),([dict(id='x',name=' ')],{}),([dict(id='x',name='ok',hidden='yes')],{})]:
   with self.assertRaises(ValueError):validate_groups(bad_groups,bad_members,{'1:a'})
 def test_view_modes_and_legacy_migration(self):
  for view in (0,1,2):
   clean,_=validate_groups([dict(id='g',name='Group',view=view)],{},set())
   self.assertEqual(clean[0]['view'],view);self.assertEqual(clean[0]['hidden'],view!=2)
  for hidden in (False,True):
   clean,_=validate_groups([dict(id='g',name='Group',hidden=hidden)],{},set())
   self.assertEqual(clean[0]['view'],0 if hidden else 2)
  for invalid in (True,-1,3,'summary',None):
   with self.assertRaises(ValueError):validate_groups([dict(id='g',name='Group',view=invalid)],{},set())
 def test_legacy_defaults(self):
  db=m.connect(':memory:')
  try:
   value=preferences(db);self.assertEqual(value['groups'],[]);self.assertEqual(value['group_members'],{})
  finally:db.close()
 def test_save_rename_reorder_delete_preserves_clients_history_and_legacy_save(self):
  with tempfile.TemporaryDirectory() as temp:
   path=str(Path(temp)/'db');db=m.connect(path)
   def client(up):return dict(id='1:a',email='Demo',inbound='1',up=up,down=0,enabled=True)
   m.ingest(db,[client(0)],60);m.ingest(db,[client(100)],120);db.close()
   server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler);origin=f'http://127.0.0.1:{server.server_port}'
   server.cfg=dict(database=path,timezone='UTC',max_gap_seconds=150,web=dict(auth=False,public_origin=origin))
   worker=threading.Thread(target=server.serve_forever);worker.start()
   def save(value):
    with urllib.request.urlopen(urllib.request.Request(origin+'/api/preferences',data=json.dumps(value).encode(),headers={'Origin':origin})) as response:self.assertEqual(response.status,200)
   def config():
    with urllib.request.urlopen(origin+'/api/config') as response:return json.load(response)['preferences']
   try:
    value=dict(order=['1:a'],favorites=['1:a'],groups=[dict(id='g1',name='A'),dict(id='g2',name='B')],group_members={'1:a':'g1'})
    save(value);save(dict(order=['1:a'],favorites=[]))
    self.assertEqual(config()['group_members'],{'1:a':'g1'})
    value['groups']=[dict(id='g2',name='Renamed',view=1),dict(id='g1',name='A')];value['ungrouped_view']=1;save(value)
    self.assertEqual(config()['groups'][0]['name'],'Renamed')
    self.assertEqual(config()['groups'][0]['view'],1)
    self.assertEqual(config()['ungrouped_view'],1)
    value['groups']=[];value['group_members']={};save(value)
    self.assertEqual(config()['groups'],[])
    with closing(m.connect(path)) as check:
     self.assertEqual(check.execute('SELECT count(*) FROM clients').fetchone()[0],1)
     self.assertEqual(check.execute('SELECT SUM(up) FROM samples').fetchone()[0],100)
    value['groups']=[dict(id='g1',name='A')];value['group_members']={'__overview__':'g1'}
    with self.assertRaises(urllib.error.HTTPError) as error:save(value)
    self.assertEqual(error.exception.code,400)
    self.assertEqual(config()['groups'],[])
    value['group_members']={};value['ungrouped_view']=True
    with self.assertRaises(urllib.error.HTTPError) as error:save(value)
    self.assertEqual(error.exception.code,400)
    self.assertEqual(config()['ungrouped_view'],1)
   finally:server.shutdown();server.server_close();worker.join()
if __name__=='__main__':unittest.main()
