"""Reuse the regulator's 3-hour catalogue as a second discovery source.

Catalogue dates are issue dates, never inferred publication dates. No extra
requests or changes to the Boletin's retry queue are made here.
"""
import re
import unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text or '').lower())
                   if unicodedata.category(c) != 'Mn')


def authority(row):
    text = normalized(' '.join(str(row.get(k) or '') for k in ('issuer', 'num', 'title')))
    if 'enrege' in text or 'ente nacional regulador del gas y la electricidad' in text:
        return 'enrege'
    if 'enargas' in text or 'ente nacional regulador del gas' in text:
        return 'enargas'
    return None


def regulator_key(row):
    org = authority(row)
    match = re.search(r'resolucion\s+(?:(?:fs|fc|i)[\s-]+)?0*(\d+)\s*/\s*(20\d{2})', normalized(row.get('num')))
    return (org, int(match[1]), match[2]) if org and match else None


def technical_text(row):
    # The decision, not generic laws cited in the recitals, determines the topic.
    return normalized(row.get('firstArticle') or row.get('disposition') or row.get('desc') or row.get('title') or '')


def is_technical(row):
    text = technical_text(row)
    if re.search(r'\b(sancionar|sancionase|multa|contratacion|designar|designase)\b', text):
        return False
    return bool(re.search(r'\bnag\s*[-–—]?\s*\d{3}\b|normas? tecnic|adenda|'
                          r'presupuestos minimos|compendio de instrucciones|'
                          r'integridad|odoriz|medicion|calidad de gas|'
                          r'reglamento para|seguridad|operacion de', text))


def relevant_catalogue(row):
    text = technical_text(row)
    if is_technical(row):
        return True
    return bool(re.search(r'gas natural|gas licuado|gasoduct|subdistrib|\b(glp|gnl|gnc|tgs|tgn)\b|'
                          r'propano|butano|plan gas|\bpist\b|comercializadores? de gas|registro de comercializadores|'
                          r'transportadora de gas|camuzzi|naturgy|metrogas|litoral gas|'
                          r'gasnea|gasnor|redengas|distribuidora de gas', text))


def sync_regulator_catalogue(data, categories):
    catalogue = data.get('resolutionExport') or {}
    rows = data.setdefault('regulations', [])
    known = {regulator_key(r): r for r in rows if regulator_key(r)}
    added = 0
    for source in catalogue.get('rows', []):
        key = regulator_key(source)
        if not key or not relevant_catalogue(source):
            continue
        row = known.get(key)
        if row is None:
            cats = categories(source.get('desc', ''))
            row = dict(num=f'Resolución {key[1]}/{key[2]}',
                       issuer=source['issuer'], title=f'Resolución {key[1]}/{key[2]}',
                       desc=source.get('desc', ''), disposition=source.get('desc', ''),
                       category=cats[0] if cats else 'Mercado', tags=cats,
                       publishedAt=None, issuedAt=source['date'],
                       dateMeaning='Fecha de la resolución; publicación no confirmada',
                       url=source['url'], sourceType='OFFICIAL',
                       validatedAt=catalogue.get('checkedAt'), auto=True,
                       discoverySource='Catálogo oficial ENARGAS / ENReGE')
            rows.append(row)
            known[key] = row
            added += 1
        row['catalogueUrl'] = source['url']
        row['issuedAt'] = source['date']
        row['catalogueCheckedAt'] = catalogue.get('checkedAt')
    for row in rows:
        row['technical'] = is_technical(row)
        tags = [t for t in row.get('tags', []) if t != 'Técnica / operativa']
        if row['technical']:
            tags.append('Técnica / operativa')
        elif row.get('category') == 'Técnica / operativa':
            row['category'] = next(iter(tags), 'Mercado')
        row['tags'] = list(dict.fromkeys(tags))
    rows.sort(key=lambda r: r.get('publishedAt') or r.get('issuedAt') or '', reverse=True)
    data['regulatorCatalogueSync'] = dict(checkedAt=catalogue.get('checkedAt'),
        complete=bool(catalogue.get('complete')), added=added,
        technicalCount=sum(r['technical'] for r in rows),
        sourceUrl=catalogue.get('sourceUrl'), cadence='Cada 3 horas',
        dateMeaning='Se distingue emisión de publicación; las ediciones pendientes del Boletín se conservan')
    return added
