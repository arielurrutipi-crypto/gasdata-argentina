"""Public data adapters. Failed reads never replace a dated observation."""
import io
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin, urlparse
from bs4 import BeautifulSoup


def eia_latest(raw):
    import xlrd
    book = xlrd.open_workbook(file_contents=raw)
    observations = []
    for sheet in book.sheets():
        for row in sheet.get_rows():
            if len(row) >= 2 and row[0].ctype == xlrd.XL_CELL_DATE and row[1].ctype == xlrd.XL_CELL_NUMBER:
                date = xlrd.xldate_as_datetime(row[0].value, book.datemode)
                value = float(row[1].value)
                if 1990 <= date.year <= datetime.now().year and 0 < value < 1000:
                    observations.append((date, value))
    if not observations:
        raise ValueError('La planilla EIA no contiene observaciones fecha/precio válidas')
    return max(observations)


def worldbank_latest(raw):
    import openpyxl
    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    results = {}
    for sheet in book:
        if sheet.title != 'Monthly Prices':
            continue
        columns = {}
        for row in sheet.values:
            for index, cell in enumerate(row):
                name = str(cell or '').lower()
                if 'natural gas' in name and 'europe' in name:
                    columns['wb_europe'] = index
                if ('natural gas' in name or 'liquefied' in name) and 'japan' in name:
                    columns['wb_japan'] = index
            match = re.fullmatch(r'(\d{4})M(\d{2})', str(row[0] or ''))
            if not match:
                continue
            period = '-'.join(match.groups())
            for key, index in columns.items():
                value = row[index]
                if isinstance(value, (int, float)) and 0 < value < 200:
                    if period > results.get(key, ('', 0))[0]:
                        results[key] = (period, float(value))
    if len(results) != 2:
        raise ValueError('Faltan las series de gas Europa y Japón en Pink Sheet')
    return results


def catalyst_latest(fetch):
    month_map={m.lower():i for i,m in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'),1)}
    # Catalyst's /works/ index can return 404 to automated clients while the
    # individual public reports remain accessible. Probe recent canonical URLs.
    today=datetime.now()
    candidates=[]
    for offset in range(0,16):
        dt=today-timedelta(days=offset)
        slug=dt.strftime('%d-%B-%Y').lower()
        candidates.append((dt,'https://www.catalyst-commercial.co.uk/works/uk-energy-market-report-'+slug+'/'))
    errors=[]
    for report_date,url in candidates:
        try:
            text=re.sub(r'\s+',' ',BeautifulSoup(fetch(url,timeout=30),'html.parser').get_text(' ',strip=True))
        except Exception as exc:
            errors.append(report_date.date().isoformat()+': '+str(exc)[:60])
            continue
        jkm=re.search(r'JKM\s+LNG\s+M\+1\s*\$?([0-9]+(?:\.[0-9]+)?)\s*/?MMBtu',text,re.I)
        if not jkm:
            jkm=re.search(r'JKM.{0,100}?\$([0-9]+(?:\.[0-9]+)?)\s*/?MMBtu',text,re.I)
        ttf=re.search(r'TTF\s+(?:spot|day-ahead).{0,120}?\$([0-9]+(?:\.[0-9]+)?)',text,re.I)
        if not ttf:
            ttf=re.search(r'TTF.{0,120}?\$([0-9]+(?:\.[0-9]+)?)\s*/?MMBtu',text,re.I)
        if not jkm or not ttf:
            errors.append(report_date.date().isoformat()+': sin JKM/TTF parseables')
            continue
        settle=re.search(r'Settlement\s+(\d{1,2})\s+([A-Za-z]+)',text,re.I)
        obs=report_date-timedelta(days=1)
        if settle:
            mon=month_map.get(settle.group(2).lower())
            if mon:
                year=report_date.year
                obs=datetime(year,mon,int(settle.group(1)))
                if obs>report_date: obs=obs.replace(year=year-1)
        return obs.date().isoformat(),float(jkm.group(1)),float(ttf.group(1)),url
    raise ValueError('No hubo reporte Catalyst accesible y parseable: '+'; '.join(errors[:5]))

def pau_2026(fetch):
    from pypdf import PdfReader
    url='https://servicios.infoleg.gob.ar/infolegInternet/anexos/420000-424999/422817/res23-anexo1.pdf'
    reader=PdfReader(io.BytesIO(fetch(url,timeout=40)))
    text=' '.join((p.extract_text() or '') for p in reader.pages)
    vals=[float(x) for x in re.findall(r'\b(3\.\d{3}|4\.\d{3})\b',text)]
    if len(vals)<8:
        raise ValueError('No se pudieron leer los PAU del Anexo Res. 23/2026')
    return min(vals),max(vals),url

def propano_ppe_from_bagsa(d,fetch):
    import pdfplumber
    row=next((x for x in d.get('tariffs',[]) if x.get('bagsa') and x.get('product')=='GLP' and x.get('documentUrl')),None)
    if not row: raise ValueError('No hay cuadro GLP BAGSA vigente')
    url=row['documentUrl']
    with pdfplumber.open(io.BytesIO(fetch(url,timeout=40))) as pdf:
        text=' '.join((p.extract_text() or '') for p in pdf.pages[:3])
    # Standard non-subsidised table exposes the recognised purchase price in $/t.
    candidates=[]
    for raw in re.findall(r'\b\d{3}\.\d{3},\d{2}\b',text):
        val=float(raw.replace('.','').replace(',','.'))
        if 200000<val<1500000: candidates.append(val)
    if not candidates:
        raise ValueError('No se encontró precio de compra reconocido en el cuadro GLP')
    recognised=max(candidates)
    return recognised,recognised/0.60,url,row.get('res',''),row.get('validFrom','')

def update_market(d, fetch, iso):
    items = {x['id']: x for x in d.get('marketPrices', [])}
    outcomes = {}
    def save(key, period, value, **fields):
        item = items.get(key, {'id': key})
        if item.get('observationDate', '') > period:
            raise ValueError('Se rechazó una observación anterior a la guardada')
        item.update(value=f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.'),
                    observationDate=period, checkedAt=iso(), validatedAt=iso(), auto=True,
                    updateStatus='current', **fields)
        item.pop('updateError', None)
        items[key] = item
    sources = {
        'henry_hub': 'https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls',
        'mb_propane': 'https://www.eia.gov/dnav/pet/hist_xls/EER_EPLLPA_PF4_Y44MB_DPGd.xls',
    }
    for key, url in sources.items():
        try:
            date, value = eia_latest(fetch(url, timeout=40))
            fields = dict(reference=date.strftime('%d/%m/%Y') + ' · spot', source='U.S. EIA',
                          sourceUrl=url, statusText='SPOT · AUTOMÁTICO')
            if key == 'mb_propane':
                fields.update(unit='USD/t', details=f'Conversión desde {value:.3f} USD/gal; 3,785411784 L/gal y densidad indicativa 0,493 kg/L.')
                value = value * 1000 / (3.785411784 * .493)
            else:
                fields.update(unit='USD/MMBtu')
            save(key, date.strftime('%Y-%m-%d'), value, **fields)
            outcomes[key] = 'ok'
        except Exception as exc:
            outcomes[key] = str(exc)[:180]
            if key in items:
                items[key].update(checkedAt=iso(), updateStatus='error', updateError=outcomes[key])
    try:
        hub = 'https://www.worldbank.org/en/research/commodity-markets'
        soup = BeautifulSoup(fetch(hub), 'html.parser')
        link = next(a['href'] for a in soup.select('a[href]') if 'CMO-Historical-Data-Monthly.xlsx' in a['href'])
        url = urljoin(hub, link)
        if urlparse(url).hostname not in ('thedocs.worldbank.org', 'www.worldbank.org'):
            raise ValueError('La descarga no pertenece al Banco Mundial')
        for key, (period, value) in worldbank_latest(fetch(url, timeout=40)).items():
            japan = key == 'wb_japan'
            save(key, period, value, label='GNL Japón · promedio mensual' if japan else 'Gas Europa · promedio mensual',
                 group='GNL' if japan else 'GN internacional', unit='USD/MMBtu', reference=period + ' · promedio mensual',
                 source='Banco Mundial · Pink Sheet', sourceUrl=url, statusText='MENSUAL · AUTOMÁTICO',
                 note='Serie mensual de referencia del Banco Mundial.',
                 details='Alternativa pública al seguimiento regional. Tiene metodología y frecuencia propias; no equivale a la cotización diaria JKM o TTF.')
        outcomes['worldbank'] = 'ok'
    except Exception as exc:
        outcomes['worldbank'] = str(exc)[:180]
        for key in ('wb_japan', 'wb_europe'):
            if key in items:
                items[key].update(checkedAt=iso(), updateStatus='error', updateError=outcomes['worldbank'])
    try:
        period,jkm,ttf,url=catalyst_latest(fetch)
        save('jkm',period,jkm,label='JKM LNG · Asia',group='GNL',unit='USD/MMBtu',
             reference=period+' · M+1',source='Catalyst Commercial · market report',sourceUrl=url,
             statusText='BENCHMARK · AUTOMÁTICO',note='JKM LNG M+1 extraído del último reporte de mercado publicado.',
             details='Benchmark spot/M+1 del noreste asiático; no equivale a un netback argentino.')
        save('ttf',period,ttf,label='TTF · gas natural Europa',group='GN internacional',unit='USD/MMBtu',
             reference=period+' · spot',source='Catalyst Commercial · market report',sourceUrl=url,
             statusText='BENCHMARK · AUTOMÁTICO',note='TTF spot extraído del último reporte de mercado publicado.',
             details='Benchmark europeo de gas natural.')
        outcomes['catalyst']='ok'
    except Exception as exc:
        outcomes['catalyst']=str(exc)[:180]
        for key in ('jkm','ttf'):
            if key in items: items[key].update(checkedAt=iso(),updateStatus='error',updateError=outcomes['catalyst'])

    try:
        low,high,url=pau_2026(fetch)
        item=items.get('pau',{'id':'pau'})
        item.update(value=f'{low:.2f}–{high:.2f}'.replace('.',','),unit='USD/MMBtu',
                    reference='Año 2026 · rango nacional por subzona',checkedAt=iso(),validatedAt=iso(),
                    auto=True,updateStatus='current',statusText='OFICIAL · AUTOMÁTICO',
                    source='Secretaría de Energía · Res. 23/2026',sourceUrl=url,
                    note='Rango mínimo–máximo del Anexo oficial del Precio Anual Uniforme 2026 por subzona.')
        item.pop('updateError',None);items['pau']=item;outcomes['pau']='ok'
    except Exception as exc:
        outcomes['pau']=str(exc)[:180]
        if 'pau' in items: items['pau'].update(checkedAt=iso(),updateStatus='error',updateError=outcomes['pau'])

    try:
        recognised,ppe,url,res,valid=propano_ppe_from_bagsa(d,fetch)
        item=items.get('glp_ppe_propano_arg',{'id':'glp_ppe_propano_arg'})
        item.update(value=f'{ppe:,.0f}'.replace(',','.'),unit='ARS/t',
                    reference=(valid or 'Cuadro vigente')+' · derivado de tarifa BAGSA',
                    checkedAt=iso(),validatedAt=iso(),auto=True,updateStatus='current',
                    statusText='DERIVADO · AUTOMÁTICO',source='BAGSA / ENReGE + Res. 126/2026',sourceUrl=url,
                    note='PPE implícito = precio de compra reconocido en tarifa / 60%.',
                    details=f'Precio reconocido: $ {recognised:,.2f}/t · Res. {res}. La Res. 126/2026 dispone trasladar 60% del PPE.'.replace(',','_').replace('.',',').replace('_','.'))
        item.pop('updateError',None);items['glp_ppe_propano_arg']=item;outcomes['ppe_propano']='ok'
    except Exception as exc:
        outcomes['ppe_propano']=str(exc)[:180]
        if 'glp_ppe_propano_arg' in items: items['glp_ppe_propano_arg'].update(checkedAt=iso(),updateStatus='error',updateError=outcomes['ppe_propano'])

    supplemental={'megsa_pist','free_contracts','glp_ppe_arg','aramco_lpg','sonatrach_lpg'}
    for key,item in items.items():
        if key in supplemental:
            item['supplemental']=True
            if item.get('updateStatus')!='error': item['updateStatus']='reference'
        elif not item.get('auto') and item.get('updateStatus') != 'error':
            item['updateStatus'] = 'manual'
    d['marketPrices'] = list(items.values())
    d['marketAutomation'] = {'checkedAt': iso(), 'readers': outcomes}
    required=('henry_hub','mb_propane','worldbank','catalyst','pau','ppe_propano')
    ok=all(outcomes.get(k)=='ok' for k in required)
    for row in d.get('updates', []):
        if row['name'] == 'Precios de mercado':
            row.update(last=iso(), status='updated' if ok else 'partial',
                       mode='Automática' if ok else 'Automática parcial',
                       strategy='EIA + Banco Mundial + Catalyst + normativa/tarifas argentinas',
                       scope='Actualiza Henry Hub, Mont Belvieu, TTF, JKM, Gas Europa, GNL Japón, PAU 2026 y PPE implícito de propano. Las referencias puntuales históricas se conservan como complementarias y no se presentan como cotización vigente.',
                       note='Lectores automáticos: '+', '.join(k+': '+v for k,v in outcomes.items())+'.')
    print('MARKET READERS', outcomes)


def monthly_values(words):
    # Power BI prints labels in paint order, not chronological order.
    values = [w for w in words if re.fullmatch(r'\d{1,3},\d{1,2}', w['text'])]
    if not values:
        raise ValueError('Sin etiquetas numéricas en el PDF')
    right = max((w['x0'] + w['x1']) / 2 for w in values)
    latest = [w for w in values if abs((w['x0'] + w['x1']) / 2 - right) < 8]
    # Two panels are delimited by their year-axis labels.
    years = sorted({round(w['top']) for w in words if re.fullmatch(r'20\d{2}', w['text'])})
    if len(years) != 2:
        raise ValueError('Cambió la estructura de los dos gráficos mensuales')
    output = {}
    for low, high, total, component in ((0, years[0], 'imports', 'lng'), (years[0], years[1], 'exports', 'chile')):
        labels = sorted((w for w in latest if low < w['top'] < high), key=lambda w: w['top'])
        if len(labels) < 2 or len(labels) > 4:
            raise ValueError('No se pudo alinear total y componente del último mes')
        output[total] = float(labels[0]['text'].replace(',', '.'))
        output[component] = float(labels[1]['text'].replace(',', '.'))
    return output


MONTHS = {name: i for i, name in enumerate(('ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'), 1)}


def tariff_header(text):
    # Some BAGSA/Camuzzi PDFs embed digits with Greek Coptic-looking glyphs
    # (Ϭϭ/Ϭϵ/ϮϬϮϲ instead of 01/09/2026). Normalize them before parsing.
    digit_map=str.maketrans({
        'Ϭ':'0','ϭ':'1','Ϯ':'2','ϯ':'3','ϰ':'4',
        'ϱ':'5','ϲ':'6','ϳ':'7','ϴ':'8','ϵ':'9'
    })
    normalized=(text or '').translate(digit_map)
    date = re.search(r'VIGENCIA\s+DESDE\s+(\d{1,2})\s+DE\s+(\w+)\s+DE\s+(20\d{2})', normalized.upper())
    resolution = re.search(r'RESFC-(20\d{2})-(\d+)-', normalized)
    if not date or not resolution:
        raise ValueError('Faltan vigencia explícita o resolución en el cuadro')
    day, month, year = date.groups()
    return datetime(int(year), MONTHS[month], int(day)).date().isoformat(), str(int(resolution[2])) + '/' + resolution[1]


def update_bagsa(d, fetch, iso):
    import pdfplumber
    hub = 'https://www.bagsa.com.ar/index.php/tarifas/'
    display_names = ['Naturgy BAN', 'Camuzzi Gas Pampeana', 'Litoral Gas', 'Camuzzi Gas del Sur']
    errors, parsed, pending_headers, fallbacks = [], {}, [], []
    try:
        soup = BeautifulSoup(fetch(hub), 'html.parser')

        # BAGSA lists four current references under GN and the same four providers
        # under GLP. Use that page order as the product/provider authority instead
        # of trusting the PDF filename: currently the CGS GN link itself points to
        # a file named CGS-GLP.
        ref_links=[]
        for a in soup.select('a[href]'):
            label=re.sub(r'\s+',' ',a.get_text(' ',strip=True))
            m=re.fullmatch(r'Ref:\s*(\d+)\s*-\s*(20\d{2})',label,re.I)
            if m:
                ref_links.append((a,m.group(1)+'/'+m.group(2)))
        if len(ref_links)<8:
            raise ValueError('No se encontraron los 8 cuadros vigentes GN/GLP en la página BAGSA')
        ref_links=ref_links[-8:]

        expected=[]
        for i,(a,page_ref) in enumerate(ref_links):
            product='GN' if i<4 else 'GLP'
            name=display_names[i%4]
            expected.append((name,product,page_ref,urljoin(hub,a['href'])))

        for name,product,page_ref,url in expected:
            try:
                if urlparse(url).hostname not in ('www.bagsa.com.ar', 'bagsa.com.ar'):
                    raise ValueError('Documento fuera del dominio BAGSA')
                with pdfplumber.open(io.BytesIO(fetch(url, timeout=40))) as pdf:
                    text = pdf.pages[0].extract_text() or ''
                date, resolution = tariff_header(text)
                if resolution != page_ref:
                    raise ValueError(f'{name} {product}: referencia página {page_ref} distinta del PDF {resolution}')
                # When BAGSA's hyperlink points to a PDF whose filename identifies
                # the other product, keep the tariff hub as the user-facing source.
                expected_token='-'+product+'-'
                source_url=url if expected_token in url.upper() else hub
                candidate = dict(
                    name=name, product=product, res=resolution, validFrom=date,
                    validatedAt=iso(), checkedAt=iso(),
                    scope='Distribución · cuadro BAGSA', bagsa=True,
                    url=source_url, documentUrl=url, auto=True, status='current'
                )
                parsed[(name,product)] = candidate
            except Exception as exc:
                pending_headers.append((name,product,page_ref,url,str(exc)[:150]))

        # If one PDF has a broken embedded font/header, BAGSA's page reference is
        # still authoritative for the product. Reuse the vigencia only from another
        # successfully parsed document carrying that exact same resolution.
        for name,product,page_ref,url,reason in pending_headers:
            same_res=next((x for x in parsed.values() if x.get('res')==page_ref),None)
            if same_res:
                expected_token='-'+product+'-'
                source_url=url if expected_token in url.upper() else hub
                parsed[(name,product)] = dict(
                    name=name, product=product, res=page_ref,
                    validFrom=same_res['validFrom'], validatedAt=iso(), checkedAt=iso(),
                    scope='Distribución · cuadro BAGSA', bagsa=True,
                    url=source_url, documentUrl=url, auto=True, status='current',
                    headerValidation='Vigencia cruzada con otro cuadro de la misma resolución'
                )
                fallbacks.append(name+' '+product+' ('+page_ref+')')
            else:
                errors.append(f'{name} {product}: {reason}')

        # Rebuild only BAGSA rows from verified current products, while preserving
        # non-BAGSA rows (e.g. transport tariffs). If one product fails, retain the
        # previous row for that provider/product instead of deleting valid data.
        old_rows=d.get('tariffs',[])
        non_bagsa=[r for r in old_rows if not r.get('bagsa')]
        old_by_product={}
        for row in old_rows:
            if not row.get('bagsa'): continue
            products=[p.strip() for p in row.get('product','').split('/')]
            for product in products:
                old_by_product[(row.get('name'),product)]={**row,'product':product}
        bagsa_rows=[]
        for name in display_names:
            for product in ('GN','GLP'):
                candidate=parsed.get((name,product))
                if candidate:
                    bagsa_rows.append(candidate)
                elif (name,product) in old_by_product:
                    bagsa_rows.append(old_by_product[(name,product)])
                    errors.append(name+' '+product+': se conserva la referencia anterior')
        d['tariffs']=non_bagsa+bagsa_rows
    except Exception as exc:
        errors.append(str(exc)[:180])

    d['tariffAutomation'] = {
        'checkedAt': iso(), 'parsed': len(parsed), 'expected': 8,
        'errors': errors, 'fallbacks': fallbacks, 'readerVersion': 4
    }
    for row in d.get('updates', []):
        if row['name'] == 'Tarifas ENReGE/BAGSA':
            row.update(
                last=iso(), status='partial' if errors else 'updated',
                mode='Automática',
                note=(f'{len(parsed)}/8 cuadros BAGSA verificados automáticamente (GN/GLP, resolución y vigencia).' + ((' Validación cruzada: '+', '.join(fallbacks)+'.') if fallbacks else '') + ((' '+ '; '.join(errors)) if errors else '')).strip()
            )
    print('BAGSA READER', len(parsed), '/8', 'fallbacks', fallbacks, 'errors', errors)


def _pba_relevant(text):
    text=re.sub(r"\s+"," ",text or "").strip()
    low=text.lower()
    if re.search(r"\bBAGSA\b|Buenos Aires Gas",text,re.I):
        return True
    if not re.search(r"\bgas\s+natural\b",text,re.I):
        return False
    # Typical corporate-purpose notices mention gas/GNC as one activity
    # among many. Exclude them before evaluating infrastructure proximity.
    corporate=("objeto social","constitución de sociedad","comercialización de productos derivados",
               "accesorios del automotor","autopartes","fraccionamiento","envasado",
               "compra, venta","importación, exportación","importacion, exportacion",
               "propietaria, proyectista","empresaria, contratista","urbanización integral de tierras",
               "urbanizacion integral de tierras","construcción, demolición","construccion, demolicion",
               "refacción de edificios","refaccion de edificios","obra pública o privada","obra publica o privada",
               "iii) constructora","constructora:","2. redes eléctricas","2. redes electricas",
               "sistemas de electrificación","sistemas de electrificacion","estudio, proyecto, dirección",
               "estudio, proyecto, direccion","proyección, dirección y ejecución","proyeccion, direccion y ejecucion",
               "mantenimiento de espacios públicos","mantenimiento de espacios publicos",
               "adm.dir.","repr:","pte:","cap $")
    public_project=re.search(r"\bmunicipalidad\b|licitaci[oó]n\s+p[úu]blica|presupuesto\s+oficial|\bobra\s*:|\bexpediente\b|\bresoluci[oó]n\b|\bdecreto\b",text,re.I)
    if any(x in low for x in corporate) and not public_project:
        return False
    if re.search(r"gas\s+natural\s+comprimido|\bGNC\b",text,re.I) and not re.search(r"red(?:es)?\s+de\s+gas\s+natural|gasoduct|licitaci[oó]n|\bBAGSA\b|Buenos Aires Gas|tarifa|suministro",text,re.I):
        return False
    sector=r"(?:red(?:es)?|ramal(?:es)?|gasoducto(?:s)?|obra(?:s)?|licitaci[oó]n|concesi[oó]n|servicio|suministro|tarifa(?:s)?|regulaci[oó]n|estaci[oó]n|planta|infraestructura|cañer[ií]a|extensi[oó]n|ampliaci[oó]n|distribuci[oó]n|subdistribuci[oó]n|municipalidad)"
    gas=r"gas\s+natural"
    if re.search(sector+r".{0,180}"+gas,text,re.I) or re.search(gas+r".{0,180}"+sector,text,re.I):
        return True
    return False

def _pba_title(text):
    text=re.sub(r"\s+"," ",text or "").strip()
    art=re.search(r"ART[ÍI]CULO\s+1[°ºo]?\.?\s*(.*?)(?=ART[ÍI]CULO\s+2|$)",text,re.I)
    if art:
        return re.sub(r"\s+"," ",art.group(1)).strip(" -–—")[:300]
    patterns=(
      r"(Licitaci[oó]n P[úu]blica\s+N[º°]?\s*.*?)(?=Presupuesto|Solicitud|Consulta|Apertura|Valor del pliego|Expediente|$)",
      r"((?:Obra|Proyecto)\s*:\s*.*?)(?=Presupuesto|Solicitud|Consulta|Apertura|Expediente|$)",
      r"((?:Extensi[oó]n|Ampliaci[oó]n|Construcci[oó]n|Renovaci[oó]n)\s+de\s+(?:la\s+)?(?:Red|Gasoducto|Ramal).*?)(?=Presupuesto|Solicitud|Consulta|Apertura|Expediente|$)"
    )
    for pattern in patterns:
        m=re.search(pattern,text,re.I)
        if m:
            return re.sub(r"\s+"," ",m.group(1)).strip(" -–—")[:300]
    if re.search(r"\bBAGSA\b|Buenos Aires Gas",text,re.I) and re.search(r"licitaci[oó]n|pliego",text,re.I):
        return "BAGSA — Licitación pública / pliego de bases y condiciones"
    if re.search(r"\bBAGSA\b|Buenos Aires Gas",text,re.I) and re.search(r"aporte irrevocable|aumento de capital",text,re.I):
        return "BAGSA — aporte irrevocable a cuenta de futuros aumentos de capital"
    m=re.search(r"(.{0,90}\bgas\s+natural\b.{0,150})",text,re.I)
    return (m.group(1).strip(" -–—") if m else text[:240]).strip()

def _pba_category(text):
    low=(text or "").lower()
    if "tarifa" in low: return "Tarifas"
    if "bagsa" in low and any(x in low for x in ("aporte irrevocable","aumento de capital")):
        return "Subdistribución"
    if any(x in low for x in ("licitación","licitacion","obra:","red de gas","gasoduct","ramal","extensión","extension","ampliación","ampliacion")):
        return "Infraestructura"
    if "bagsa" in low or "subdistrib" in low: return "Subdistribución"
    if "infraestructura" in low: return "Infraestructura"
    return "Normativa"


def update_bopba(d, fetch, iso, today):
    state = d.setdefault('bopbaScan', {})
    base = 'https://boletinoficial.gba.gob.ar/buscar'
    all_items = [r for r in d.get('regulations', []) if r.get('url')]
    removed = 0
    items = {}
    for r in all_items:
        if r.get('jurisdiction') == 'PBA':
            # Old records used a generic title containing "BAGSA"; evaluate
            # relevance from the actual excerpt only to avoid false positives.
            probe=str(r.get('desc',''))
            if not _pba_relevant(probe):
                removed += 1
                continue
            title=_pba_title(probe)
            category=_pba_category(probe)
            tags=['PBA',category]
            if re.search(r'\bBAGSA\b|Buenos Aires Gas',probe,re.I): tags.append('BAGSA')
            if re.search(r'\bsubdistrib',probe,re.I): tags.append('Subdistribución')
            r={**r,'title':title,'disposition':title,'category':category,'tags':list(dict.fromkeys(tags))}
        items[r['url']] = r
    errors = []
    count = 0
    for term in ('gas natural', 'BAGSA'):
        scan = state.setdefault(term, {})
        last = scan.get('lastScannedDate')
        start = max(datetime(today.year, 1, 1).date(), datetime.fromisoformat(last).date() - timedelta(days=2)) if last else datetime(today.year, 1, 1).date()
        url = scan.get('pendingUrl') or base + '?' + urlencode({'search[date_gteq]': start.strftime('%d/%m/%Y'), 'search[date_lteq]': today.strftime('%d/%m/%Y'), 'search[words]': term, 'search[sort]': 'by_date_desc', 'search[section]': 'OFICIAL', 'commit': 'Buscar'})
        end = scan.get('pendingThrough') or today.isoformat()
        try:
            visited = set()
            for _ in range(30):
                if url in visited or urlparse(url).hostname != 'boletinoficial.gba.gob.ar':
                    raise ValueError('Paginación inválida')
                visited.add(url)
                scan.update(pendingUrl=url, pendingThrough=end)
                soup = BeautifulSoup(fetch(url), 'html.parser')
                if not soup.select_one('.search-result'):
                    raise ValueError('No se reconoce la página de resultados')
                for box in soup.select('.result-box'):
                    date_node = box.select_one('.date strong')
                    if not date_node:
                        continue
                    date = datetime.strptime(date_node.get_text(strip=True), '%d/%m/%Y').date()
                    for anchor in box.select('a.page[href]'):
                        paragraph = anchor.find_next_sibling('p', class_='excerpt')
                        text = paragraph.get_text(' ', strip=True) if paragraph else ''
                        # The official search stems BAGSA to BAGS and can also
                        # return corporate notices where gas/GNC is incidental.
                        if not _pba_relevant(text):
                            continue
                        link = urljoin(base, anchor['href'])
                        if link not in items:
                            count += 1
                        title=_pba_title(text)
                        category=_pba_category(text)
                        tags=['PBA', category]
                        if re.search(r'\bBAGSA\b|Buenos Aires Gas', text, re.I): tags.append('BAGSA')
                        if re.search(r'\bsubdistrib', text, re.I): tags.append('Subdistribución')
                        items[link] = {**items.get(link, {}), 'num': 'PBA · ' + date.isoformat() + ' · ' + anchor.get_text(' ', strip=True),
                                       'title': title, 'desc': text[:650], 'disposition': title,
                                       'issuer': 'Boletín Oficial PBA', 'jurisdiction': 'PBA', 'category': category,
                                       'tags': list(dict.fromkeys(tags)),
                                       'date': date.strftime('%d/%m/%Y'), 'publishedAt': date.isoformat() + 'T00:00:00-03:00',
                                       'validatedAt': iso(), 'url': link, 'auto': True}
                nxt = next((a for a in soup.select('a[href]') if 'Siguiente' in a.get_text()), None)
                if not nxt:
                    scan.update(lastScannedDate=end, complete=True, checkedAt=iso())
                    scan.pop('pendingUrl', None)
                    scan.pop('pendingThrough', None)
                    break
                url = urljoin(base, nxt['href'])
                scan['pendingUrl'] = url
            else:
                errors.append(term + ': continúa la paginación en la próxima ejecución')
        except Exception as exc:
            errors.append(term + ': ' + str(exc)[:140])
    d['regulations'] = sorted(items.values(), key=lambda r: r.get('publishedAt', ''), reverse=True)
    state['cleanupVersion'] = 5
    for row in d.get('updates', []):
        if row['name'] == 'Boletín Oficial PBA':
            row.update(last=iso(), next=iso(today + timedelta(hours=3)), status='partial' if errors else 'updated' if (count or removed) else 'unchanged',
                       note=f'{count} publicaciones provinciales incorporadas · {removed} coincidencias irrelevantes depuradas. ' + ('; '.join(errors) if errors else 'Se conservan sólo BAGSA, regulación, tarifas, obras, redes y otra infraestructura de gas.'))
    print('BOPBA READER', count, 'added', removed, 'removed', errors)
