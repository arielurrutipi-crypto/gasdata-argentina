import unittest
from tariff_pdf import effective_date,encode,decode,norm
from tariff_comparison import FIELDS
class AnnexTests(unittest.TestCase):
    def test_operative_date_overrides_historical_recital(self):
        text='Que las tarifas tienen vigencia a partir del 1° de septiembre de 2026. RESUELVE: ARTÍCULO 1°: Aprobar. ARTÍCULO 6°: Entrarán en vigencia a partir del 1° de octubre de 2026.'
        self.assertEqual(effective_date(text),'2026-10-01')
    def test_missing_operative_date_is_rejected(self):
        with self.assertRaises(ValueError):effective_date('Que se aplica desde septiembre. RESUELVE: ARTÍCULO 1°: Aprobar tarifas.')
    def test_pdf_roundtrip_preserves_only_available_charges(self):
        record={k:'' for k in FIELDS};record.update(EMPRESA='BAGSA',CARGOTIPO='Cargo Variable ($/m3)',CARGO=405.70)
        decoded=decode(encode([record],FIELDS));self.assertEqual(decoded,[record]);self.assertEqual(len(decoded),1)
    def test_multiline_locality_matches(self):
        self.assertEqual(norm('CLAROMECÓ Y\nCOPETONAS'),norm('CLAROMECÓ, COPETONAS'))
if __name__=='__main__':unittest.main()
