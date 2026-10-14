"""Hybrid infrastructure registry: automatic discovery never overwrites verified facts.

Uses the existing hourly news collection, daily official discovery, bounded document
rechecks, persistent per-source cursors and explicit repository review decisions.
No physical progress is inferred from a stage, a deadline, or a component metric.
"""
from __future__ import annotations
import copy
import hashlib
import io
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parents[1]
REGISTRY = BASE / 'data/infrastructure.json'
DECISIONS = BASE / 'data/infrastructure-decisions.json'
STAGES = ['Anunciado', 'Ingeniería', 'Licitación', 'Adjudicado', 'Construcción', 'Puesta en marcha', 'Operativo']
OFFICIAL_HUBS = [
    ('ENARSA','https://www.energia-argentina.com.ar/novedades/'),
    ('TGS','https://www.tgs.com.ar/prensa/'),
    ('TGN','https://www.tgn.com.ar/prensa-y-novedades/novedades/'),
    ('Oldelval','https://www.oldelval.com/novedades/'),
    ('Southern Energy','https://southern-nrg.com/novedades/'),
    ('Río Negro','https://rionegro.gov.ar/'),
    ('Santa Fe / ENERFE','https://www.santafe.gob.ar/ms/enerfe/'),
    ('Pluspetrol','https://www.pluspetrol.net/es/noticias'),
    ('Tecpetrol','https://www.tecpetrol.com/es/noticias'),
    ('Pampa Energía','https://pampa.com/prensa/'),
    ('Litoralgas','https://www.litoralgas.com.ar/site/informacion-util/noticias/'),
    ('TotalEnergies','https://totalenergies.com/newsroom'),
    ('AXION','https://www.axionenergy.com/en-movimiento/'),
    ('Secretaría de Energía','https://www.argentina.gob.ar/economia/energia/noticias'),
]

def norm(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower()) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()

def canonical_url(url):
    u=urlsplit(str(url or ''))
    if u.scheme not in ('http','https') or not u.netloc or u.username or u.password: return ''
    qs=[(k,v) for k,v in parse_qsl(u.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit(('https',u.netloc.lower().removeprefix('www.'),u.path.rstrip('/') or '/',urlencode(qs),''))

def ident(*parts):
    return hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:24]

def date_value(value):
    try:
        value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except (ValueError,TypeError): return None

def due(state, now, hours):
    last=date_value(state.get('checkedAt'))
    retry=date_value(state.get('retryAt'))
    if retry and now < retry: return False
    if state.get('status')=='error': return not retry or now>=retry
    return not last or now-last >= timedelta(hours=hours)

def matches(project, title, description=''):
    """A distinctive name or an approved combination of context is required."""
    t=' '+norm(title+' '+description)+' '
    config=project.get('matching',{})
    if any(' '+norm(term)+' ' in t for term in config.get('exclude',[])): return []
    found=[a for a in config.get('strong',[]) if ' '+norm(a)+' ' in t]
    for group in config.get('combinations',[]):
        if all(' '+norm(term)+' ' in t for term in group): found.append(' + '.join(group))
    return found

def summary(project, title, description, source):
    t=norm(title+' '+description)
    topics=[]
    for pattern,label in [
        (r'financ|prestamo|credito','financiación'),(r'licit|concurso|ofertas','licitación o contratación'),
        (r'adjudic|contrato|acuerdo','acuerdos del proyecto'),(r'inaugur|operacion|puesta en marcha|primer gas','puesta en marcha'),
        (r'constru|soldadura|excava|trabajos','trabajos de obra'),(r'ampli|capacidad','ampliación de capacidad'),
        (r'ambient|audiencia|permiso','evaluación ambiental o permisos'),(r'inversion|rigi','inversión o encuadre RIGI')]:
        if re.search(pattern,t): topics.append(label)
    focus=', '.join(topics[:2]) or 'novedades del proyecto'
    return f'{source} aborda {focus} vinculados a {project["name"]}. La referencia se conserva para seguir los hitos de esta obra.'

def signals(title, description, body=''):
    """Proposals only; snippets retain an explicit number and its local scope."""
    content=re.sub(r'\s+',' ', ' '.join([title,description,body]))
    clean=norm(title+' '+description)
    capacity_contest=bool(re.search(r'concurso.*capacidad|adjudicar.*capacidad|contratacion.*transporte firme',clean))
    out=[]
    for regex,stage in [
        (r'cancelad|suspendid|paralizad','Suspendido / cancelación a verificar'),
        (r'puesta en marcha|entro en operacion|comenzo a operar|inaugur','Puesta en marcha / operación a verificar'),
        (r'comenz.*constru|inicio.*obra|soldadura|excava','Construcción a verificar'),
        (r'adjudic','Adjudicación a verificar'),(r'licit|concurso','Licitación / concurso a verificar')]:
        if capacity_contest and stage in ('Adjudicación a verificar','Licitación / concurso a verificar'):continue
        if re.search(regex,clean): out.append({'field':'stage','proposal':stage,'kind':'status','scope':'Por verificar; puede referir a un componente'})
    # Accept an explicit proximity to "avance"; never convert 80 % of capacity contracts.
    for m in re.finditer(r'(?:avance(?:\s+(?:físico|fisico|global|general|de\s+(?:la\s+)?(?:obra|construcción|construccion)))?)[^%.]{0,65}?(\d{1,3}(?:[.,]\d+)?)\s*%',content,re.I):
        value=float(m.group(1).replace(',','.'))
        if not 0 <= value <= 100: continue
        start=max(0,m.start()-45);end=min(len(content),m.end()+80)
        fragment=content[start:end]
        financial=bool(re.search(r'financier|presupuest|desembolso',fragment,re.I))
        component=bool(re.search(r'cruces|soldadur|caños|canos|tramo|modulo|módulo',fragment,re.I))
        out.append({'field':'progress','proposal':value,'kind':'progress','scope':'Financiero' if financial else 'Componente por verificar' if component else 'Físico / alcance por verificar', 'evidence':' '.join(fragment.split()[:20])})
    return out

def parse_document(raw, url):
    if raw[:4]==b'%PDF':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        body=' '.join(page.extract_text() or '' for page in list(reader.pages)[:45])
        return {'title':(reader.metadata or {}).get('/Title') or urlsplit(url).path.rsplit('/',1)[-1], 'description':'','body':body,'date':None,'datePrecision':'unknown','hash':hashlib.sha256(raw).hexdigest()}
    soup=BeautifulSoup(raw,'html.parser')
    article=soup.find('article') or soup.find('main') or soup
    title=soup.find('meta',property='og:title')
    title=title.get('content') if title else (article.find('h1') or soup.find('title'))
    if not isinstance(title,str): title=title.get_text(' ',strip=True) if title else ''
    desc=soup.find('meta',attrs={'name':'description'}) or soup.find('meta',property='og:description')
    description=desc.get('content','') if desc else ''
    stamp=None
    meta=soup.find('meta',property='article:published_time')
    if meta: stamp=meta.get('content')
    if not stamp:
        time=article.find('time',datetime=True)
        if time: stamp=time.get('datetime')
    def visit(x):
        nonlocal stamp
        if isinstance(x,list):
            for v in x: visit(v)
        elif isinstance(x,dict):
            if not stamp and x.get('datePublished'): stamp=x['datePublished']
            for v in x.values():
                if isinstance(v,(list,dict)): visit(v)
    for script in soup.find_all('script',type='application/ld+json'):
        try:visit(json.loads(script.get_text()))
        except (ValueError,TypeError):pass
    for node in article.select('script, style, nav, footer, header, aside, .related-posts, .sidebar'): node.decompose()
    # Text paragraphs rather than navigation lists: stable hash ignores rotating cards.
    paragraphs=article.find_all(['h1','h2','p','li'])
    body=' '.join(n.get_text(' ',strip=True) for n in paragraphs) if paragraphs else article.get_text(' ',strip=True)
    body=re.sub(r'\s+',' ',body)
    precision='day' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(stamp)) else 'instant' if date_value(stamp) else 'unknown'
    if precision=='unknown': stamp=None
    return {'title':title[:250],'description':description[:400],'body':body,'date':stamp,'datePrecision':precision,'hash':hashlib.sha256((title+'|'+body).encode()).hexdigest()}

def bounded_fetch(fetch, url):
    raw=fetch(url,timeout=12)
    if len(raw)>16_000_000: raise ValueError('Documento excede límite de lectura de 16 MB')
    return raw

def register_news(registry, project, row, seen_at, official=False):
    url=canonical_url(row.get('url'))
    if not url: return
    found=matches(project,row.get('title',''),row.get('desc',''))
    if not found: return
    uid=ident(project['id'],url)
    previous=registry['news'].get(uid,{})
    published=row.get('publishedAt') if row.get('dateType')=='published' else None
    doc=row.get('_document',{})
    if doc: published=doc.get('date')
    known=next((s for s in registry.get('sources',[]) if canonical_url(s['url'])==url),None)
    if not published and known:published=known.get('date')
    if published and str(published)[:4].isdigit() and int(str(published)[:4])<2020:return
    item={**previous,'id':uid,'projectId':project['id'],'url':row['url'],'title':row.get('title') or previous.get('title',''),
          'source':row.get('source') or previous.get('source','Fuente original'),'sourceType':'official' if official else 'press',
          'summary':summary(project,row.get('title',''),row.get('desc',''),row.get('source','La fuente')),
          'publishedAt':published or previous.get('publishedAt'),'datePrecision':doc.get('datePrecision') or ('partial' if published and len(str(published))<10 else 'day' if published and len(str(published))==10 else 'instant' if published else previous.get('datePrecision','unknown')),
          'firstDetectedAt':previous.get('firstDetectedAt') or seen_at,'lastDetectedAt':seen_at,'matchedAliases':found}
    registry['news'][uid]=item
    for signal in signals(row.get('title',''),row.get('desc',''),doc.get('body','')):
        cid=ident(uid,signal['field'],signal['proposal'],signal.get('scope'))
        # Seed-era coverage goes into the archive; it does not claim to be a new change.
        seed_cutoff=project.get('verifiedAt','2026-10-13')[:10]
        historical=bool(published and str(published)[:10]<=seed_cutoff)
        if cid in registry['candidates']:
            old=registry['candidates'][cid]
            if published and not old.get('sourceDate'):
                old.update(sourceDate=published,datePrecision=item['datePrecision'])
                if historical and old['status']=='pending':old['status']='historical'
            continue
        registry['candidates'][cid]={**signal,'id':cid,'projectId':project['id'],'newsId':uid,'sourceUrl':row['url'],
              'sourceType':item['sourceType'],'sourceDate':published,'detectedAt':seen_at,
              'status':'historical' if historical else 'pending','datePrecision':item['datePrecision']}

def apply_decisions(registry, decisions):
    applied=set(registry.get('appliedDecisions',[]))
    projects={p['id']:p for p in registry['projects']}
    for decision in decisions.get('decisions',[]):
        did=decision.get('id');cid=decision.get('candidateId');candidate=registry['candidates'].get(cid)
        if not did or did in applied or not candidate: continue
        project=projects.get(candidate['projectId'])
        reviewed=date_value(decision.get('reviewedAt'))
        if not project or not reviewed or decision.get('outcome') not in ('accept','reject'): continue
        if decision['outcome']=='accept':
            field=candidate['field'];value=decision.get('value')
            if field=='stage':
                if value not in STAGES+['Suspendido','Cancelado','Por verificar']:continue
                project['stage']=value
                project['verifiedStatus']=decision.get('statusText') or value
                project['phase']='Ejecutado' if value=='Operativo' else 'En ejecución' if value in ('Construcción','Puesta en marcha') else 'Proyectado'
            elif field=='progress':
                if not isinstance(value,(int,float)) or not 0<=value<=100:continue
                if not date_value(decision.get('effectiveDate')) or decision.get('scope')!='global_physical':continue
                project['progress']={'value':value,'date':decision['effectiveDate'],'scope':'Avance físico global validado','sourceUrl':candidate['sourceUrl'],'approximate':bool(decision.get('approximate'))}
            else:continue
            project['verifiedAt']=decision['reviewedAt']
            project.setdefault('history',[]).append({'date':decision.get('effectiveDate') or candidate.get('sourceDate'),'label':project['verifiedStatus'] if field=='stage' else f'Avance informado: {value} %','sourceUrl':candidate['sourceUrl'],'verifiedAt':decision['reviewedAt'],'decisionId':did})
        candidate.update(status='accepted' if decision['outcome']=='accept' else 'rejected',reviewedAt=decision['reviewedAt'])
        applied.add(did)
    registry['appliedDecisions']=sorted(applied)

def update_registry(registry, news, fetch, current, checked, decisions=None, official=True):
    r=copy.deepcopy(registry)
    for key in ('news','candidates','sourceChecks'): r.setdefault(key,{})
    # G07 is deliberately excluded even if an older registry or news archive contains it.
    r['projects']=[p for p in r.get('projects',[]) if p['id']!='G07']
    ids={p['id'] for p in r['projects']}
    r['news']={k:v for k,v in r['news'].items() if v.get('projectId') in ids}
    r['candidates']={k:v for k,v in r['candidates'].items() if v.get('projectId') in ids}
    normalized={};remap={}
    for key,item in r['news'].items():
        uid=ident(item['projectId'],canonical_url(item['url']));remap[key]=uid
        prev=normalized.get(uid)
        if not prev or (prev.get('titleType')=='inventory_reference' and item.get('titleType')!='inventory_reference'):
            normalized[uid]={**item,'id':uid}
    r['news']=normalized
    for candidate in r['candidates'].values():
        if candidate.get('newsId') in remap:candidate['newsId']=remap[candidate['newsId']]
    for row in news:
        host=urlsplit(row.get('url','')).netloc.removeprefix('www.')
        trusted={urlsplit(s['url']).netloc.removeprefix('www.') for s in r.get('sources',[]) if s['type']=='official'}
        for project in r['projects']: register_news(r,project,row,checked,official=host in trusted)
    if official:
        def hub_job(spec):
            name,url=spec;state=r['sourceChecks'].get(url,{})
            if not due(state,current,24):return None
            try:
                soup=BeautifulSoup(bounded_fetch(fetch,url),'html.parser')
                links={}
                for a in soup.select('a[href]'):
                    title=a.get_text(' ',strip=True);link=urljoin(url,a['href'])
                    if not 18<=len(title)<=260 or urlsplit(link).netloc.removeprefix('www.')!=urlsplit(url).netloc.removeprefix('www.'):continue
                    if any(x in link for x in ('/tag/','/category/','/author/','#')):continue
                    if any(matches(p,title) for p in r['projects']):links.setdefault(canonical_url(link),(link,title))
                fresh=[]
                for link,title in links.values():
                    st=r['sourceChecks'].get(link,{})
                    # Known article pages revalidated weekly; do not fetch all history hourly.
                    if due(st,current,168):fresh.append((name,link,title))
                return url,{'name':name,'type':'hub','checkedAt':checked,'lastSuccessAt':checked,'status':'ok','discovered':len(links)},fresh[:6]
            except Exception as e:
                return url,{**state,'name':name,'type':'hub','checkedAt':checked,'retryAt':(current+timedelta(hours=6)).isoformat(),'status':'error','error':str(e)[:160]},[]
        jobs=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(hub_job,OFFICIAL_HUBS):
                if result:
                    url,state,new=result;r['sourceChecks'][url]=state;jobs+=new
        # Revalidate up to twelve known documents daily, round-robin by oldest check.
        docs=[s for s in r.get('sources',[]) if s['type']=='official' and any(s['id'] in p['sources'] for p in r['projects'])]
        eligible=[s for s in docs if due(r['sourceChecks'].get(s['url'],{}),current,168)]
        eligible.sort(key=lambda s:r['sourceChecks'].get(s['url'],{}).get('checkedAt',''))
        for s in eligible[:12]:jobs.append((s['title'].split(' — ')[0],s['url'],s['title']))
        dedup={canonical_url(url):(name,url,title) for name,url,title in jobs}
        def doc_job(job):
            name,url,title=job;state=r['sourceChecks'].get(url,{})
            try:
                doc=parse_document(bounded_fetch(fetch,url),url)
                return name,url,doc,{**state,'type':'document','checkedAt':checked,'lastSuccessAt':checked,'status':'ok','hash':doc['hash'],'changed':bool(state.get('hash') and state['hash']!=doc['hash'])}
            except Exception as e:
                return name,url,None,{**state,'type':'document','checkedAt':checked,'retryAt':(current+timedelta(hours=6)).isoformat(),'status':'error','error':str(e)[:160]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name,url,doc,state in pool.map(doc_job,dedup.values()):
                old=r['sourceChecks'].get(url,{})
                r['sourceChecks'][url]=state
                if not doc:continue
                known=next((s for s in r.get('sources',[]) if canonical_url(s['url'])==canonical_url(url)),None)
                if not doc.get('date') and known and known.get('date'):
                    doc['date']=known['date']
                    doc['datePrecision']='day' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',known['date']) else 'partial'
                row={'source':name,'url':url,'title':doc['title'],'desc':doc['description'],'_document':doc}
                for project in r['projects']:
                    register_news(r,project,row,checked,True)
                    # A changed verified document may contain a correction without a new date.
                    related=any(s['id'] in project['sources'] and canonical_url(s['url'])==canonical_url(url) for s in docs)
                    if related and old.get('hash') and old['hash']!=doc['hash']:
                        cid=ident(project['id'],url,doc['hash'])
                        r['candidates'].setdefault(cid,{'id':cid,'projectId':project['id'],'field':'document','kind':'document','proposal':'Cambió el contenido de una fuente del proyecto','sourceUrl':url,'sourceType':'official','sourceDate':doc['date'],'detectedAt':checked,'status':'pending','previousHash':old['hash'],'hash':doc['hash']})
    apply_decisions(r,decisions or {})
    checks=list(r['sourceChecks'].values())
    failures=[s for s in checks if s.get('status')=='error']
    r['meta']={**r.get('meta',{}),'schemaVersion':1,'strategy':'hybrid','generatedAt':checked,'newsLinkedAt':checked,
       'pendingCount':sum(c.get('status')=='pending' for c in r['candidates'].values()),
       'officialLastSuccessAt':max((s.get('lastSuccessAt','') for s in checks),default='') or None,
       'officialErrors':len(failures),'officialStatus':'partial' if failures else 'ok' if checks else 'pending',
       'newsFrequency':'Cada hora, colector existente','officialFrequency':'Descubrimiento diario; documentos en rotación semanal',
       'newsCursor':max((n.get('publishedAt') or '' for n in r['news'].values()),default='') or None}
    return r

def atomic_write(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def update_infrastructure(d,fetch,now,iso):
    if not REGISTRY.exists():return
    try:
        current=now();checked=iso(current)
        r=json.loads(REGISTRY.read_text(encoding='utf-8'))
        decisions=json.loads(DECISIONS.read_text(encoding='utf-8')) if DECISIONS.exists() else {}
        news=d.get('news',[])+d.get('bagsaNews',[])
        r=update_registry(r,news,fetch,current,checked,decisions)
        atomic_write(REGISTRY,r)
        d['infrastructureMeta']=r['meta']
    except Exception as e:
        # Preserve the published registry and let existing modules complete normally.
        d['infrastructureMeta']={**d.get('infrastructureMeta',{}),'lastAttemptAt':iso(),'status':'error','error':str(e)[:200]}
