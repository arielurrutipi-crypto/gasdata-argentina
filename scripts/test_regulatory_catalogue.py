import unittest
from regulatory_catalogue import sync_regulator_catalogue, regulator_key, is_technical, relevant_catalogue


class CatalogueTests(unittest.TestCase):
    def source(self, issuer='ENReGE', number=96, desc='APROBAR LA NORMA NAG 444 (2026)'):
        return dict(num=f'{issuer} Resolución FC {number}/2026', issuer=issuer,
                    date='2026-03-10', desc=desc, url=f'https://example.org/{issuer}/{number}')

    def data(self, *rows):
        return dict(regulations=[], resolutionExport=dict(rows=list(rows), checkedAt='2026-10-26T06:00-03:00', complete=True))

    def sync(self, data):
        return sync_regulator_catalogue(data, lambda _: [])

    def test_recovers_nag_with_spaces_without_inventing_publication(self):
        d = self.data(self.source()); self.assertEqual(self.sync(d), 1)
        row = d['regulations'][0]
        self.assertTrue(row['technical']); self.assertIsNone(row['publishedAt'])
        self.assertEqual(row['issuedAt'], '2026-03-10')
        self.assertEqual(self.sync(d), 0)

    def test_same_number_different_regulators_remain_distinct(self):
        d = self.data(self.source('ENARGAS'), self.source('ENReGE'))
        self.assertEqual(self.sync(d), 2)

    def test_existing_bulletin_record_keeps_publication_and_link(self):
        d = self.data(self.source()); r = dict(num='Resolución 96/2026', issuer='ENTE NACIONAL REGULADOR DEL GAS Y LA ELECTRICIDAD',
          url='https://boletinoficial.gob.ar/verified', publishedAt='2026-03-12T00:00-03:00', firstArticle='APROBAR LA NORMA NAG-444', tags=[])
        d['regulations'] = [r]; self.assertEqual(self.sync(d), 0)
        self.assertEqual(r['publishedAt'], '2026-03-12T00:00-03:00')
        self.assertEqual(r['url'], 'https://boletinoficial.gob.ar/verified')
        self.assertIn('catalogueUrl', r)

    def test_pending_bulletin_dates_are_not_cleared(self):
        d = self.data(self.source()); d['regulationScan'] = dict(pendingDates=['2026-10-23'], complete=False)
        self.sync(d); self.assertEqual(d['regulationScan']['pendingDates'], ['2026-10-23'])
        self.assertFalse(d['regulationScan']['complete'])

    def test_retained_partial_catalogue_remains_available(self):
        d = self.data(self.source()); self.sync(d); d['resolutionExport'].update(rows=[], complete=False)
        self.sync(d); self.assertEqual(len(d['regulations']), 1)
        self.assertFalse(d['regulatorCatalogueSync']['complete'])

    def test_commercial_registration_not_technical_by_cited_regulation(self):
        r = dict(disposition='INSCRIBIR como comercializador de gas natural conforme al Reglamento de Comercializadores', tags=['Técnica / operativa'])
        d = self.data(); d['regulations'] = [r]; self.sync(d)
        self.assertFalse(r['technical']); self.assertNotIn('Técnica / operativa', r['tags'])
        self.assertFalse(is_technical(dict(firstArticle='INSCRIBIR A UNA FIRMA COMO COMERCIALIZADOR DE GAS', desc='Antecedentes de normativa técnica y seguridad')))

    def test_technical_decisions_not_sanctions_or_electric_commercial_company(self):
        self.assertFalse(is_technical(dict(desc='SANCIONAR por incumplir la NAG-100')))
        self.assertTrue(is_technical(dict(desc='DISPONER CONSULTA PÚBLICA DEL COMPENDIO DE INSTRUCCIONES PARA LA SUBDISTRIBUCIÓN')))
        self.assertFalse(relevant_catalogue(dict(desc='SANCIONAR A DISTRIBUIDORA Y COMERCIALIZADORA NORTE SOCIEDAD ANÓNIMA')))



class OfficialCatalogueReaderTests(unittest.TestCase):
    def table(self, with_department=True):
        department='<td>DIRECTORIO#ENREGE</td>' if with_department else ''
        return ('<table id="tableFiltro"><tbody><tr><td>970</td><td>19/11/2026</td>'
                '<td>ARTÍCULO 1: APROBAR LA NORMA NAG-201.</td><td>Resolución FC</td>'+department+
                '<td><a href="https://wss.enargas.gov.ar:9092/service.asmx/ObtenerArchivo?Tipo=13&amp;Numero=970&amp;Ano=2026&amp;Reparticion=37">PDF</a></td>'
                '</tr></tbody></table>').encode()

    def test_original_pdf_in_both_official_layouts(self):
        from resolution_export import parse_catalogue
        for with_department in (False,True):
            row=parse_catalogue(self.table(with_department),2026,'ENReGE')[0]
            self.assertIn('ObtenerArchivo?',row['url'])
            self.assertIn('&Reparticion=37',row['url'])
            self.assertEqual(row['date'],'2026-11-19')
            self.assertIn('NAG-201',row['desc'])

    def test_reader_migration_then_preserves_three_hour_frequency(self):
        import io
        from datetime import datetime,timezone
        from unittest.mock import patch
        from resolution_export import update_resolution_export
        current=datetime(2026,11,20,11,tzinfo=timezone.utc)
        data={'resolutionExport':{'complete':True,'checkedAt':current.isoformat(),'rows':[{'url':'old-catalogue'}]}}
        with patch('resolution_export.urllib.request.urlopen',side_effect=lambda *a,**kw:io.BytesIO(self.table())) as request:
            update_resolution_export(data,lambda:current,lambda:current.isoformat())
            self.assertEqual(request.call_count,2)
            self.assertEqual(data['resolutionExport']['readerVersion'],2)
            self.assertIn('ObtenerArchivo?',data['resolutionExport']['rows'][0]['url'])
            update_resolution_export(data,lambda:current,lambda:current.isoformat())
            self.assertEqual(request.call_count,2,'no extra requests within the existing cadence')

    def test_failed_read_keeps_catalogue_and_links(self):
        from datetime import datetime,timezone
        from unittest.mock import patch
        from resolution_export import update_resolution_export
        old=[{'url':'https://example.org/verified.pdf'}]
        data={'resolutionExport':{'rows':old}}
        current=datetime(2026,11,20,11,tzinfo=timezone.utc)
        with patch('resolution_export.urllib.request.urlopen',side_effect=OSError('offline')):
            update_resolution_export(data,lambda:current,lambda:current.isoformat())
        self.assertEqual(data['resolutionExport']['rows'],old)
        self.assertFalse(data['resolutionExport']['complete'])

if __name__ == '__main__': unittest.main()
