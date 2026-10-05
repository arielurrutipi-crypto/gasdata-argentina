"""Fallback to official resolution annex tables when normalized XLSX lags.
Monthly charges and explicitly published component tables are emitted. Missing
components remain missing rather than inheriting a previous month.
"""
import io,re,unicodedata
from datetime import datetime

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().upper()
    s=re.sub(r'\s+',' ',s)
    for a,b in [('BUENOS AIRES SUR','BA SUR'),('CORDILLERANO','CORD'),('HIPOLITO YRIGOYEN','HIPOLITO IRIGOYEN'),('NAPALEOFU','NAPOLEUFU'),('CLAROMECO Y COPETONAS','CLAROMECO COPETONAS'),('BAHIA SAN BLAS','SAN BLAS')]:s=s.replace(a,b)
    return re.sub(r'[^A-Z0-9]','',s.replace('PROVINCIA','PROV').replace('PROV. DE','PROV').replace('PROV.','PROV').replace(' DE ',' ').replace(' Y ',' '))

def decode(data):
    records=[dict(zip(data['columns'],[data['values'][i][v] for i,v in enumerate(row)])) for row in data['rows']]
    for record,proof in zip(records,data.get('provenance',[])):
        if proof:record['_pdfSource']=dict(url=data['sourceDocuments'][proof[0]],page=proof[1],table=proof[2],row=proof[3],column=proof[4],line=proof[5] if len(proof)>5 else None)
    return records

def encode(records,fields):
    values=[[] for _ in fields];indexes=[{} for _ in fields];rows=[]
    for r in records:
        row=[]
        for i,f in enumerate(fields):
            v=r[f]
            if v not in indexes[i]:indexes[i][v]=len(values[i]);values[i].append(v)
            row.append(indexes[i][v])
        rows.append(row)
    result=dict(schema=1,columns=fields,values=values,rows=rows)
    if any(r.get('_pdfSource') for r in records):
        documents=sorted({r['_pdfSource']['url'] for r in records if r.get('_pdfSource')})
        result.update(sourceDocuments=documents,provenance=[[documents.index(p['url']),p['page'],p['table'],p['row'],p['column'],p.get('line')] if (p:=r.get('_pdfSource')) else None for r in records])
    return result

def effective_date(text):
    months={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
    text=text[text.upper().rfind('RESUELVE'):]
    m=re.search(r'vigencia\s+a\s*partir\s*del?\s*(\d{1,2})(?:[°º])?\s*de\s*(\w+)\s*de\s*(20\d{2})',text,re.I)
    if not m or m[2].lower() not in months:raise ValueError('Vigencia no legible en la parte resolutiva')
    return datetime(int(m[3]),months[m[2].lower()],int(m[1])).date().isoformat()

def component_kind(label):
    label=norm(label)
    if 'TONELADA' in label:return None
    if label.startswith(norm('Precio en el Punto de Ingreso')) or label.startswith(norm('Precio de compra')):return 'PIST o Precio de compra ($/m3)'
    if label.startswith('DIFERENCIASDIARIASACUMULADAS'):return 'Diferencia Diaria Acumulada ($/m3)'
    if label.startswith('COSTOGASRETENIDO') or label.startswith('COSTODEGASRETENIDO'):return 'Gas Retenido ($/m3)'
    if label.startswith('INCIDENCIADELPRECIODELGAS'):return 'incidencia del Precio del Gas sobre los cargos por m3 consumido (%)'
    if label.startswith('COSTOTRANSPORTE') or label.startswith('COSTODETRANSPORTE'):return 'Costo Transporte ($/m3)'
    return None

def annex_categories(label,known,components=False):
    if components and norm(label)=='RESIDENCIALES':return sorted(known)
    cats=[c for c in known if re.search(r'(?<![A-Z0-9])'+re.escape(c)+r'(?![A-Z0-9°])',label)]
    if label.startswith('R2 -'):cats=[c for c in known if c=='R2']
    if label.startswith('SGP'):cats=[c for c in known if c=='SGP']
    return cats

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
        for page_number,page in enumerate(pdf.pages,1):
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
            for table_number,table in enumerate(page.extract_tables(),1):
                if not table or len(table)<2:continue
                header=table[0];first=norm(header[0])
                components=first.startswith('COMPONENTESDELCARGO');glp_percentages=first=='CATEGORIALOCALIDAD' and str(table[1][1] or '').strip().endswith('%');percentages=first in ('CONCEPTO','') and len(header)>1 and 'CATEGORIA' in norm(header[1])
                if product=='GLP' and first=='LOCALIDADCONCEPTO':
                    # These components are published with localities down rows, not across columns.
                    target_pool=[r for r in pool if (r['CATEGORIA'].startswith('BP') if 'ENTIDADES DE BIEN' in upper else not r['CATEGORIA'].startswith(('BP','CB')))]
                    for row_number,row in enumerate(table[1:],2):
                        names=str(row[0] or '').splitlines()
                        for j,label in enumerate(header[1:],1):
                            kind=component_kind(label)
                            if not kind:continue
                            cells=str(row[j] or '').splitlines()
                            if len(cells)!=len(names) or not all(amount_like(v) for v in cells):
                                unmatched.add('Componentes GLP con filas desalineadas');continue
                            for line,(name,cell) in enumerate(zip(names,cells)):
                                zones=[z for z in set(r['SUBZONA'] for r in target_pool) if norm(z)==norm(name)]
                                if len(zones)!=1:unmatched.add(name);continue
                                for template in target_pool:
                                    if template['SUBZONA']!=zones[0] or template['CARGOTIPO']!=kind:continue
                                    record={k:v for k,v in template.items() if k!='_pdfSource'}
                                    record.update(CARGO=amount(cell),VIGENCIADESDE=datetime.fromisoformat(period).strftime('%d/%m/%Y'))
                                    key=tuple(record[k] for k in record if k not in ('CARGO','VIGENCIADESDE'))
                                    if key in ambiguous:continue
                                    if key in output and output[key]['CARGO']!=record['CARGO']:
                                        ambiguous.add(key);del output[key];continue
                                    record['_pdfSource']=dict(url='',page=page_number,table=table_number,row=row_number,column=j,line=line)
                                    output[key]=record
                    continue
                if first not in ('TIPOCARGO','CATEGORIALOCALIDAD') and not components and not percentages:continue
                start=next((i for i in range(1,len(header)) if header[i] and 'CATEGOR' not in norm(header[i]) and amount_like(str(table[1][i] or '').rstrip('%'))),None)
                if start is None:continue
                current_kind='';current_categories=''
                for row_number,row in enumerate(table[1:],2):
                    if len(row)!=len(header):continue
                    if first=='TIPOCARGO' or components or percentages:
                        if row[0]:current_kind=row[0]
                        if row[1]:current_categories=row[1]
                        label=current_kind;catlabel=current_categories;range_text=' '.join(str(v or '') for v in row[2:start])
                    else:label=catlabel=row[0] or '';range_text=''
                    if glp_percentages:kind='incidencia del Precio del Gas sobre los cargos por m3 consumido (%)'
                    elif components or percentages:
                        kind=component_kind(label)
                        if not kind:continue
                    elif 'Fijo' in label or '$/mes' in label:kind='Cargo Fijo ($)'
                    elif 'Reserva' in label:kind='Capacidad ($ por m3/d)'
                    elif 'consumo' in label.lower() or 'Consumo' in label or '$/m3' in label:kind='Cargo Variable ($/m3)'
                    else:continue
                    begin='0';end=''
                    nums=re.findall(r'\d+',range_text.replace('m3',''))
                    if ' a ' in range_text and len(nums)>=2:begin,end=nums[:2]
                    elif 's de' in range_text and nums:begin=str(int(nums[0])+1)
                    known=set(r['CATEGORIA'] for r in pool)
                    cats=annex_categories(catlabel,known,components or percentages)
                    for j in range(start,len(header)):
                        cell=str(row[j] or '').strip();is_percent=cell.endswith('%')
                        if not header[j] or not amount_like(cell.rstrip('%')) or ((percentages or glp_percentages) and not is_percent):continue
                        zones=[z for z in set(r['SUBZONA'] for r in pool) if norm(z)==norm(header[j])]
                        if len(zones)!=1:
                            # Strict alias list for labels expanded in the PDF.
                            aliases={'BASURPROVRIONEGROCHUBUT':'BAPROVCHUBUTRIONEGRO','CORDPROVRIONEGROCHUBUT':'CORDCHUBUTRIONEGRO','CORDPROVNEUQUEN':'CORDNEUQUEN','NEUQUENPROVNEUQUEN':'PROVNEUQUEN','NEUQUENPROVRIONEGROCHUBUT':'PROVCHUBUTRIONEGRO','BUENOSAIRES':'PROVBUENOSAIRES','IRENEOPORTELA':'IRINEOPORTELA','RUFINOSANTAFE':'RUFINO','BAHIASANBLASPARTIDOPATAGONES':'SANBLAS','SANBLASPARTIDOPATAGONES':'SANBLAS','CAMARONESCHUBUT':'CAMARONES','GANGANCHUBUT':'GANGAN','GASTRECHUBUT':'GASTRE','GOBERNADORGREGORESSANTACRUZ':'GOBERNADORGREGORES','GUALJAINACHUBUT':'GUALJAINA','PASOINDIOSCHUBUT':'PASOINDIOS','PERITOMORENOSANTACRUZ':'PERITOMORENO','PROVCHACO':'CHACO','PROVFORMOSA':'FORMOSA','PROVMISIONES':'MISIONES','PROVCORRIENTES':'LOCALIDADCORRIENTESCONGLP','SALTAPUNA':'LAPUNA','SANTAFE':'PROVSANTAFE','SMARIAVALOGUERCIOACARBONI':'SALVADORMARIALOGUERCIOCARBONI'}
                            mapped=aliases.get(norm(header[j]));zones=[z for z in set(r['SUBZONA'] for r in pool) if norm(z)==mapped] if mapped else []
                        if len(zones)!=1:unmatched.add(str(header[j]));continue
                        candidates=[r for r in pool if r['SUBZONA']==zones[0] and r['CATEGORIA'] in cats and r['CARGOTIPO']==kind and r['CONSUMOM3INICIO']==begin and r['CONSUMOM3FIN']==end]
                        if not candidates and kind in ('Cargo Fijo ($)','Cargo Variable ($/m3)','Capacidad ($ por m3/d)'):
                            # The PDF defines this month's brackets; last month's templates identify only the user scope.
                            scopes={}
                            for r in pool:
                                if r['SUBZONA']==zones[0] and r['CATEGORIA'] in cats and r['CARGOTIPO']==kind:
                                    scope=tuple(r[k] for k in ('EMPRESA','SUBZONA','SERVICIO','CATEGORIA','TIPOTARIFA','CUADRO'))
                                    scopes.setdefault(scope,r)
                            candidates=list(scopes.values())
                        for template in candidates:
                            record={k:v for k,v in template.items() if k!='_pdfSource'}
                            record.update(CARGO=amount(cell.rstrip('%'))/(100 if is_percent else 1),VIGENCIADESDE=datetime.fromisoformat(period).strftime('%d/%m/%Y'),CONSUMOM3INICIO=begin,CONSUMOM3FIN=end)
                            if is_percent and kind=='Gas Retenido ($/m3)' and 'SDB' in catlabel:record['CARGOTIPO']='Gas Retenido sobre precio a usuarios (%)'
                            elif is_percent and kind!='incidencia del Precio del Gas sobre los cargos por m3 consumido (%)':continue
                            key=tuple(record[k] for k in record if k not in ('CARGO','VIGENCIADESDE'))
                            if key in ambiguous:continue
                            if key in output and output[key]['CARGO']!=record['CARGO']:
                                ambiguous.add(key);del output[key];continue
                            record['_pdfSource']=dict(url='',page=page_number,table=table_number,row=row_number,column=j)
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
            if previous and previous.get('sha256')==digest and previous.get('parserVersion')==4 and path.exists():data=json.loads(path.read_text())
            else:
                period,records,unmatched=parse_annex(raw,templates)
                for record in records:record['_pdfSource']['url']=url
                data=encode(records,fields);data.update(period=period,sourceUrl=url,unmatchedZones=unmatched);path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
            return url,dict(period=data['period'],sha256=digest,file=path.name,parserVersion=4),data,None
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
        companies=sorted(set(r['EMPRESA'] for r in records));result.append(dict(key=key,period=period,month=period[:7],product=product,count=len(records),sourceUrl=page,sourceKind='pdf',sources=sorted(group['sources']),url='data/tariff-comparison/'+key+'.json',checkedAt=iso(),companies=companies,coverageStatus='partial',coverageNote='Lectura parcial de anexos PDF oficiales, con enlace a la página de origen por concepto. Sin dato significa no extraído, no que el organismo no lo publicó. No se copian valores anteriores ni se completan faltantes con cero.',unmatchedZones=sorted(group['unmatched'])))
    return result,errors
