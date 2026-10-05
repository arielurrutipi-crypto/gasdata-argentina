"""Official TGN/TGS route references; preserve validated data on reader failure."""
import io,re,hashlib
from tariff_pdf import effective_date,norm
PAGE='https://www.enargas.gob.ar/secciones/precios-y-tarifas/resoluciones-tarifas-vigentes.php'
def number(value):
    value=str(value or '').strip()
    if not re.fullmatch(r'\d[\d.]*,\d{2}',value):raise ValueError('Importe de transporte ilegible')
    return float(value.replace('.','').replace(',','.'))
def route_rows(tables,company,service,period,url,resolution):
    result=[]
    for table in tables:
        active=False
        for row in table:
            if len(row)!=4:continue
            if norm(row[0])=='RECEPCION' and norm(row[1])=='DESPACHO':active=True;continue
            if not active or not row[0] or not row[1] or not row[2] or not row[3]:continue
            origin=' '.join(row[0].split());destinations=row[1].splitlines();rates=row[2].splitlines();retained=row[3].splitlines()
            if len(destinations)!=len(rates) or len(rates)!=len(retained):raise ValueError('Rutas y precios sin correspondencia')
            for destination,rate,retention in zip(destinations,rates,retained):
                amount=number(rate);percent=number(retention)
                if percent>=100:raise ValueError('Retención inválida')
                result.append(dict(id=company+'-'+service+'-'+norm(origin)+'-'+norm(destination),company=company,service=service,origin=origin,destination=destination,rate=amount,unit='ARS por m³/día y mes' if service=='TF' else 'ARS/1.000 m³',retainedPercent=percent,period=period,sourceUrl=url,resolution=resolution))
    return result

def parse_transport(raw,company,url):
    import pdfplumber
    from pypdf import PdfReader
    period=effective_date(' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages[:4]));resolution=re.search(r'Numero=(\d+)',url)[1]+'/'+period[:4];rows=[]
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            title=page.extract_text() or ''
            if 'TARIFAS TRANSPORTE - SIN IMPUESTOS' not in title:continue
            service='TF' if 'TRANSPORTE FIRME (TF)' in title else 'TI' if 'TRANSPORTE INTERRUMPIBLE (TI)' in title else None
            if service:rows.extend(route_rows(page.extract_tables(),company,service,period,url,resolution))
    if not rows or {r['service'] for r in rows}!={'TF','TI'}:raise ValueError('No se reconocieron cuadros TF y TI completos')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Rutas duplicadas')
    return rows

def update_transport_references(state,folder,fetch,iso):
    import json
    from bs4 import BeautifulSoup
    previous=state.get('transportReferences',{});rows=[];errors=[];seen=set()
    try:
        soup=BeautifulSoup(fetch(PAGE,timeout=40),'html.parser')
        for tr in soup.find_all('tr'):
            label=tr.get_text(' ',strip=True).lower();a=tr.find('a',href=True)
            company='TGN' if 'transportadora de gas del norte' in label else 'TGS' if 'transportadora de gas del sur' in label else None
            if not company or not a or 'ObtenerArchivo' not in a['href']:continue
            seen.add(company);url=a['href'];path=folder/('transport-'+company.lower()+'.json')
            try:
                raw=fetch(url,timeout=40);digest=hashlib.sha256(raw).hexdigest();cached=json.loads(path.read_text()) if path.exists() else {}
                current=cached.get('rows',[]) if cached.get('sha256')==digest and cached.get('parserVersion')==1 else parse_transport(raw,company,url)
                path.write_text(json.dumps(dict(parserVersion=1,sha256=digest,rows=current),ensure_ascii=False,separators=(',',':'))+'\n');rows.extend(current)
            except Exception as e:
                rows.extend(r for r in previous.get('rows',[]) if r['company']==company);errors.append(dict(company=company,error=str(e)[:180]))
        for company in {'TGN','TGS'}-seen:
            rows.extend(r for r in previous.get('rows',[]) if r['company']==company);errors.append(dict(company=company,error='Fuente vigente no identificada'))
    except Exception as e:
        rows=previous.get('rows',[]);errors.append(dict(error=str(e)[:180]))
    state['transportReferences']=dict(rows=rows,checkedAt=iso(),status='partial' if errors else 'updated',errors=errors,cadence='Cada 3 horas',sourceUrl=PAGE)
    return errors
