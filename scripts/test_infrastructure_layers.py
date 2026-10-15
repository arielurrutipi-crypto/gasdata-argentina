import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import infrastructure_layers as I

class LayerTests(unittest.TestCase):
 def test_geographic_validation(self):
  self.assertTrue(I.valid_geometry({'type':'Point','coordinates':[-60,-35]}))
  self.assertFalse(I.valid_geometry({'type':'Point','coordinates':[-600,-35]}))
  self.assertFalse(I.valid_geometry({'type':'LineString','coordinates':[]}))
  self.assertFalse(I.valid_geometry({'type':'Point','coordinates':[float('nan'),-35]}))
 def test_domains_and_precision(self):
  self.assertEqual(I.decode({'owner':1},[{'name':'owner','domain':{'codedValues':[{'code':1,'name':'TGS'}]}}])['owner'],'TGS')
  self.assertEqual(I.round_coords([[-60.123456789,-35.987654321]]),[[-60.12346,-35.98765]])
 def test_cadence_and_failure_backoff(self):
  now=datetime(2026,10,15,tzinfo=timezone.utc)
  self.assertFalse(I.due({'nextCheckAt':(now+timedelta(days=7)).isoformat()},now))
  self.assertFalse(I.due({'status':'error','retryAt':(now+timedelta(hours=6)).isoformat()},now))
  self.assertTrue(I.due({'status':'error','retryAt':(now-timedelta(minutes=1)).isoformat()},now))
 def test_failure_keeps_last_valid_layer(self):
  now=datetime(2026,10,15,tzinfo=timezone.utc);old='2026-10-01T00:00:00+00:00'
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'layers.json';p.write_text(json.dumps({'layers':[{'id':'network','status':'ok','lastSuccessAt':old,'features':[{'geometry':{'type':'Point','coordinates':[-60,-35]}}]}]}))
   with patch.object(I,'SPECS',[('network','Red','https://example.com','Oficial')]):
    data=I.refresh_layers(lambda *a,**k:(_ for _ in ()).throw(ValueError('offline')),now,p)
   r=data['layers'][0];self.assertEqual(r['lastSuccessAt'],old);self.assertEqual(len(r['features']),1);self.assertEqual(r['status'],'error')
 def test_empty_response_is_rejected(self):
  def fetch(url,**kw):return json.dumps({'features':[]} if '/query?' in url else {'fields':[]}).encode()
  with self.assertRaises(ValueError):I.arcgis(fetch,'https://example.com','network')
 def test_truncated_arcgis_response_is_completed_by_ids(self):
  from urllib.parse import parse_qs,urlparse
  feature={'type':'Feature','geometry':{'type':'Point','coordinates':[-60,-35]},'properties':{'Nombre':'Referencia'}}
  def fetch(url,**kw):
   q=parse_qs(urlparse(url).query)
   if '/query?' not in url:return json.dumps({'fields':[]}).encode()
   if 'returnIdsOnly' in q:return json.dumps({'objectIds':[1,2]}).encode()
   if 'objectIds' in q:return json.dumps({'features':[feature,feature]}).encode()
   return json.dumps({'features':[feature],'exceededTransferLimit':True}).encode()
  rows,_=I.arcgis(fetch,'https://example.com','network');self.assertEqual(len(rows),2)
 def test_snapshot_has_five_attributed_layers(self):
  data=json.loads(I.OUTPUT.read_text());self.assertEqual({l['id'] for l in data['layers']},{'network','enarsa','international','compressors','basins'})
  for l in data['layers']:
   self.assertTrue(l['sourceUrl'].startswith('https://'));self.assertTrue(l['features']);self.assertTrue(l['lastSuccessAt'])
   self.assertTrue(all(I.valid_geometry(f['geometry']) for f in l['features']))
  self.assertGreaterEqual(len(next(l for l in data['layers'] if l['id']=='basins')['features']),5)

if __name__=='__main__':unittest.main()
