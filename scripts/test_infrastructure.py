import copy,json,sys,unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import infrastructure as I

def project(id='P02'):
    return {'id':id,'name':'Duplicar Norte','stage':'Construcción','phase':'En ejecución','verifiedStatus':'En construcción','verifiedAt':'2026-10-13',
      'matching':{'strong':['duplicar norte'],'combinations':[['oldelval','auca mahuida']], 'exclude':[]},'sources':[],'progress':None,'history':[]}
def registry():return {'projects':[project()], 'sources':[], 'news':{}, 'candidates':{}, 'sourceChecks':{}, 'meta':{}}
NOW=datetime(2026,10,14,12,tzinfo=timezone.utc)
CHECKED=NOW.isoformat()
def row(**kw):
    d={'url':'https://example.com/noticia','title':'Duplicar Norte inició las obras','desc':'Avance físico global del 72 %.','source':'Medio','publishedAt':'2026-10-14T09:00:00-03:00','dateType':'published'};d.update(kw);return d

class InfrastructureTests(unittest.TestCase):
    def test_no_generic_match(self):
        self.assertFalse(I.matches(project(),'Oldelval invierte en Vaca Muerta'))
        self.assertFalse(I.matches(project(),'Gasoductos e infraestructura argentina'))
    def test_distinct_alias_and_combination(self):
        self.assertTrue(I.matches(project(),'Novedades de DUPLICAR NORTE'))
        self.assertTrue(I.matches(project(),'Oldelval trabaja en Auca Mahuida'))
    def test_alias_boundaries(self):
        self.assertFalse(I.matches(project(),'Duplicar Nortes no es nombre del proyecto'))
    def test_exclusions(self):
        p=project();p['matching']['exclude']=['minería']
        self.assertFalse(I.matches(p,'Duplicar Norte minería'))
    def test_url_dedup(self):
        self.assertEqual(I.canonical_url('http://www.example.com/noticia/?utm_source=x#abc'),I.canonical_url('https://example.com/noticia'))
    def test_archive_and_separate_candidates(self):
        r=I.update_registry(registry(),[row()],None,NOW,CHECKED,official=False)
        self.assertEqual(len(r['news']),1)
        self.assertTrue(any(c['field']=='progress' and c['proposal']==72 for c in r['candidates'].values()))
        self.assertEqual(r['projects'][0]['verifiedStatus'],'En construcción')
        self.assertIsNone(r['projects'][0]['progress'])
    def test_archive_persists_when_news_roll_off(self):
        r=I.update_registry(registry(),[row()],None,NOW,CHECKED,official=False)
        r2=I.update_registry(r,[],None,NOW+timedelta(days=100),(NOW+timedelta(days=100)).isoformat(),official=False)
        self.assertEqual(len(r2['news']),1)
    def test_duplicate_article_is_one_per_project(self):
        r=I.update_registry(registry(),[row(),row(url='http://example.com/noticia/?utm_source=foo')],None,NOW,CHECKED,official=False)
        self.assertEqual(len(r['news']),1)
    def test_unknown_publication_date_not_detection_date(self):
        r=I.update_registry(registry(),[row(dateType='unknown')],None,NOW,CHECKED,official=False)
        n=next(iter(r['news'].values()));self.assertIsNone(n['publishedAt']);self.assertEqual(n['firstDetectedAt'],CHECKED)
    def test_old_progress_is_historical(self):
        r=I.update_registry(registry(),[row(publishedAt='2025-09-17T10:00:00-03:00')],None,NOW,CHECKED,official=False)
        self.assertTrue(all(c['status']=='historical' for c in r['candidates'].values()))
    def test_no_inferred_progress(self):
        self.assertFalse(any(c['field']=='progress' for c in I.signals('Duplicar Norte','Continúan los trabajos de construcción')))
        self.assertFalse(any(c['field']=='progress' for c in I.signals('Duplicar Norte','El 80 % de la capacidad fue contratada')))
    def test_capacity_contest_is_not_construction_tender(self):
        self.assertFalse(I.signals('TGS lanza concursos abiertos para adjudicar capacidad de transporte firme',''))
    def test_component_financial_and_invalid_progress(self):
        s=I.signals('Obras','Avance financiero del 30 % del presupuesto.')
        self.assertEqual(next(x for x in s if x['field']=='progress')['scope'],'Financiero')
        s=I.signals('Obras','Avance de obra del 80 % en los cruces especiales.')
        self.assertIn('Componente',next(x for x in s if x['field']=='progress')['scope'])
        self.assertFalse(any(x['field']=='progress' for x in I.signals('Obra','avance global del 120 %')))
    def test_g07_always_removed(self):
        r=registry();r['projects'].append(project('G07'));r['news']['old']={'projectId':'G07'};r['candidates']['old']={'projectId':'G07'}
        r=I.update_registry(r,[],None,NOW,CHECKED,official=False)
        self.assertNotIn('G07',[x['id'] for x in r['projects']]);self.assertNotIn('old',r['news']);self.assertNotIn('old',r['candidates'])
    def test_failure_preserves_state_and_last_success(self):
        r=registry();r['sourceChecks']['https://example.com/']={'status':'ok','checkedAt':'2026-10-01','lastSuccessAt':'2026-10-01'}
        def fail(*a,**kw):raise RuntimeError('network')
        with patch.object(I,'OFFICIAL_HUBS',[('Official','https://example.com/')]):
            updated=I.update_registry(r,[],fail,NOW,CHECKED)
        self.assertEqual(updated['projects'],r['projects'])
        self.assertEqual(updated['sourceChecks']['https://example.com/']['lastSuccessAt'],'2026-10-01')
        self.assertEqual(updated['meta']['officialStatus'],'partial')
    def test_daily_frequency_and_error_backoff(self):
        self.assertFalse(I.due({'status':'ok','checkedAt':CHECKED},NOW+timedelta(hours=1),24))
        failed={'status':'error','checkedAt':CHECKED,'retryAt':(NOW+timedelta(hours=6)).isoformat()}
        self.assertFalse(I.due(failed,NOW+timedelta(hours=5),168))
        self.assertTrue(I.due(failed,NOW+timedelta(hours=7),168))
    def test_explicit_review_required_for_promotion(self):
        r=I.update_registry(registry(),[row()],None,NOW,CHECKED,official=False)
        c=next(x for x in r['candidates'].values() if x['field']=='progress')
        I.apply_decisions(r,{'decisions':[{'id':'x','candidateId':c['id'],'outcome':'accept','value':72,'reviewedAt':CHECKED,'effectiveDate':'2026-10-14','scope':'component'}]})
        self.assertIsNone(r['projects'][0]['progress'])
        I.apply_decisions(r,{'decisions':[{'id':'y','candidateId':c['id'],'outcome':'accept','value':72,'reviewedAt':CHECKED,'effectiveDate':'2026-10-14','scope':'global_physical'}]})
        self.assertEqual(r['projects'][0]['progress']['value'],72)
        self.assertEqual(len(r['projects'][0]['history']),1)
    def test_document_publication_date_and_no_sidebar_pollution(self):
        raw=b'<html><meta property="article:published_time" content="2026-10-14"><article><h1>Duplicar Norte</h1><p>Avance global del 72 %</p><aside>Otra noticia 90 %</aside></article></html>'
        d=I.parse_document(raw,'https://example.com/a');self.assertEqual(d['date'],'2026-10-14');self.assertNotIn('Otra noticia',d['body'])
    def test_atomic_output(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'data.json';I.atomic_write(p,registry());self.assertTrue(json.loads(p.read_text())['projects']);self.assertFalse(p.with_suffix('.tmp').exists())

if __name__=='__main__':unittest.main()
