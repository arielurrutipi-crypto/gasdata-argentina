import io,zipfile,unittest
from tariff_comparison import read_xlsx,FIELDS

def workbook(value='12,34',missing=False):
    cols=FIELDS[:-1] if missing else FIELDS
    rows=['<row r="1">'+''.join(f'<c r="{chr(65+i)}1" t="inlineStr"><is><t>{field}</t></is></c>' for i,field in enumerate(cols))+'</row>']
    vals=['BAGSA','GLP','Z1','Zona 1','Plenas','SinSEF','Residencial','R1','Cargo Fijo ($)',value,'0','','01/08/2026']
    rows.append('<row r="2">'+''.join(f'<c r="{chr(65+i)}2" t="inlineStr"><is><t>{val}</t></is></c>' for i,val in enumerate(vals))+'</row>')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z: z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>')
    return output.getvalue()
class ComparisonReaderTests(unittest.TestCase):
    def test_decimal_and_zero_are_preserved(self):
        for text,expected in [('12,34',12.34),('0',0.0),('-4,78',-4.78),('23.039,79',23039.79)]:
            d=read_xlsx(workbook(text));self.assertEqual(d['values'][9][d['rows'][0][9]],expected)
    def test_changed_schema_is_rejected(self):
        with self.assertRaises(ValueError):read_xlsx(workbook(missing=True))
    def test_unreadable_amount_is_rejected(self):
        with self.assertRaises(ValueError):read_xlsx(workbook('pendiente'))
if __name__=='__main__':unittest.main()
