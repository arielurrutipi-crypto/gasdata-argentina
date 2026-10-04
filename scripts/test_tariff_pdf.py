import unittest
from tariff_pdf import effective_date,encode,decode,norm,component_kind,annex_categories
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
    def test_explicit_components_and_category_groups(self):
        self.assertEqual(component_kind('Precio en el Punto de Ingreso\nen el Sistema de Transporte ($/m3)'), 'PIST o Precio de compra ($/m3)')
        self.assertEqual(component_kind('Diferencias Diarias Acumuladas ($/m3)'), 'Diferencia Diaria Acumulada ($/m3)')
        self.assertEqual(component_kind('Costo de Transporte ($/m3)'), 'Costo Transporte ($/m3)')
        self.assertIsNone(component_kind('Precio Incluido en los Cargos por m3 de Consumo ($/m3)'))
        self.assertEqual(set(annex_categories('P1-P2-P3', {'P1','P2','P3','SDB'}, True)), {'P1','P2','P3'})
        self.assertEqual(set(annex_categories('RESIDENCIALES', {'R1','R2 1°'}, True)), {'R1','R2 1°'})
    def test_next_month_is_discovered_by_date(self):
        self.assertEqual(effective_date('RESUELVE: tendrán vigencia a partir del 1° de noviembre de 2026.'), '2026-11-01')
if __name__=='__main__':unittest.main()
