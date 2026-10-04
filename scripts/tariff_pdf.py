"""Fallback to official resolution annex tables when normalized XLSX lags.
Only monthly fixed, consumption and reservation charges are emitted. Missing
component breakdowns remain missing rather than inheriting a previous month.
"""
import io,re,unicodedata
from datetime import datetime

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().upper()
    s=re.sub(r'\s+',' ',s)
    for a,b in [('BUENOS AIRES SUR','BA SUR'),('CORDILLERANO','CORD'),('HIPOLITO YRIGOYEN','HIPOLITO IRIGOYEN'),('NAPALEOFU','NAPOLEUFU'),('CLAROMECO Y COPETONAS','CLAROMECO COPETONAS'),('BAHIA SAN BLAS','SAN BLAS')]:s=s.replace(a,b)
    return re.sub(r'[^A-Z0-9]','',s.replace('PROVINCIA','PROV').replace('PROV. DE','PROV').replace('PROV.','PROV').replace(' DE ',' ').replace(' Y ',' '))

def decode(data):
    return [dict(zip(data['columns'],[data['values'][i][v] for i,v in enumerate(row)])) for row in data['rows']]

def encode(records,fields):
    values=[[] for _ in fields];indexes=[{} for _ in fields];rows=[]
    for r in records:
        row=[]
        for i,f in enumerate(fields):
            v=r[f]
            if v not in indexes[i]:indexes[i][v]=len(values[i]);values[i].append(v)
            row.append(indexes[i][v])
        rows.append(row)
    return dict(schema=1,columns=fields,values=values,rows=rows)

def effective_date(text):
    months={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
    text=text[text.upper().rfind('RESUELVE'):]
    m=re.search(r'vigencia\s+a\s*partir\s*del?\s*(\d{1,2})(?:[°º])?\s*de\s*(\w+)\s*de\s*(20\d{2})',text,re.I)
    if not m or m[2].lower() not in months:raise ValueError('Vigencia no legible en la parte resolutiva')
    return datetime(int(m[3]),months[m[2].lower()],int(m[1])).date().isoformat()

def parse_annex(raw,templates):
    import pdfplumber
    from pypdf import PdfReader
    text=' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages[:7]);period=effective_date(text)
    output={};unmatched=set();titles={};ambiguous=set()
    def amount(s):
        s=str(s or '').strip()
        if not re.fullmatch(r'-?\d[\d.]*,\d{2}',s):raise ValueError('Importe ilegible: '+s)
        return float(s.replace('.','').replace(',','.'))
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            title=page.extract_text() or '';upper=title.upper()
            if 'SIN IMPUESTOS' not in upper:continue
            product='GLP' if 'PROPANO/BUTANO' in upper or 'GAS PROPANO' in upper else 'GN'
            pool=[r for r in templates if r['TIPODESUMINISTRO']==product]
            if not pool:continue
            if product=='GLP':
                company='Buenos Aires Gas S.A. (BAGSA)' if 'BAGSA' in upper else None
                if not company and 'DISTRIGAS' in upper:company='Distrigas S.A.'
                if not company and 'HIDENESA' in upper:company='Hidrocarburos del Neuquén S.A. (HIDENESA)'
                if company:pool=[r for r in pool if r['EMPRESA']==company]
                else:
                    # Other GLP annex operators are identified only by their exact company name.
                    companies=[c for c in set(r['EMPRESA'] for r in pool) if norm(c) in norm(title[:600])]
                    if len(companies)!=1:continue
                    pool=[r for r in pool if r['EMPRESA']==companies[0]]
            else:
                companies=[c for c in set(r['EMPRESA'] for r in pool) if norm(c) in norm(title[:200])]
                if len(companies)!=1:continue
                pool=[r for r in pool if r['EMPRESA']==companies[0]]
            tariff='Diferenciales 50%' if 'DIFERENCIALES' in upper and '(70%)' not in upper else 'Diferenciales 70%' if 'DIFERENCIALES' in upper else 'Plenas'
            if 'ZONA FRIA' in upper and 'DIFERENCIALES' not in upper:tariff='Plenas ZF'
            service='Unbundling' if 'TARIFAS DE DISTRIBUCI' in upper else None
            pool=[r for r in pool if r['TIPOTARIFA']==tariff and r['CUADRO']=='SinSEF' and (service is None or r['SERVICIO']==service)]
            if product=='GN' and service is None:
                service='Residencial' if 'A USUARIOS RESIDENCIALES' in upper else 'Clubes de Barrio' if 'CLUBES DE BARRIO' in upper and 'ENTIDADES' not in upper else 'Servicio General'
                pool=[r for r in pool if r['SERVICIO']==service]
            for table in page.extract_tables():
                if not table or len(table)<2:continue
                header=table[0];first=norm(header[0])
                if first not in ('TIPOCARGO','CATEGORIALOCALIDAD'):continue
                start=next((i for i in range(1,len(header)) if header[i] and 'CATEGOR' not in norm(header[i]) and amount_like(table[1][i])),None)
                if start is None:continue
                current_kind='';current_categories=''
                for row in table[1:]:
                    if len(row)!=len(header):continue
                    if first=='TIPOCARGO':
                        if row[0]:current_kind=row[0]
                        if row[1]:current_categories=row[1]
                        label=current_kind;catlabel=current_categories;range_text=' '.join(str(v or '') for v in row[2:start])
                    else:label=catlabel=row[0] or '';range_text=''
                    if 'Fijo' in label or '$/mes' in label:kind='Cargo Fijo ($)'
                    elif 'Reserva' in label:kind='Capacidad ($ por m3/d)'
                    elif 'consumo' in label.lower() or 'Consumo' in label or '$/m3' in label:kind='Cargo Variable ($/m3)'
                    else:continue
                    begin='0';end=''
                    nums=re.findall(r'\d+',range_text.replace('m3',''))
                    if ' a ' in range_text and len(nums)>=2:begin,end=nums[:2]
                    elif 's de' in range_text and nums:begin=str(int(nums[0])+1)
                    known=set(r['CATEGORIA'] for r in pool)
                    cats=[c for c in known if re.search(r'(?<![A-Z0-9])'+re.escape(c)+r'(?![A-Z0-9°])',catlabel)]
                    if catlabel.startswith('R2 -'):cats=[c for c in known if c=='R2']
                    if catlabel.startswith('SGP'):cats=[c for c in known if c=='SGP']
                    for j in range(start,len(header)):
                        if not header[j] or not amount_like(row[j]):continue
                        zones=[z for z in set(r['SUBZONA'] for r in pool) if norm(z)==norm(header[j])]
                        if len(zones)!=1:
                            # Strict alias list for labels expanded in the PDF.
                            aliases={'BASURPROVRIONEGROCHUBUT':'BAPROVCHUBUTRIONEGRO','CORDPROVRIONEGROCHUBUT':'CORDCHUBUTRIONEGRO','CORDPROVNEUQUEN':'CORDNEUQUEN','NEUQUENPROVNEUQUEN':'PROVNEUQUEN','NEUQUENPROVRIONEGROCHUBUT':'PROVCHUBUTRIONEGRO','BUENOSAIRES':'PROVBUENOSAIRES','IRENEOPORTELA':'IRINEOPORTELA','RUFINOSANTAFE':'RUFINO','BAHIASANBLASPARTIDOPATAGONES':'SANBLAS','SANBLASPARTIDOPATAGONES':'SANBLAS','CAMARONESCHUBUT':'CAMARONES','GANGANCHUBUT':'GANGAN','GASTRECHUBUT':'GASTRE','GOBERNADORGREGORESSANTACRUZ':'GOBERNADORGREGORES','GUALJAINACHUBUT':'GUALJAINA','PASOINDIOSCHUBUT':'PASOINDIOS','PERITOMORENOSANTACRUZ':'PERITOMORENO','PROVCHACO':'CHACO','PROVFORMOSA':'FORMOSA','PROVMISIONES':'MISIONES','PROVCORRIENTES':'LOCALIDADCORRIENTESCONGLP','SALTAPUNA':'LAPUNA','SANTAFE':'PROVSANTAFE','SMARIAVALOGUERCIOACARBONI':'SALVADORMARIALOGUERCIOCARBONI'}
                            mapped=aliases.get(norm(header[j]));zones=[z for z in set(r['SUBZONA'] for r in pool) if norm(z)==mapped] if mapped else []
                        if len(zones)!=1:unmatched.add(str(header[j]));continue
                        candidates=[r for r in pool if r['SUBZONA']==zones[0] and r['CATEGORIA'] in cats and r['CARGOTIPO']==kind and r['CONSUMOM3INICIO']==begin and r['CONSUMOM3FIN']==end]
                        for template in candidates:
                            record=dict(template,CARGO=amount(row[j]),VIGENCIADESDE=datetime.fromisoformat(period).strftime('%d/%m/%Y'))
                            key=tuple(record[k] for k in record if k not in ('CARGO','VIGENCIADESDE'))
                            if key in ambiguous:continue
                            if key in output and output[key]['CARGO']!=record['CARGO']:
                                ambiguous.add(key);del output[key];continue
                            output[key]=record;titles[key]=title
    if not output:raise ValueError('No se extrajeron cargos comparables del anexo')
    if ambiguous:unmatched.add(str(len(ambiguous))+' alcances ambiguos omitidos')
    return period,list(output.values()),sorted(unmatched)

def amount_like(s):return bool(re.fullmatch(r'-?\d[\d.]*,\d{2}',str(s or '').strip()))

def update_resolution_comparison(state,folder,fetch,iso,datasets,fields):
    """Refresh advertised official annexes; save only periods newer than XLSX."""
    import json,hashlib
    from bs4 import BeautifulSoup
    from concurrent.futures import ThreadPoolExecutor
    page='https://www.enargas.gob.ar/secciones/precios-y-tarifas/resoluciones-tarifas-vigentes.php'
    soup=BeautifulSoup(fetch(page,timeout=40),'html.parser');links=[]
    for tr in soup.find_all('tr'):
        a=tr.find('a',href=True)
        if a and 'ObtenerArchivo' in a['href'] and '2026' in a.get_text() and not any(w in tr.get_text().lower() for w in ['transportadora','gasoducto','gas link','energía argentina','enel','refinería del norte','compañía entrerriana']):links.append(a['href'])
    if not links:raise ValueError('No se identificaron anexos vigentes de distribuidoras')
    templates=[]
    for product in ['GN','GLP']:
        latest=max((r for r in datasets if r['product']==product),key=lambda r:r['period'],default=None)
        if latest:templates+=decode(json.loads((folder/(latest['key']+'.json')).read_text()))
    cache=state.setdefault('resolutionTables',{});errors=[]
    def read(url):
        key=re.search(r'Numero=(\d+)',url)[1];path=folder/('resolution-'+key+'.json');previous=cache.get(url)
        try:
            raw=fetch(url,timeout=40);digest=hashlib.sha256(raw).hexdigest()
            if previous and previous.get('sha256')==digest and previous.get('parserVersion')==2 and path.exists():data=json.loads(path.read_text())
            else:
                period,records,unmatched=parse_annex(raw,templates);data=encode(records,fields);data.update(period=period,sourceUrl=url,unmatchedZones=unmatched);path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
            return url,dict(period=data['period'],sha256=digest,file=path.name,parserVersion=2),data,None
        except Exception as e:
            data=json.loads(path.read_text()) if previous and path.exists() else None
            return url,previous,data,{'key':'resolution-'+key,'error':str(e)[:180]}
    grouped={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for url,meta,data,error in pool.map(read,links):
            if meta:cache[url]=meta
            if error:errors.append(error)
            if not data:continue
            for r in decode(data):
                product=r['TIPODESUMINISTRO'];latest=max((s['period'] for s in datasets if s['product']==product),default='')
                if data['period']<=latest:continue
                group=grouped.setdefault((data['period'],product),{'rows':[],'sources':set(),'unmatched':set()});group['rows'].append(r);group['sources'].add(url);group['unmatched'].update(data.get('unmatchedZones',[]))
    result=[]
    for (period,product),group in grouped.items():
        key=period+'-'+product;records=group['rows'];data=encode(records,fields);data.update(period=period,month=period[:7],product=product,checkedAt=iso(),sourceUrl=page,sourceKind='pdf',sources=sorted(group['sources']));(folder/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
        companies=sorted(set(r['EMPRESA'] for r in records));result.append(dict(key=key,period=period,month=period[:7],product=product,count=len(records),sourceUrl=page,sourceKind='pdf',sources=sorted(group['sources']),url='data/tariff-comparison/'+key+'.json',checkedAt=iso(),companies=companies,coverageNote='Anexos PDF oficiales: cargo fijo, cargo variable y reserva de capacidad. Los desgloses no extraídos quedan sin dato.',unmatchedZones=sorted(group['unmatched'])))
    return result,errors
