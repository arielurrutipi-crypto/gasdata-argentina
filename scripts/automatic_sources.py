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
    for key, item in items.items():
        if not item.get('auto') and item.get('updateStatus') != 'error':
            item['updateStatus'] = 'manual'
    d['marketPrices'] = list(items.values())
    d['marketAutomation'] = {'checkedAt': iso(), 'readers': outcomes}
    for row in d.get('updates', []):
        if row['name'] == 'Precios de mercado':
            row.update(last=iso(), status='partial', note='Lectores automáticos: ' + ', '.join(k + ': ' + v for k, v in outcomes.items()) + '. Las demás referencias conservan su fecha y requieren revisión manual.')
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
        if not labels or len(labels) > 4:
            raise ValueError('No se pudo alinear el último mes')
        output[total] = float(labels[0]['text'].replace(',', '.'))
        # Component labels require color/legend alignment; never guess their identity.
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
    names = {'NATURGY': 'Naturgy BAN', 'CGP': 'Camuzzi Gas Pampeana', 'CGS': 'Camuzzi Gas del Sur', 'LITORAL': 'Litoral Gas'}
    errors, parsed = [], {}
    try:
        soup = BeautifulSoup(fetch(hub), 'html.parser')
        urls = sorted({urljoin(hub, a['href']) for a in soup.select('a[href]') if re.search(r'/(NATURGY|CGP|CGS|LITORAL)-(GN|GLP)-.*\.pdf$', a['href'], re.I)})
        if not urls:
            raise ValueError('No se encontraron cuadros BAGSA')
        for url in urls:
            try:
                if urlparse(url).hostname not in ('www.bagsa.com.ar', 'bagsa.com.ar'):
                    raise ValueError('Documento fuera del dominio BAGSA')
                match = re.search(r'/(NATURGY|CGP|CGS|LITORAL)-(GN|GLP)-', url, re.I)
                name, product = names[match[1].upper()], match[2].upper()
                with pdfplumber.open(io.BytesIO(fetch(url, timeout=40))) as pdf:
                    text = pdf.pages[0].extract_text() or ''
                date, resolution = tariff_header(text)
                candidate = dict(name=name, product=product, res=resolution, validFrom=date, validatedAt=iso(), checkedAt=iso(),
                                 scope='Distribución · cuadro BAGSA', bagsa=True, url=url, auto=True, status='current')
                key = (name, product)
                if date >= parsed.get(key, {}).get('validFrom', ''):
                    parsed[key] = candidate
            except Exception as exc:
                errors.append(str(exc)[:180])
        # Replace a combined GN/GLP row only when all of its products were verified.
        output = []
        for row in d.get('tariffs', []):
            products = [p.strip() for p in row.get('product', '').split('/')]
            candidates = [parsed.get((row['name'], p)) for p in products]
            if all(candidates) and all(c['validFrom'] >= row.get('validFrom', '') for c in candidates):
                output.extend(candidates)
            else:
                output.append(row)
                if row.get('bagsa'):
                    errors.append(row['name'] + ': se conserva la referencia anterior; falta verificar un producto')
        d['tariffs'] = output
    except Exception as exc:
        errors.append(str(exc)[:180])
    d['tariffAutomation'] = {'checkedAt': iso(), 'parsed': len(parsed), 'errors': errors, 'readerVersion': 2}
    for row in d.get('updates', []):
        if row['name'] == 'Tarifas ENReGE/BAGSA':
            row.update(last=iso(), status='partial' if errors else 'updated',
                       mode='Automática',
                       note=(f'{len(parsed)} cuadros BAGSA leídos automáticamente con resolución y vigencia explícitas. ' + '; '.join(errors)).strip())
    print('BAGSA READER', len(parsed), errors)


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
