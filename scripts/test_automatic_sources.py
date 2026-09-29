import io
import unittest
from automatic_sources import monthly_values, tariff_header, worldbank_latest, update_market

class ReadersTest(unittest.TestCase):
    def test_tariff_effective_date(self):
        self.assertEqual(tariff_header('VIGENCIA DESDE 01 DE SEPTIEMBRE DE 2026 RESFC-2026-539-APN'), ('2026-09-01', '539/2026'))
        with self.assertRaises(ValueError):
            tariff_header('Publicada el 01/09/2026 RESFC-2026-539-APN')

    def test_monthly_coordinates(self):
        words = [dict(text=t, x0=x, x1=x+18, top=y) for t,x,y in [('10,34',640,429), ('6,67',910,448), ('6,3',912,475), ('16,77',841,144), ('8,94',910,195), ('7,79',910,230), ('2026',706,285), ('2026',706,513)]]
        self.assertEqual(monthly_values(words), {'imports': 8.94, 'exports': 6.67})
        with self.assertRaises(ValueError):
            monthly_values([])

    def test_worldbank(self):
        import openpyxl
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = 'Monthly Prices'
        sheet.append(['Period','Natural gas, Europe','Liquefied natural gas, Japan'])
        sheet.append(['2026M07',18.06,13.85])
        sheet.append(['2026M08',21.11,13.94])
        sheet.append(['2026M09','…',None])
        out = io.BytesIO()
        book.save(out)
        self.assertEqual(worldbank_latest(out.getvalue()), {'wb_europe': ('2026-08',21.11),'wb_japan': ('2026-08',13.94)})

    def test_failure_keeps_observation(self):
        data = {'marketPrices':[dict(id='henry_hub',value='2,90',reference='22/09/2026',validatedAt='old')]}
        def fail(*a, **kw):
            raise OSError('offline')
        update_market(data, fail, lambda:'now')
        row = data['marketPrices'][0]
        self.assertEqual((row['value'],row['reference'],row['validatedAt']), ('2,90','22/09/2026','old'))
        self.assertEqual(row['updateStatus'], 'error')

if __name__ == '__main__':
    unittest.main()
