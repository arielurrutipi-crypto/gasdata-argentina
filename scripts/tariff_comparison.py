"""Read the official normalized tariff XLSX series without rewriting workbooks."""
import io, json, re, zipfile
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import timedelta, datetime
from concurrent.futures import ThreadPoolExecutor

BASE = Path(__file__).resolve().parents[1]
FIELDS = ['EMPRESA','TIPODESUMINISTRO','SUBZONACODIGO','SUBZONA','TIPOTARIFA','CUADRO','SERVICIO','CATEGORIA','CARGOTIPO','CARGO','CONSUMOM3INICIO','CONSUMOM3FIN','VIGENCIADESDE']
NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def read_xlsx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        rows = ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('m:sheetData/m:row',NS)
        def cells(row):
            result = {}
            for cell in row.findall('m:c',NS):
                col = re.sub(r'\d','',cell.get('r',''))
                v = cell.findtext('m:v','',NS)
                if cell.get('t')=='s': v = strings[int(v)] if v else ''
                elif cell.get('t')=='inlineStr': v = ''.join(cell.find('m:is',NS).itertext())
                result[col] = v
            return result
        header = cells(rows[0]); order = {v:k for k,v in header.items()}
        if set(FIELDS)-set(order): raise ValueError('La planilla cambió de estructura: faltan columnas oficiales')
        dictionaries = [[] for _ in FIELDS]; indices = [{} for _ in FIELDS]; encoded = []
        for row in rows[1:]:
            values = cells(row)
            if not values.get(order['EMPRESA']): continue
            record = []
            for i,field in enumerate(FIELDS):
                value = values.get(order[field],'')
                if field=='CARGO':
                    try: value = float(value.replace('.','').replace(',','.')) if ',' in value else float(value)
                    except ValueError: raise ValueError('Importe no numérico en '+row.get('r',''))
                if value not in indices[i]:
                    indices[i][value]=len(dictionaries[i]); dictionaries[i].append(value)
                record.append(indices[i][value])
            encoded.append(record)
        if not encoded: raise ValueError('Planilla sin filas tarifarias')
        return {'schema':1,'columns':FIELDS,'values':dictionaries,'rows':encoded}

def update_tariff_comparison(d, fetch, now, iso):
    state = d.setdefault('tariffComparison',{})
    folder = BASE/'data'/'tariff-comparison'; folder.mkdir(parents=True,exist_ok=True)
    old = {r['key']:r for r in state.get('datasets',[])}
    sources = [r for r in d.get('tariffSeries2026',[]) if r.get('documentType')=='xlsx' and re.fullmatch(r'20\d{2}-\d{2}',r.get('month',''))]
    try: due = now()>=datetime.fromisoformat(state['checkedAt'])+timedelta(hours=3)
    except (ValueError,KeyError): due = True
    due=due or state.get('readerVersion')!=5
    errors=[]; result=[]
    primary='https://www.enargas.gob.ar/secciones/precios-y-tarifas/cuadros-tarifarios.php'
    current=state.get('currentSources',[])
    if due:
        try:
            page=fetch(primary,timeout=40).decode('utf-8')
            discovered=[]
            for href,product,date in re.findall(r'href=[\"\']([^\"\']*tarifas-(gn|glp)-(20\d{6})\.xlsx)[\"\']',page,re.I):
                period=datetime.strptime(date,'%Y%m%d').date().isoformat()
                discovered.append({'documentType':'xlsx','month':period[:7],'validFrom':period,'product':product.upper(),'documentUrl':urljoin(primary,href)})
            if not discovered: raise ValueError('La página vigente no publica enlaces de planillas 2026 reconocibles')
            current=discovered;state['currentSources']=current
        except Exception as error: errors.append({'key':'current-sources','error':str(error)[:180]})
    sources=list({(r['validFrom'],r['product']):r for r in [*sources,*current]}.values())
    latest = {p:max((r['validFrom'] for r in sources if r['product']==p),default='') for p in ('GN','GLP')}
    def process(source):
        key = source['validFrom']+'-'+source['product']; path = folder/(key+'.json'); previous = old.get(key)
        if previous and path.exists() and previous.get('sourceUrl')==source['documentUrl'] and (source['validFrom']!=latest[source['product']] or not due): return previous,None
        try:
            data = read_xlsx(fetch(source['documentUrl'],timeout=40))
            data.update(month=source['month'],period=source['validFrom'],product=source['product'],sourceUrl=source['documentUrl'],checkedAt=iso())
            path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
            return {'key':key,'month':source['month'],'period':source['validFrom'],'product':source['product'],'sourceUrl':source['documentUrl'],'url':'data/tariff-comparison/'+key+'.json','count':len(data['rows']),'checkedAt':iso()},None
        except Exception as error: return previous,{'key':key,'error':str(error)[:180]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for dataset,error in pool.map(process,sources):
            if dataset: result.append(dataset)
            if error: errors.append(error)
    if due:
        from transport_tariffs import update_transport_references
        errors.extend({'key':'transport-references',**e} for e in update_transport_references(state,folder,fetch,iso))
        try:
            from tariff_pdf import update_resolution_comparison
            newer,pdf_errors=update_resolution_comparison(state,folder,fetch,iso,result,FIELDS)
            result.extend(newer);errors.extend(pdf_errors)
        except Exception as error:
            errors.append({'key':'resolution-annexes','error':str(error)[:180]})
            result.extend(r for r in old.values() if r['key'] not in {s['key'] for s in result})
    else:
        result.extend(r for r in old.values() if r['key'] not in {s['key'] for s in result})
    result.extend(r for r in old.values() if r['key'] not in {s['key'] for s in result})
    state.update(readerVersion=5,datasets=sorted(result,key=lambda r:r['key']),checkedAt=iso() if due or len(result)!=len(old) else state.get('checkedAt'),errors=errors,status='partial' if errors else 'updated',cadence='Cada 3 horas; el histórico se conserva')
