import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from transport_tariffs import route_rows,update_transport_references
class TransportTests(unittest.TestCase):
    def test_multiline_routes_and_thousand_unit(self):
        tables=[[['RECEPCIÓN','DESPACHO',None,None],['NEUQUÉN','Bahía Blanca\nBuenos Aires','17.917,53\n24.265,80','2,08\n3,30']]]
        rows=route_rows(tables,'TGS','TI','2026-10-01','official','711/2026')
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['rate']/1000,24.2658);self.assertEqual(rows[1]['retainedPercent'],3.3)
    def test_misaligned_routes_rejected(self):
        with self.assertRaises(ValueError):route_rows([[['RECEPCIÓN','DESPACHO',None,None],['NEUQUÉN','A\nB','10,00','1,00\n2,00']]],'TGS','TF','2026-10-01','official','711/2026')
    def test_failure_preserves_previous_values(self):
        rows=[dict(company='TGS',rate=684.18,period='2026-10-01')];state={'transportReferences':{'rows':rows}}
        def fetch(url,**kw):raise OSError('source unavailable')
        with tempfile.TemporaryDirectory() as tmp:update_transport_references(state,Path(tmp),fetch,lambda:'2026-11-01T12:00:00-03:00')
        self.assertEqual(state['transportReferences']['rows'],rows);self.assertEqual(state['transportReferences']['status'],'partial')
    def test_new_resolution_discovered_without_hardcoded_number(self):
        state={};url='https://wss.enargas.gov.ar/service.asmx/ObtenerArchivo?Numero=0901&Ano=2026'
        html=f'<table><tr><td>Transportadora de Gas del Sur S.A.</td><td><a href="{url}">901/2026</a></td></tr><tr><td>Transportadora de Gas del Norte S.A.</td><td><a href="{url}">902/2026</a></td></tr></table>'.encode()
        def fetch(u,**kw):return html if u.endswith('.php') else b'new official PDF'
        def parse(raw,company,u):return [dict(id=company,company=company,rate=700,period='2026-11-01',sourceUrl=u)]
        with tempfile.TemporaryDirectory() as tmp,patch('transport_tariffs.parse_transport',side_effect=parse):update_transport_references(state,Path(tmp),fetch,lambda:'2026-11-01T12:00:00-03:00')
        self.assertEqual(len(state['transportReferences']['rows']),2);self.assertEqual(state['transportReferences']['status'],'updated');self.assertEqual(state['transportReferences']['rows'][0]['period'],'2026-11-01')
if __name__=='__main__':unittest.main()
