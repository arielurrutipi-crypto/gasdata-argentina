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


if __name__ == '__main__': unittest.main()
